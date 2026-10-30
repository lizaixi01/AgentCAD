"""Generic drawing-integrity checks (no spec needed)."""
from __future__ import annotations

import math
import re
from typing import Any

from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.math import Vec3

from .. import geom as G
from ..errors import AgentCADError
from ..model import circle_wcs, get_tag
from ..tolerances import check_dimension_tolerance
from ..units import unit_from_insunits
from .features import Features, measure_dimension

NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
# feet-inches 3'-6 1/2", inches with fraction 11-1/4" or 6 1/2", plain fractions 1/4, decimals
ARCH_RE = re.compile(r"(?:(\d+(?:\.\d+)?)')?\s*-?\s*(\d+(?:\.\d+)?)?(?:[\s-]+(\d+)/(\d+))?\"")
FEET_RE = re.compile(r"(\d+(?:\.\d+)?)'")
WORD_RE = re.compile(r"[A-Za-z@]+")
UNIT_RE = re.compile(r"\s*(?:mm|cm|m|in|ft|deg|°)\s*$", re.I)
PREFIX_RE = re.compile(r"^(?:\d+\s*[X×x]\s*)?(?:%%[CcDdPp]|[Ø⌀R±])?", re.I)


def dimension_plain_text(txt: str) -> str:
    """Override text without MTEXT formatting, alternate units [..] and the count/Ø/R prefix."""
    from ezdxf.tools.text import plain_mtext
    t = plain_mtext(txt) if ("\\" in txt or "{" in txt) else txt
    t = re.sub(r"\[[^\]]*\]", "", t).replace("%%c", "").replace("%%C", "").strip()
    return UNIT_RE.sub("", PREFIX_RE.sub("", t, count=1).strip())


def text_values(t: str) -> list[float]:
    vals = []
    for m in ARCH_RE.finditer(t):
        ft, inch, num, den = m.groups()
        if ft or inch or num:
            v = float(ft or 0) * 12 + float(inch or 0) + (float(num) / float(den) if num and float(den) else 0)
            vals.append(v)
    rest = ARCH_RE.sub(" ", t)
    vals += [float(v) * 12 for v in FEET_RE.findall(rest)]
    rest = FEET_RE.sub(" ", rest)
    return vals + [float(n) for n in NUM_RE.findall(rest)]


def crosses(s0, s1, direction) -> bool:
    """A point partway along an edge fixes a linear dimension only if the edge is not parallel to the
    measured direction (a wall face for a horizontal dimension, not the floor line it runs along)."""
    if direction is None:
        return False
    d = G.sub(s1, s0)
    n = G.norm(d)
    return n > 0 and abs(G.cross(G.mul(d, 1 / n), direction)) > 0.1


