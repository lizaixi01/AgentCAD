"""Technical-document → structured plate spec, with source traceability.

Two routes, both deterministic:

* ``extract_facts`` — a rule-based extractor for common English / Chinese
  phrasings (sizes, units, hole diameter/count/edge offset, corner radius,
  thickness, material). Every fact records page, line, section and the exact
  text snippet it came from.
* ``verify_citations`` — external agents may do the language understanding
  themselves and submit facts with a quoted snippet + page; the runtime checks
  each quote really occurs on that page before accepting it.

``build_spec`` merges facts, detects missing parameters, contradictions and
ambiguous intent, and never invents values.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import file_error, input_error
from .spec import check_plate
from .units import normalize_unit

NUM = r"(\d+(?:\.\d+)?)"
UNIT = r"\s*(mm|millimet(?:er|re)s?|cm|m|in|inch(?:es)?|毫米|厘米|英寸)?"
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
EN_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8}

# (field, regex, value-group(s), unit-group)
PATTERNS: list[tuple[str, re.Pattern, Any]] = [
    ("units", re.compile(r"(?:all\s+dimensions\s+(?:are\s+)?in|units?\s*[:：=]|单位\s*[:：为]?\s*)\s*"
                         r"(mm|millimet(?:er|re)s?|inch(?:es)?|in|cm|毫米|英寸|厘米)", re.I), "unit"),
    ("size", re.compile(NUM + UNIT + r"\s*[x×X*]\s*" + NUM + UNIT, re.I), "size"),
    ("width", re.compile(r"(?:\bwidth\b|\boverall\s+length\b|\blength\b|长度|长)\s*(?:of\s+)?(?:is|=|[:：])?\s*" + NUM + UNIT, re.I), "val"),
    ("height", re.compile(r"(?:\bheight\b|\bdepth\b|宽度|宽|高度|高)\s*(?:is|=|[:：])?\s*" + NUM + UNIT, re.I), "val"),
    ("hole_diameter", re.compile(r"(?:(?:hole\s+)?diameter|dia\.?|孔径|直径|[Øø⌀Φφ])\s*(?:of\s+)?(?:is|=|[:：])?\s*" + NUM + UNIT, re.I), "val"),
    ("edge_offset", re.compile(r"(?:" + NUM + UNIT + r"\s+from\s+(?:the\s+)?(?:two\s+)?(?:adjacent|nearest|neighbouring|neighboring)?\s*edges?)", re.I), "val"),
    ("edge_offset", re.compile(r"(?:距(?:离)?(?:相邻|两侧|各)?(?:边缘|边)(?:的)?(?:距离)?(?:均|都|各)?(?:为|是)?\s*)" + NUM + UNIT), "val"),
    ("edge_offset", re.compile(r"(?:edge\s+(?:distance|offset)|边距)\s*(?:is|=|[:：])?\s*" + NUM + UNIT, re.I), "val"),
    ("corner_radius", re.compile(r"(?:corner\s+radius|圆角(?:半径)?)\s*(?:of\s+)?(?:is|=|[:：])?\s*R?\s*" + NUM + UNIT, re.I), "val"),
    ("thickness", re.compile(r"(?:thickness|厚度|板厚|厚)\s*(?:is|=|[:：])?\s*" + NUM + UNIT, re.I), "val"),
    ("material", re.compile(r"(?:material|材料|材质)\s*(?:is|=|[:：])?\s*([A-Za-z0-9][A-Za-z0-9\-\.#]*)", re.I), "text"),
    ("hole_count", re.compile(r"(\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|eight)\s*(?:个|x|×)?\s*"
                              r"(?:through[-\s])?(?:mounting\s+)?(?:holes?|孔|通孔|安装孔)", re.I), "count"),
    ("hole_pattern_corners", re.compile(r"(?:each|all\s+four|four)\s+corners?|四角|四个角|每个角", re.I), "flag"),
]
# "## Title", "3 Holes", "2.1 Outline", "四、材料" — a numbered heading must not look like a sentence
# ("15 mm from the adjacent edges." is not a heading)
SECTION_RE = re.compile(r"^\s*(?:#+\s*(.+)|(\d+(?:\.\d+)*)\.?\s+([A-Za-z一-鿿][^.。:：]*)|"
                        r"([一二三四五六七八九十]+)[、.]\s*(\S.*))$")
UNIT_WORD = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+(mm|cm|m|in|inch|inches|millimet)", re.I)


def load_document(path: Path, max_bytes: int) -> list[dict[str, Any]]:
    """Returns pages: [{page, lines: [{line, text, section}]}]."""
    if not path.is_file():
        raise file_error("FILE_NOT_FOUND", f"{path} does not exist")
    if path.stat().st_size > max_bytes:
        raise file_error("FILE_TOO_LARGE", f"{path.name} exceeds {max_bytes} bytes")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            texts = [(p.extract_text() or "") for p in reader.pages]
        except Exception as exc:
            raise file_error("PDF_PARSE_ERROR", f"Cannot read PDF {path.name}: {exc}")
        if not any(t.strip() for t in texts):
            raise file_error("PDF_NO_TEXT", f"{path.name} has no extractable text (scanned?)",
                             hint="OCR is not built in; supply a text version")
    elif suffix in (".txt", ".md", ".markdown", ".text"):
        try:
            raw = path.read_text("utf-8")
        except UnicodeDecodeError:
            raise file_error("ENCODING_ERROR", f"{path.name} is not UTF-8 text")
        texts = raw.split("\f")
    else:
        raise input_error("UNSUPPORTED_DOCUMENT", f"Unsupported document type {suffix!r}", hint="Use .pdf, .txt or .md")
    pages = []
    section = None
    for pno, t in enumerate(texts, start=1):
        lines = []
        for lno, line in enumerate(t.splitlines(), start=1):
            m = SECTION_RE.match(line)
            heading = bool(m and len(line.strip()) < 60 and not UNIT_WORD.match(line))
            if heading:
                section = line.strip().lstrip("#").strip()
            lines.append({"line": lno, "text": line, "section": section, "heading": heading})
        pages.append({"page": pno, "lines": lines})
    return pages


def _unit(u: str | None) -> str | None:
    if not u:
        return None
    u = u.lower()
    if u.startswith("millimet") or u == "毫米":
        return "mm"
    if u.startswith("inch") or u == "英寸":
        return "in"
    if u == "厘米":
        return "cm"
    return normalize_unit(u)


def extract_facts(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts = []
    for pg in pages:
        for ln in pg["lines"]:
            text = ln["text"]
            if not text.strip():
                continue
            if ln.get("heading"):
                # the section number of "3 Holes" is not a hole count; only drop the leading number
                text = re.sub(r"^\s*#*\s*\d+(?:\.\d+)*\.?\s*", lambda mm: " " * len(mm.group(0)), text)
            taken: list[tuple[int, int]] = []
            for field, rx, kind in PATTERNS:
                for m in rx.finditer(text):
                    if any(a < m.end() and m.start() < b for a, b in taken) and field not in ("units", "hole_pattern_corners"):
                        continue
                    if field == "hole_count" and (re.search(r"(各|每)\S{0,2}$", text[:m.start()])
                                                  or re.match(r"\s*(?:at|in|on)\s+each\b", text[m.end():], re.I)):
                        continue  # "one hole at each corner" / "各有一个孔" is a per-location count
                    src = {"page": pg["page"], "line": ln["line"], "section": ln["section"], "text": ln["text"].strip(),
                           "match": m.group(0).strip(), "span": [m.start(), m.end()]}
                    if kind == "size":
                        u1, u2 = _unit(m.group(2)), _unit(m.group(4))
                        facts.append({"field": "width", "value": float(m.group(1)), "unit": u1 or u2, "source": src})
                        facts.append({"field": "height", "value": float(m.group(3)), "unit": u2 or u1, "source": src})
                    elif kind == "val":
                        facts.append({"field": field, "value": float(m.group(1)), "unit": _unit(m.group(2)), "source": src})
                    elif kind == "unit":
                        facts.append({"field": "units", "value": _unit(m.group(1)), "unit": None, "source": src})
                    elif kind == "text":
                        facts.append({"field": field, "value": m.group(1), "unit": None, "source": src})
                    elif kind == "count":
                        g = m.group(1).lower()
                        n = int(g) if g.isdigit() else CN_NUM.get(g, EN_NUM.get(g))
                        facts.append({"field": field, "value": n, "unit": None, "source": src})
                    elif kind == "flag":
                        facts.append({"field": "hole_pattern", "value": "corners", "unit": None, "source": src})
                    taken.append((m.start(), m.end()))
    return facts


def verify_citations(pages: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check agent-supplied facts: each needs {field, value, quote, page}; the quote must occur on that page."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", "", s).lower()

    out = []
    for i, f in enumerate(facts):
        if not isinstance(f, dict) or "field" not in f or "value" not in f:
            raise input_error("INVALID_FACT", f"facts[{i}] needs 'field' and 'value'")
        quote = f.get("quote")
        page = f.get("page")
        ok = False
        hit = None
        if quote:
            for pg in pages:
                if page is not None and pg["page"] != page:
                    continue
                for ln in pg["lines"]:
                    if norm(quote) and norm(quote) in norm(ln["text"]):
                        ok, hit = True, {"page": pg["page"], "line": ln["line"], "section": ln["section"],
                                         "text": ln["text"].strip(), "match": quote}
                        break
                if not ok:  # quotes may span lines in PDFs
                    whole = norm("".join(l["text"] for l in pg["lines"]))
                    if norm(quote) in whole:
                        ok, hit = True, {"page": pg["page"], "line": None, "section": None, "text": quote, "match": quote}
                if ok:
                    break
        out.append({"field": f["field"], "value": f["value"], "unit": f.get("unit"),
                    "source": hit if ok else {"page": page, "text": quote, "unverified": True},
                    "citation_verified": ok, "origin": "agent"})
    return out


REQUIRED = ["units", "width", "height"]


def build_spec(facts: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge facts into a plate spec. Returns {status, spec, issues, traceability}."""
    issues: list[dict[str, Any]] = []
    by_field: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        if f.get("citation_verified") is False:
            issues.append({"code": "CITATION_NOT_FOUND", "severity": "error", "field": f["field"],
                           "message": f"Quote for {f['field']} was not found in the document", "sources": [f["source"]]})
            continue
        by_field.setdefault(f["field"], []).append(f)

    # document unit
    unit_facts = by_field.get("units", [])
    units = {f["value"] for f in unit_facts}
    explicit = {f["unit"] for fs in by_field.values() for f in fs if f.get("unit")}
    if len(units) > 1:
        issues.append({"code": "SPEC_CONFLICT", "severity": "error", "field": "units",
                       "message": f"Document states several units {sorted(units)}", "sources": [f["source"] for f in unit_facts]})
    doc_unit = next(iter(units)) if len(units) == 1 else (next(iter(explicit)) if len(explicit) == 1 else None)

    spec: dict[str, Any] = {"kind": "plate", "units": doc_unit, "source": {}}
    trace: dict[str, Any] = {}

    def resolve(field: str) -> Any:
        fs = by_field.get(field, [])
        if not fs:
            return None
        vals = []
        for f in fs:
            v = f["value"]
            if isinstance(v, float) and f.get("unit") and doc_unit and f["unit"] != doc_unit:
                from .units import convert
                v = convert(v, f["unit"], doc_unit)
            vals.append((v, f))
        distinct = {round(v, 9) if isinstance(v, float) else v for v, _ in vals}
        if len(distinct) > 1:
            issues.append({"code": "SPEC_CONFLICT", "severity": "error", "field": field,
                           "message": f"Contradictory values for {field}: {sorted(map(str, distinct))}",
                           "sources": [f["source"] for _, f in vals]})
            return None
        trace[field] = [f["source"] for _, f in vals]
        return vals[0][0]

    for field in ("width", "height", "corner_radius", "thickness", "material"):
        v = resolve(field)
        if v is not None:
            spec[field] = v
            spec["source"][field] = trace[field][0]
    if doc_unit is None:
        issues.append({"code": "UNITS_UNDEFINED", "severity": "error", "field": "units",
                       "message": "The document never states the length unit"})
    else:
        trace["units"] = [f["source"] for f in unit_facts] or "inferred from explicit value units"

    dia = resolve("hole_diameter")
    count = resolve("hole_count")
    pattern = resolve("hole_pattern")
    off = resolve("edge_offset")
    mentions_holes = any(k in by_field for k in ("hole_diameter", "hole_count", "hole_pattern", "edge_offset"))
    if mentions_holes:
        hole: dict[str, Any] = {"pattern": pattern}
        if pattern is None and count == 4 and off is not None:
            issues.append({"code": "AMBIGUOUS_INTENT", "severity": "warning", "field": "hole_pattern",
                           "message": "4 holes with an edge offset but no explicit 'corner' placement; assuming corners is NOT done automatically"})
        if pattern is None:
            issues.append({"code": "SPEC_MISSING_PARAM", "severity": "error", "field": "hole_pattern",
                           "message": "Hole placement (e.g. 'at each corner') is not stated"})
        if dia is None and "hole_diameter" not in [i.get("field") for i in issues]:
            issues.append({"code": "SPEC_MISSING_PARAM", "severity": "error", "field": "hole_diameter",
                           "message": "Hole diameter is not stated"})
        if pattern == "corners":
            if off is None and "edge_offset" not in [i.get("field") for i in issues]:
                issues.append({"code": "SPEC_MISSING_PARAM", "severity": "error", "field": "edge_offset",
                               "message": "Distance of hole centers from the edges is not stated"})
            if count is not None and count != 4:
                issues.append({"code": "SPEC_CONFLICT", "severity": "error", "field": "hole_count",
                               "message": f"{count} holes stated but corner placement implies 4",
                               "sources": trace.get("hole_count", []) + trace.get("hole_pattern", [])})
        hole.update({"diameter": dia, "edge_offset": off,
                     "source": {k: trace.get(k, [None])[0] for k in ("hole_diameter", "edge_offset", "hole_pattern")}})
        spec["holes"] = [hole]

    for f in REQUIRED[1:]:
        if f not in spec and f not in [i.get("field") for i in issues]:
            issues.append({"code": "SPEC_MISSING_PARAM", "severity": "error", "field": f,
                           "message": f"Plate {f} is not stated"})

    # explicit confirmations / additions by the calling agent (recorded as such)
    if overrides:
        for k, v in overrides.items():
            if k == "holes":
                spec["holes"] = v
            else:
                spec[k] = v
            trace[k] = [{"origin": "caller_override"}]
            issues = [i for i in issues if not (i.get("field") == k or (k == "holes" and str(i.get("field", "")).startswith(("hole", "edge"))))]

    # geometric consistency (only if the basics are present)
    if spec.get("units") and spec.get("width") and spec.get("height") and \
            all(h.get("diameter") and h.get("pattern") for h in spec.get("holes", [])) and \
            not any(i["severity"] == "error" for i in issues):
        geo_issues, _ = check_plate({k: v for k, v in spec.items()})
        for gi in geo_issues:
            issues.append({**gi, "severity": "error", "field": gi.get("path"),
                           "sources": [s for k in ("width", "height", "hole_diameter", "edge_offset") for s in trace.get(k, [])]})

    errors = [i for i in issues if i["severity"] == "error"]
    status = "ok" if not errors else ("conflict" if any(i["code"] == "SPEC_CONFLICT" for i in errors) else "incomplete")
    if spec.get("holes") == []:
        spec.pop("holes")
    return {"status": status, "spec": spec, "issues": issues, "traceability": trace}
