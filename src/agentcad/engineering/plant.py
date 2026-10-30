"""Evidence-based foreign plant drawing description and preliminary quantities.

No authored-spec records are required. Connections come from segment endpoints,
T-junctions and fitting boxes; sizes and circuits come from nearby drawing text.
Layout lengths are rectilinear estimates, not installed pipe/cable measurements.
"""

from __future__ import annotations

from collections import defaultdict
import itertools
import math
import re
import statistics

from ezdxf import bbox

from .. import geom as G
from ..errors import input_error
from ..model import circle_wcs, lwpoly_wcs
from ..units import unit_from_insunits


def service(name):
    s = re.sub(r"[\W_]", "", name.lower())
    if any(w in s for w in ("ijswater", "icewater", "ледян")):
        return "ice_water"
    if "cip" in s:
        return "cip_return" if any(w in s for w in ("return", "retour", "возврат")) else "cip_supply"
    if any(w in s for w in ("product", "processpipe", "продукт")):
        return "product"
    if any(w in s for w in ("electr", "epower", "ecallout", "кабел")):
        return "electrical"
    return None


def plain(text):
    text = re.sub(r"\\U\+([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)
    text = re.sub(r"\\[fF][^;]*;", "", text).replace("\\P", " ")
    return (
        text.replace("%%c", "Ø")
        .replace("%%C", "Ø")
        .replace("∅", "Ø")
        .replace("⌀", "Ø")
        .replace("ø", "Ø")
        .strip("{} ")
    )


def tag_name(text):
    text = text.strip().upper()
    if re.match(r"^(DN|SMS)\d", text):
        return None
    if re.fullmatch(r"[A-Z]{1,5}[- ]?\d+(?:-\d+)?", text):
        return re.sub(r"^CP[ -]?(\d+)$", r"CP-\1", text)
    return None


def texts(doc):
    out = []
    for e in doc.modelspace():
        if e.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        out.append(
            {
                "text": plain(e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()),
                "at": tuple(e.dxf.insert)[:2],
                "height": e.dxf.height if e.dxftype() == "TEXT" else e.dxf.char_height,
                "layer": e.dxf.layer,
                "handle": e.dxf.handle,
            }
        )
    return out


def _boxes(doc):
    out = []
    for e in doc.modelspace():
        ext = bbox.extents([e], fast=True)
        if ext.has_data:
            out.append(
                {"handle": e.dxf.handle, "box": [ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y]}
            )
    return out


def _distance_boxes(a, b):
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0), max(a[1] - b[3], b[1] - a[3], 0))


def _inside(p, box, tolerance=0):
    return (
        box[0] - tolerance <= p[0] <= box[2] + tolerance and box[1] - tolerance <= p[1] <= box[3] + tolerance
    )