class BlockSnaps:
    """Vertices of geometry inside block references, built only when a dimension anchor is not on top-level
    geometry: real drawings dimension walls and parts that are blocks (examples/trials/real_dwg_survey)."""

    def __init__(self, doc: Drawing, layout: str | None = None) -> None:
        from ..model import layout_spaces
        self.doc = doc
        self.space = layout_spaces(doc, layout)[0]
        self.has_xref = any(b.block.is_xref for b in doc.blocks if b.block is not None and
                            not b.name.startswith("*")) and any(
            i.dxf.name in doc.blocks and doc.blocks.get(i.dxf.name).block.is_xref
            for i in self.space.query("INSERT"))
        self._grid: dict[tuple[int, int], list] | None = None
        self._cell = 1.0

    def _build(self) -> None:
        from .features import snap_points
        pts: list[tuple[float, float]] = []
        segs: list[tuple[tuple[float, float], tuple[float, float]]] = []

        def walk(ins, depth: int) -> None:
            try:
                ents = list(ins.virtual_entities())
            except Exception:
                return
            for v in ents:
                t = v.dxftype()
                if t == "INSERT" and depth < 4:
                    walk(v, depth + 1)
                elif t == "LINE":
                    s0, s1 = (v.dxf.start.x, v.dxf.start.y), (v.dxf.end.x, v.dxf.end.y)
                    pts.extend([s0, s1])
                    segs.append((s0, s1))
                elif t in ("CIRCLE", "ARC"):
                    c, r, a1, a2 = circle_wcs(v)
                    pts.append(c)
                    if t == "ARC":
                        pts.extend([G.polar(c, r, a1), G.polar(c, r, a2)])
                    else:
                        pts.extend(G.polar(c, r, a) for a in (0, 90, 180, 270))
                elif t == "LWPOLYLINE":
                    vs = [(p[0], p[1]) for p in v.vertices_in_wcs()]
                    pts.extend(vs)
                    segs.extend(zip(vs, vs[1:] + (vs[:1] if v.closed else [])))
                else:
                    pts.extend(snap_points(v))

        for ins in self.space.query("INSERT"):
            walk(ins, 0)
        self._grid = {}
        for p in pts:
            self._grid.setdefault((math.floor(p[0] / self._cell), math.floor(p[1] / self._cell)), []).append(p)
        self._segs = segs

    def near(self, a, snap: float, direction=None) -> bool:
        if self._grid is None:
            self._cell = max(snap * 4, 1e-6)
            self._build()
        i, j = math.floor(a[0] / self._cell), math.floor(a[1] / self._cell)
        return any(G.dist(a, p) <= snap for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   for p in self._grid.get((i + di, j + dj), ())) or             any(G.dist_to_segment(a, s0, s1) <= snap and crosses(s0, s1, direction) for s0, s1 in self._segs)


def issue(code: str, severity: str, message: str, entities: list[str] | None = None, **details: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"code": code, "severity": severity, "category": "geometry",
                         "message": message, "entities": entities or []}
    if details:
        d["details"] = details
    return d


def _finite(*vals: float) -> bool:
    return all(math.isfinite(v) for v in vals)


def geometry_key(e, q: float) -> tuple | None:
    """Canonical rounded geometry key for duplicate detection."""
    t = e.dxftype()
    x = e.dxf

    def rp(p):
        return (round(p[0] / q), round(p[1] / q))

    if t == "LINE":
        a, b = rp(x.start), rp(x.end)
        return (t, x.layer, min(a, b), max(a, b))
    if t == "CIRCLE":
        return (t, x.layer, rp(x.center), round(x.radius / q))
    if t == "ARC":
        c, rad, s, en = circle_wcs(e)
        return (t, x.layer, rp(c), round(rad / q), round(s, 4), round(en, 4))
    if t == "LWPOLYLINE":
        pts = tuple(rp(p) + (round(b, 6),) for *p, b in ((p[0], p[1], p[2]) for p in e.get_points("xyb")))
        return (t, x.layer, bool(e.closed), pts)
    if t == "POINT":
        return (t, x.layer, rp(x.location))
    if t in ("TEXT",):
        return (t, x.layer, rp(x.insert), x.text)
    if t == "INSERT":
        return (t, x.layer, x.name, rp(x.insert), round(x.rotation, 6))
    if t == "DIMENSION":
        m = measure_dimension(e)[1]
        return (t, x.layer, x.dimtype & 0x0F, round(x.get("angle", 0.0) % 180, 6),
                rp(x.defpoint2) if x.hasattr("defpoint2") else rp(x.defpoint),
                rp(x.defpoint3) if x.hasattr("defpoint3") else rp(x.defpoint4), None if m is None else round(m / q))
    return None


XDATA_LIMIT = 16 * 1024


def xdata_issues(doc: Drawing, e) -> list[dict[str, Any]]:
    """AutoCAD 2027 discards the *entire* drawing on DXFIN when an entity carries XDATA
    of an unregistered APPID or more than 16 KB of XDATA (research/autocad, exp_blocked_items)."""
    xd = getattr(e, "xdata", None)
    if not xd or not xd.data:
        return []
    out = []
    size = 0
    for app, tags in xd.data.items():
        if app not in doc.appids:
            out.append(issue("XDATA_APPID_UNREGISTERED", "error",
                             f"XDATA uses APPID {app!r} that is not in the APPID table; AutoCAD rejects the whole file",
                             [e.dxf.handle], appid=app))
        size += len(app) + sum(len(str(t.value).encode("utf-8")) + 2 for t in tags)
    if size > XDATA_LIMIT:
        out.append(issue("XDATA_TOO_LARGE", "error", f"XDATA of {size} bytes exceeds AutoCAD's 16 KB per entity; "
                         "AutoCAD rejects the whole file", [e.dxf.handle], bytes=size))
    return out


CJK_RE = re.compile(r"[⺀-鿿가-힯＀-￯]")
ANNOTATION_RATIO = 250  # median dimension length / arrow size; a sheet-wide 400 mm dimension with 2.5 mm arrows is 160


def _text_items(msp):
    for e in msp.query("TEXT MTEXT"):
        yield e, e.dxf.get("style", "Standard"), (e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text)
    for ins in msp.query("INSERT"):
        for a in ins.attribs:
            yield a, a.dxf.get("style", "Standard"), a.dxf.text


def annotation_issues(doc: Drawing, layout: str | None = None) -> list[dict[str, Any]]:
    """Readability problems seen only when AutoCAD plots the drawing (examples/trials)."""
    out = []
    from ..model import layout_spaces
    msp = layout_spaces(doc, layout)[0]
    bad: dict[str, list[str]] = {}
    for e, style, text in _text_items(msp):
        if not text or not CJK_RE.search(text) or style not in doc.styles:
            continue
        st = doc.styles.get(style)
        font = (st.dxf.get("font") or "").lower()
        if (font.endswith(".shx") or "." not in font) and not st.dxf.get("bigfont"):
            bad.setdefault(style, []).append(e.dxf.handle)
    for style, hs in bad.items():
        out.append(issue("TEXT_GLYPHS_MISSING", "warning",
                         f"{len(hs)} text(s) contain Chinese/CJK characters but style {style!r} uses an SHX font "
                         "without a big font; AutoCAD shows them as '???'", hs[:50],
                         hint="Set the style's big font (e.g. gbcbig.shx) or use a TrueType font"))
    ratios, small = [], []
    for d in msp.query("DIMENSION"):
        kind, m = measure_dimension(d)
        if kind not in ("linear", "aligned") or not m:
            continue
        try:
            ov = d.override()  # per-entity DSTYLE overrides, then the dimension style
            scale, asz = ov.get("dimscale", 1.0), ov.get("dimasz", 0.18)
        except Exception:
            continue
        if not scale or not asz:  # dimscale 0 = scaled by the paper-space viewport: cannot tell here
            continue
        ratios.append(m / (asz * scale))
        small.append(d.dxf.handle)
    if ratios and sorted(ratios)[len(ratios) // 2] > ANNOTATION_RATIO:
        out.append(issue("ANNOTATION_TOO_SMALL", "warning",
                         f"Dimensions are typically {sorted(ratios)[len(ratios) // 2]:.0f}x longer than their arrows; "
                         "arrows and text vanish when the sheet is plotted", small[:50],
                         hint="Use the set_annotation_scale operation (e.g. 50 or 100 for building plans "
                              "in mm), or create_drawing(annotation_scale=...)"))
    return out


MIN_PRINTED_TEXT = 2.5  # mm on paper; ISO 3098 / GB/T 14691 smallest standard character height


def _model_text_heights(doc: Drawing):
    """(handle, kind, height in model units, (x, y)) for text and dimension text in model space."""
    for e in doc.modelspace():
        t = e.dxftype()
        try:
            if t == "TEXT":
                yield e.dxf.handle, "text", e.dxf.height, (e.dxf.insert.x, e.dxf.insert.y)
            elif t == "MTEXT":
                yield e.dxf.handle, "text", e.dxf.char_height, (e.dxf.insert.x, e.dxf.insert.y)
            elif t == "INSERT":
                for a in e.attribs:
                    if a.dxf.text:
                        yield a.dxf.handle, "text", a.dxf.height, (a.dxf.insert.x, a.dxf.insert.y)
            elif t == "DIMENSION":
                ov = e.override()
                scale, txt = ov.get("dimscale", 1.0), ov.get("dimtxt", 0.18)
                if not scale:  # DIMSCALE 0: AutoCAD sizes it to the viewport, always readable
                    continue
                p = e.dxf.get("text_midpoint") or e.dxf.get("defpoint")
                yield e.dxf.handle, "dimension", txt * scale, (p.x, p.y)
        except Exception:
            continue


def printed_text_issues(doc: Drawing) -> list[dict[str, Any]]:
    """Text that comes out too small on paper: model text shown through a scaled viewport, and paper text.
    The H6 trials put a 1:1 drawing with 3.5 mm dimensions behind a 1:2 viewport and printed 1.75 mm text."""
    from ..model import is_model
    out = []
    model_text = None
    for name in doc.layouts.names_in_taborder():
        if is_model(name):
            continue
        lay = doc.layouts.get(name)
        for vp in lay.query("VIEWPORT"):
            vh = vp.dxf.get("view_height", 0) or 0
            if vp.dxf.get("id", 0) == 1 or vh <= 0 or vp.dxf.get("status", 1) == 0:
                continue
            s = vp.dxf.height / vh
            c = vp.dxf.view_center_point
            hw, hh = vp.dxf.width / s / 2, vh / 2
            if model_text is None:
                model_text = list(_model_text_heights(doc))
            small = [(h, k, ht) for h, k, ht, (x, y) in model_text
                     if abs(x - c.x) <= hw and abs(y - c.y) <= hh and 0 < ht * s < MIN_PRINTED_TEXT - 1e-9]
            if small:
                lo = min(ht for _, _, ht in small) * s
                kinds = sorted({k for _, k, _ in small})
                out.append(issue("PRINTED_TEXT_TOO_SMALL", "warning",
                                 f"Viewport {vp.dxf.handle} in layout {name!r} shows the model at "
                                 f"{_ratio(s)}: {len(small)} {'/'.join(kinds)} text(s) print as small as "
                                 f"{lo:.2f} mm (minimum {MIN_PRINTED_TEXT} mm)", [h for h, _, _ in small][:50],
                                 layout=name, viewport=vp.dxf.handle, scale=s,
                                 min_model_height=round(MIN_PRINTED_TEXT / s, 6),
                                 hint=f"Make model text and dimension text at least {MIN_PRINTED_TEXT / s:g} "
                                      "(modify text 'height' / dimension 'text_height'), or use a larger "
                                      "viewport scale"))
        tiny = [e.dxf.handle for e in lay.query("TEXT MTEXT")
                if 0 < (e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height) < MIN_PRINTED_TEXT - 1e-9]
        if tiny:
            out.append(issue("PRINTED_TEXT_TOO_SMALL", "warning",
                             f"{len(tiny)} text(s) on layout {name!r} are under {MIN_PRINTED_TEXT} mm high on paper",
                             tiny[:50], layout=name, hint=f"Use a text height of at least {MIN_PRINTED_TEXT} mm"))
    return out


def _ratio(s: float) -> str:
    return f"1:{1 / s:g}" if s < 1 else f"{s:g}:1"


def run_generic_checks(doc: Drawing, feats: Features, *, bounds: list | None = None,
                       tolerance: float = 1e-6, contour_layers: list[str] | None = None,
                       layout: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    from ..model import layout_spaces
    msp = layout_spaces(doc, layout)[0]
    ins = doc.header.get("$INSUNITS", 0)
    if unit_from_insunits(ins) is None:
        out.append(issue("UNITS_UNDEFINED", "warning", f"$INSUNITS={ins} is not a supported explicit length unit"))

    seen: dict[tuple, str] = {}
    for space in doc.layouts:
        for entity in space:
            if entity.dxf.layer.upper() in {"CONSTRUCTION", "DEFPOINTS"} or entity.dxftype() in {"XLINE", "RAY"}:
                out.append(issue("CONSTRUCTION_GEOMETRY", "warning", "Construction geometry remains in the drawing",
                                 [entity.dxf.handle], layout=space.name))
    for e in msp:
        t = e.dxftype()
        h = e.dxf.handle
        x = e.dxf
        # degenerate / invalid geometry
        if t == "LINE":
            if not _finite(x.start.x, x.start.y, x.end.x, x.end.y):
                out.append(issue("INVALID_COORDINATE", "error", "Non-finite coordinate", [h]))
            elif (x.end - x.start).magnitude < tolerance:
                out.append(issue("DEGENERATE_GEOMETRY", "error", "Zero-length line", [h]))
        elif t in ("CIRCLE", "ARC"):
            if not _finite(x.center.x, x.center.y, x.radius):
                out.append(issue("INVALID_COORDINATE", "error", "Non-finite coordinate/radius", [h]))
            elif x.radius <= tolerance:
                out.append(issue("DEGENERATE_GEOMETRY", "error", f"Radius {x.radius} <= 0", [h]))
        elif t == "LWPOLYLINE":
            pts = e.get_points("xy")
            if len({(round(p[0], 9), round(p[1], 9)) for p in pts}) < 2:
                out.append(issue("DEGENERATE_GEOMETRY", "error", "Polyline has fewer than 2 distinct vertices", [h]))
        elif t == "INSERT" and x.name not in doc.blocks:
            out.append(issue("UNDEFINED_BLOCK", "error", f"Block {x.name!r} is not defined", [h]))
        elif t == "HATCH" and not len(e.paths):
            out.append(issue("DEGENERATE_GEOMETRY", "error", "Hatch has no boundary path", [h]))
        elif t in ("XLINE", "RAY") and Vec3(x.unit_vector).magnitude < 1e-9:
            out.append(issue("DEGENERATE_GEOMETRY", "error", f"{t} has no direction", [h]))
        if x.layer not in doc.layers:
            out.append(issue("UNDEFINED_LAYER", "warning", f"Layer {x.layer!r} has no layer table entry", [h]))
        if t == "ARC" and not (0 <= x.start_angle < 360 and 0 <= x.end_angle < 360):
            out.append(issue("ARC_ANGLE_NOT_NORMALIZED", "warning",
                             f"Arc angles {x.start_angle}/{x.end_angle} outside [0, 360): AutoCAD AUDIT reports them", [h]))
        out.extend(xdata_issues(doc, e))
        # duplicates
        k = geometry_key(e, max(tolerance, 1e-9))
        if k is not None:
            if k in seen:
                out.append(issue("DUPLICATE_ENTITY", "error", f"{t} {h} duplicates {seen[k]}", [seen[k], h]))
            else:
                seen[k] = h

    out.extend(annotation_issues(doc, layout))
    out.extend(printed_text_issues(doc))

    # Tolerance declarations are document integrity, including nested/unreferenced
    # blocks. Walk stored entities once, not virtual INSERT copies (which can be
    # repeated, transformed or cyclic). This does not certify block placement.
    for entity in doc.entitydb.values():
        if entity.dxftype() != "DIMENSION":
            continue
        try:
            check_dimension_tolerance(entity, unit_from_insunits(ins) or "mm")
        except AgentCADError as exc:
            out.append(issue(exc.code, "error", exc.message, [entity.dxf.handle]))

    # dimensions: stored text / measurement consistent with definition points
    blocks = BlockSnaps(doc, layout)
    for d in feats.dimensions:
        if d["measurement"] is None:
            out.append(issue("DIMENSION_UNMEASURABLE", "warning", "Dimension type cannot be re-measured", [d["id"]]))
            continue
        txt = (d["text"] or "").strip()
        if txt and "<>" not in txt:
            plain = dimension_plain_text(txt)
            nums = text_values(plain)
            shown = d["scaled_measurement"]
            if nums and not any(abs(n - shown) <= max(tolerance, 0.005 * max(1, abs(n))) for n in nums):
                # a bare value ("2700", "Ø12") that disagrees is an error; a note with several numbers or words
                # ("10R @ 7.09\"", "8×Ø12 EQ SP") cannot be checked reliably, so it is only a warning
                simple = len(nums) == 1 and not WORD_RE.search(plain)
                out.append(issue("DIMENSION_TEXT_MISMATCH", "error" if simple else "warning",
                                 f"Dimension text {txt!r} disagrees with measured value {shown:.6g}",
                                 [d["id"]], expected=shown, actual_text=txt))
        display = d["display_evidence"]
        if display["value"] is None:
            out.append(issue("DIMENSION_DISPLAY_UNVERIFIED", "error" if display["status"] == "hidden" else "warning",
                             "Saved graphics do not establish a visible primary dimension value", [d["id"]],
                             status=display["status"], texts=display["texts"]))
        elif abs(display["value"] - d["scaled_measurement"]) > max(tolerance, (display["resolution"] or 0) / 2 + 1e-9):
            out.append(issue("DIMENSION_RENDER_MISMATCH", "error",
                             "Saved dimension graphics disagree with the scaled geometry beyond display precision",
                             [d["id"]], expected=d["scaled_measurement"], displayed=display["value"], texts=display["texts"]))
        # '<>' of a diameter/radius dimension already carries the Ø / R prefix (seen in AutoCAD 2027 plots)
        before = txt.upper().split("<>")[0].rstrip() if "<>" in txt else ""
        doubled = (d["kind"] == "diameter" and before.endswith(("%%C", "Ø", "⌀"))) or \
            (d["kind"] == "radius" and before.endswith("R") and not before[:-1][-1:].isalpha())
        if doubled:
            out.append(issue("DIMENSION_DOUBLE_PREFIX", "warning",
                             f"Text {txt!r} repeats the {'Ø' if d['kind'] == 'diameter' else 'R'} prefix that "
                             "'<>' already includes; it will show twice", [d["id"]],
                             hint="Write '<>' alone, or e.g. '4X <>'"))
        stored = d.get("stored")
        if stored is not None and d["kind"] in ("angular", "angular3p"):
            stored = math.degrees(stored)  # group 42 holds radians for angular dimensions
        if stored is not None and abs(stored - d["measurement"]) > max(tolerance, 1e-6):
            out.append(issue("DIMENSION_STALE", "warning",
                             f"Stored measurement {stored:.6g} != re-measured {d['measurement']:.6g}", [d["id"]]))
        snap = max(tolerance, 1e-6) * 10
        for a in d["anchors"]:
            on_point = any(G.dist(a, p) <= snap for p, _ in feats.points)
            on_curve = any(abs(G.dist(a, c) - r) <= snap for c, r, _ in feats.curves) or                 (not on_point and any(G.dist_to_segment(a, s0, s1) <= snap and crosses(s0, s1, d["direction"])
                                      for s0, s1 in feats.segments))
            if not (on_point or on_curve) and blocks.has_xref:
                break  # the geometry may live in an external reference that is not loaded: cannot tell
            if not (on_point or on_curve) and not blocks.near(a, snap, d["direction"]):
                out.append(issue("DIMENSION_NOT_ATTACHED", "warning",
                                 f"Dimension anchor {list(map(lambda v: round(v, 6), a))} is not on any geometry point",
                                 [d["id"]]))
                break

    # contours that should be closed
    for layer in contour_layers or []:
        for chain in feats.open_chains:
            ents = [doc.entitydb[h] for h in chain]
            if ents and ents[0].dxf.layer == layer:
                out.append(issue("OPEN_CONTOUR", "error", f"Open contour on layer {layer!r}", chain))

    # bounds
    if bounds:
        (bx0, by0), (bx1, by1) = bounds
        for e in msp:
            try:
                ext = bbox.extents([e], fast=True)
            except Exception:
                continue
            if not ext.has_data:
                continue
            if ext.extmin.x < bx0 - tolerance or ext.extmin.y < by0 - tolerance or \
               ext.extmax.x > bx1 + tolerance or ext.extmax.y > by1 + tolerance:
                out.append(issue("OUT_OF_BOUNDS", "error",
                                 f"{e.dxftype()} {e.dxf.handle} extends outside the drawing bounds",
                                 [e.dxf.handle], bounds=bounds,
                                 extents=[[round(ext.extmin.x, 6), round(ext.extmin.y, 6)],
                                          [round(ext.extmax.x, 6), round(ext.extmax.y, 6)]],
                                 tag=get_tag(e)))
    return out