class Union:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while i != self.parent[i]:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def describe(doc):
    rows, boxes = texts(doc), _boxes(doc)
    if len(boxes) > 20000:
        raise input_error(
            "ANALYSIS_BUDGET", "Foreign drawing analysis supports at most 20000 bounded entities"
        )
    heights = [t["height"] for t in rows if t["height"] > 0]
    height = statistics.median(heights) if heights else 0
    declared = unit_from_insunits(doc.header.get("$INSUNITS", 0))
    # Large engineering labels and equipment symbols in these ranges give millimetre evidence.
    # Small/ambiguous geometry retains its declaration instead of asserting an inferred unit.
    inferred = "mm" if 50 <= height <= 2000 else declared
    warnings = []
    if inferred != declared:
        warnings.append(f"INSUNITS declares {declared}; annotation height {height:g} suggests {inferred}")
    centers = [((r["box"][0] + r["box"][2]) / 2, (r["box"][1] + r["box"][3]) / 2) for r in boxes]
    center = tuple(statistics.median(p[i] for p in centers) for i in (0, 1)) if centers else (0, 0)
    distances = [math.dist(p, center) for p in centers]
    typical = max(statistics.median(distances) if distances else 0, height * 20, 1e-6)
    outliers = [r["handle"] for r, d in zip(boxes, distances) if d > typical * 100]
    kept = [r for r in boxes if r["handle"] not in outliers]
    uf = Union(len(kept))
    # Bounding boxes connected by ordinary annotation-sized gaps form a drawing cluster.
    gap = max(height * 4, typical * 0.01, 1e-6)
    for i, a in enumerate(kept):
        for j in range(i):
            if _distance_boxes(a["box"], kept[j]["box"]) <= gap:
                uf.join(i, j)
    groups = defaultdict(list)
    for i, r in enumerate(kept):
        groups[uf.find(i)].append(r)
    clusters = []
    for group in groups.values():
        bs = [r["box"] for r in group]
        clusters.append(
            {
                "box": [
                    min(b[0] for b in bs),
                    min(b[1] for b in bs),
                    max(b[2] for b in bs),
                    max(b[3] for b in bs),
                ],
                "handles": [r["handle"] for r in group],
            }
        )
    # A closed frame/wall ring encloses disconnected equipment. Merge component envelopes as well.
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(clusters):
            for j in range(i):
                b = clusters[j]
                if _distance_boxes(a["box"], b["box"]) <= gap:
                    b["box"] = [
                        min(a["box"][0], b["box"][0]),
                        min(a["box"][1], b["box"][1]),
                        max(a["box"][2], b["box"][2]),
                        max(a["box"][3], b["box"][3]),
                    ]
                    b["handles"] += a["handles"]
                    clusters.pop(i)
                    merged = True
                    break
            if merged:
                break
    return {
        "units": {
            "declared": declared,
            "inferred": inferred,
            "agree": declared == inferred,
            "evidence": {"median_text_height": height, "method": "annotation-size heuristic"},
        },
        "warnings": warnings,
        "extents": {"outlier_handles": outliers},
        "clusters": sorted(clusters, key=lambda c: c["box"]),
        "layers": [{"name": l.dxf.name, "service": service(l.dxf.name)} for l in doc.layers],
    }


def tag_positions(doc, description, wanted=()):
    occurrences = defaultdict(list)
    for t in texts(doc):
        tag = tag_name(t["text"])
        if tag:
            occurrences[tag].append(t["at"])
    cluster = None
    if any(len(v) > 1 for v in occurrences.values()) and description["clusters"]:
        cluster = min(
            description["clusters"],
            key=lambda c: (
                -sum(any(_inside(p, c["box"]) for p in occurrences.get(t, [])) for t in wanted),
                *c["box"][:2],
            ),
        )["box"]
    positions, ambiguous = {}, []
    for tag, places in occurrences.items():
        places = [p for p in places if cluster is None or _inside(p, cluster)]
        if len(places) == 1:
            positions[tag] = places[0]
        elif places:
            ambiguous.append(tag)
    return {"positions": positions, "ambiguous": ambiguous, "cluster": cluster}


def scale_check(pid, layout):
    common = sorted(pid.keys() & layout.keys())
    ratios = []
    for a, b in itertools.combinations(common, 2):
        ld, pd = math.dist(layout[a], layout[b]), math.dist(pid[a], pid[b])
        if ld >= 2000 and pd > 1e-9:
            ratios.append(pd / ld)
    median = statistics.median(ratios) if ratios else None
    within = sum(abs(r / median - 1) <= 0.1 for r in ratios) / len(ratios) if ratios else 0
    return {
        "verdict": "scaled"
        if len(ratios) >= 3 and within >= 0.8
        else "schematic"
        if len(ratios) >= 3
        else "insufficient_evidence",
        "median_ratio": median,
        "within_10pct": within,
        "pairs": len(ratios),
    }


def _segments(doc):
    pieces, seen = [], set()
    for e in doc.modelspace():
        cls = service(e.dxf.layer)
        if cls in {None, "electrical"} or e.dxftype() not in {"LINE", "LWPOLYLINE", "ARC"}:
            continue
        arc = None
        if e.dxftype() != "LINE" and (abs(e.dxf.extrusion.x) > 1e-9 or abs(e.dxf.extrusion.y) > 1e-9):
            raise input_error("UNSUPPORTED_GEOMETRY", "Plant network requires planar XY curves")
        if e.dxftype() == "LINE":
            parts = [(tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2])]
        elif e.dxftype() == "LWPOLYLINE":
            if any(abs(p[2]) > 1e-12 for p in e.get_points("xyb")):
                raise input_error(
                    "UNSUPPORTED_GEOMETRY",
                    "Plant network currently requires unbulged polylines; use ARC for bends",
                )
            pts = [p[:2] for p in lwpoly_wcs(e)]
            parts = list(zip(pts, pts[1:]))
            if e.closed and len(pts) > 1:
                parts.append((pts[-1], pts[0]))
        else:
            parts = [(tuple(e.start_point)[:2], tuple(e.end_point)[:2])]
            arc = circle_wcs(e)
        for a, b in parts:
            key = (cls, tuple(sorted((tuple(round(v, 6) for v in a), tuple(round(v, 6) for v in b)))), arc)
            if key not in seen:
                seen.add(key)
                pieces.append(
                    {"a": a, "b": b, "service": cls, "handle": e.dxf.handle, "arc": arc}
                )
    return pieces


def _piece_distance(point, piece):
    """Distance to the actual finite curve, never to an ARC's endpoint chord."""
    if piece["arc"] is None:
        return G.dist_to_segment(point, piece["a"], piece["b"])
    center, radius, start, end = piece["arc"]
    if G.angle_in_arc(G.angle_of(G.sub(point, center)), start, end):
        return abs(math.dist(point, center) - radius)
    return min(math.dist(point, piece["a"]), math.dist(point, piece["b"]))


def rmst(points):
    if len(points) < 2:
        return 0
    reached, total = {0}, 0.0
    while len(reached) < len(points):
        distance, j = min(
            (abs(points[i][0] - p[0]) + abs(points[i][1] - p[1]), j)
            for i in reached
            for j, p in enumerate(points)
            if j not in reached
        )
        total += distance
        reached.add(j)
    return total


def takeoff(pid, layout, services=None, allowance=0.2):
    if not 0 <= allowance <= 2:
        raise input_error("INVALID_VALUE", "Cable allowance must be between 0 and 2")
    pd, ld = describe(pid), describe(layout)
    if pd["units"]["inferred"] != "mm" or ld["units"]["inferred"] != "mm":
        raise input_error("UNSUPPORTED_UNITS", "Plant quantities currently require millimetre geometry")
    ps = tag_positions(pid, pd)
    ls = tag_positions(layout, ld, ps["positions"])
    positions, layout_positions = ps["positions"], ls["positions"]
    scale = scale_check(positions, layout_positions)
    pieces = _segments(pid)
    if len(pieces) > 5000:
        raise input_error("ANALYSIS_BUDGET", "Pipe network supports at most 5000 unique segments")
    uf = Union(len(pieces))
    tol = 1e-4
    for i, a in enumerate(pieces):
        for j, b in enumerate(pieces[:i]):
            if a["service"] == b["service"] and (
                any(_piece_distance(p, b) <= tol for p in (a["a"], a["b"]))
                or any(_piece_distance(p, a) <= tol for p in (b["a"], b["b"]))
            ):
                uf.join(i, j)
    shapes, fittings = [], []
    for e in pid.modelspace().query("INSERT CIRCLE LWPOLYLINE"):
        if service(e.dxf.layer) is not None:
            continue
        ext = bbox.extents([e], fast=True)
        if not ext.has_data:
            continue
        box = [ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y]
        tags = [tag for tag, at in positions.items() if _inside(at, box)]
        if tags:
            shapes.append((box, tags))
        elif e.dxftype() == "INSERT":
            fittings.append(box)
    for box in fittings:
        hits = [i for i, e in enumerate(pieces) if any(_inside(p, box, tol) for p in (e["a"], e["b"]))]
        if 2 <= len(hits) <= 4:
            for i, j in itertools.combinations(hits, 2):
                if pieces[i]["service"] == pieces[j]["service"]:
                    uf.join(i, j)
    labels, words = [], []
    for t in texts(pid):
        match = re.fullmatch(r"(Ø|DN|SMS)\s*(\d+(?:\.\d+)?)|(\d+\s*[xX]\s*\d+)", t["text"], re.I)
        if match:
            size = re.sub(r"\s+", "", t["text"]).replace("X", "x")
            labels.append((t, size))
        elif re.search(r"возврат|return|retour|подача|supply", t["text"], re.I):
            words.append(t)
    direct = defaultdict(set)
    for t, size in labels:
        if pieces:
            distance, i = min((_piece_distance(t["at"], e), i) for i, e in enumerate(pieces))
            if distance <= max(t["height"] * 3, 1):
                direct[i].add(size)
    word_service = {}
    for t in words:
        if pieces:
            distance, i = min((_piece_distance(t["at"], e), i) for i, e in enumerate(pieces))
            if distance <= max(t["height"] * 3, 1):
                word_service[uf.find(i)] = (
                    "cip_return" if re.search(r"возврат|return|retour", t["text"], re.I) else "cip_supply"
                )
    components = defaultdict(list)
    for i in range(len(pieces)):
        components[uf.find(i)].append(i)
    runs = []
    for root, indices in components.items():
        cls = word_service.get(root, pieces[indices[0]]["service"])
        if services is not None and cls not in services:
            continue
        tags = sorted(
            {
                tag
                for i in indices
                for box, ts in shapes
                if any(_inside(p, box, tol) for p in (pieces[i]["a"], pieces[i]["b"]))
                for tag in ts
            }
        )
        routed = len(tags) >= 2 and all(tag in layout_positions for tag in tags)
        length = rmst([layout_positions[t] for t in tags]) if routed else None
        sizes = sorted(set().union(*(direct[i] for i in indices)))
        status = "C" if not routed else "A" if all(direct[i] for i in indices) else "B"
        runs.append(
            {
                "service": cls,
                "tags": tags,
                "diameters": sizes,
                "status": status,
                "layout_m": None if length is None else length / 1000,
                "handles": sorted({pieces[i]["handle"] for i in indices}),
                "direct_size_segments": sum(bool(direct[i]) for i in indices),
                "segments": len(indices),
            }
        )
    panels = {}
    for e in layout.modelspace().query("MULTILEADER"):
        mtext = e.context.mtext
        if mtext is None:
            continue
        match = re.search(r"wiring\s+to\s+(CP[ -]?\d+)", mtext.default_content, re.I)
        if not match:
            continue
        for leader in e.context.leaders:
            for line in leader.lines:
                if line.vertices:
                    tip = tuple(line.vertices[0])[:2]
                    for tag, at in layout_positions.items():
                        if math.dist(tip, at) <= tol:
                            panels[tag] = tag_name(match[1])
    cables, warnings = [], []
    for t in texts(pid):
        if service(t["layer"]) != "electrical" or not re.search(
            r"кВт|kw|ф\.|phase|нагрев|heater", t["text"], re.I
        ):
            continue
        distance, tag = min(((math.dist(t["at"], p), tag) for tag, p in positions.items()),
                            default=(math.inf, None))
        if distance > t["height"] * 10:
            tag = None
            warnings.append(f"ELECTRICAL_TAG_MISSING: callout {t['handle']} has no nearby equipment tag; cable length unknown")
        match = re.search(r"(?:P\s*=\s*)?(\d+(?:[.,]\d+)?)\s*(?:кВт|kw)", t["text"], re.I)
        power = float(match[1].replace(",", ".")) if match else None
        panel = panels.get(tag)
        length = (
            rmst([layout_positions[tag], layout_positions[panel]]) / 1000
            if tag in layout_positions and panel in layout_positions
            else None
        )
        cables.append(
            {
                "tag": tag,
                "panel": panel,
                "kw": power,
                "length_m": length,
                "cable_m": math.ceil(length * (1 + allowance)) if length is not None else None,
                "source_handle": t["handle"],
            }
        )
    return {
        "scale": scale,
        "pipe": {"runs": runs, "length_source": "layout_rmst"},
        "cable": {"rows": cables, "allowance": allowance},
        "layout_selection": ls,
        "warnings": pd["warnings"] + ld["warnings"] + warnings,
        "method": "Preliminary Manhattan routing; geometry in inferred millimetres, no elevations or installed-route claim",
    }
