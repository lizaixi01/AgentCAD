"""Drafting-practice checks: what a checker marks on a drawing whose geometry and values are right.

Seen in the 2026-11-02 rerun (examples/trials): agents rendered a preview, read every value correctly and still
delivered dimensions drawn over one another, and a stepped shaft without the edges of its shoulders. All warnings:
the drawing is correct, only harder to read or incomplete as a view."""
from __future__ import annotations

import re
from typing import Any

from ezdxf.document import Drawing

from .. import geom as G
from .features import Features, dimension_direction, measure_dimension

Seg = tuple[G.Vec, G.Vec]
MAX_DIMENSIONS = 2000  # pairwise checks; a sheet with more is a survey drawing, not a part
CHAR_WIDTH = 0.6  # of the text height: an average glyph, narrower than most fonts so overlaps are real ones
CENTER_RE = re.compile(r"CENT|AXIS|中心|轴线", re.I)
DIAMETER_RE = re.compile(r"%%c|Ø|⌀", re.I)


def drafting_issues(doc: Drawing, feats: Features, layout: str | None = None) -> list[dict[str, Any]]:
    from ..model import layout_spaces
    from .checks import issue
    space = layout_spaces(doc, layout)[0]
    dims = [d for d in (_dimension_shape(e) for e in space.query("DIMENSION")) if d]
    out = _dimension_overlaps(dims, issue) if len(dims) <= MAX_DIMENSIONS else []
    return out + _turned_edges(doc, space, feats, issue)


# --- dimensions drawn over one another -------------------------------------------------------------------------

def _dimension_shape(e) -> dict[str, Any] | None:
    """The dimension line (the parts of it the saved graphics draw) and the text boxes of one dimension."""
    kind, _ = measure_dimension(e)
    x = e.dxf
    try:
        if kind in ("linear", "aligned"):
            direction, on = dimension_direction(e), (x.defpoint.x, x.defpoint.y)
            ends = [_project(on, direction, (p.x, p.y)) for p in (x.defpoint2, x.defpoint3)] if direction else []
            center = None
        elif kind in ("diameter", "radius"):
            p, q = (x.defpoint.x, x.defpoint.y), (x.defpoint4.x, x.defpoint4.y)
            direction, on, ends = G.unit(G.sub(q, p)), p, [p, q]
            center = p if kind == "radius" else G.mul(G.add(p, q), 0.5)
        else:
            return None
    except Exception:
        return None
    if not direction or not ends:
        return None
    block = e.get_geometry_block()
    texts, lines = [], []
    for g in block or []:
        t = g.dxftype()
        if t == "LINE":
            lines.append(((g.dxf.start.x, g.dxf.start.y), (g.dxf.end.x, g.dxf.end.y)))
        elif t in ("MTEXT", "TEXT"):
            if box := _text_box(g):
                texts.append(box)
    h = max((b[1] for b in texts), default=0.0) or _dim_text_height(e)
    tol = max(h * 0.1, 1e-6)
    drawn = [s for s in lines if all(abs(G.cross(G.sub(p, on), direction)) <= tol for p in s)]
    return {"id": x.handle, "kind": kind, "direction": direction, "lines": drawn or [tuple(ends)],
            "texts": [b[0] for b in texts], "height": h, "tol": tol, "center": center}


def _project(on: G.Vec, direction: G.Vec, p: G.Vec) -> G.Vec:
    return G.add(on, G.mul(direction, G.dot(G.sub(p, on), direction)))


def _dim_text_height(e) -> float:
    try:
        ov = e.override()
        return ov.get("dimtxt", 0.18) * (ov.get("dimscale", 1.0) or 1.0)
    except Exception:
        return 0.0


def _text_box(g) -> tuple[list[G.Vec], float] | None:
    """Corners of a dimension text, from its insertion point, height, rotation and attachment."""
    from ezdxf.tools.text import plain_mtext
    try:
        if g.dxftype() == "MTEXT":
            h, raw, attach = g.dxf.char_height, g.text, g.dxf.get("attachment_point", 1)
            rot = g.get_rotation()
            ins = g.dxf.insert
        else:
            h, raw, attach, rot = g.dxf.height, g.dxf.text, 7, g.dxf.get("rotation", 0.0)
            ins = g.dxf.insert
        txt = plain_mtext(raw.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%p", "±"))
    except Exception:
        return None
    lines = [s for s in txt.split("\n") if s.strip()]
    if not lines or not h:
        return None
    w, hh = max(len(s) for s in lines) * CHAR_WIDTH * h, len(lines) * h
    col, row = (attach - 1) % 3, (attach - 1) // 3  # 1 top-left ... 9 bottom-right
    x0 = -w * col / 2
    y1 = hh * row / 2
    u, v = G.polar((0.0, 0.0), 1.0, rot), G.polar((0.0, 0.0), 1.0, rot + 90)
    o = (ins.x, ins.y)
    corners = [G.add(o, G.add(G.mul(u, a), G.mul(v, b))) for a, b in
               ((x0, y1 - hh), (x0 + w, y1 - hh), (x0 + w, y1), (x0, y1))]
    return corners, h


def _boxes_meet(a: list[G.Vec], b: list[G.Vec]) -> bool:
    """Separating-axis test for two convex quadrilaterals."""
    for poly in (a, b):
        for i in range(4):
            n = G.sub(poly[(i + 1) % 4], poly[i])
            n = (-n[1], n[0])
            pa = [G.dot(p, n) for p in a]
            pb = [G.dot(p, n) for p in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def _shrink(box: list[G.Vec], f: float = 0.85) -> list[G.Vec]:
    c = G.mul(G.add(box[0], box[2]), 0.5)
    return [G.add(c, G.mul(G.sub(p, c), f)) for p in box]


def _segment_meets_box(s: Seg, box: list[G.Vec]) -> bool:
    if G.point_in_polygon(s[0], box) or G.point_in_polygon(s[1], box):
        return True
    return any(_cross_point(s, (box[i], box[(i + 1) % 4])) for i in range(4))


def _cross_point(a: Seg, b: Seg, margin: float = 0.0) -> G.Vec | None:
    """Where two segments cross, both strictly inside (by ``margin`` of each length)."""
    r = G.line_line(G.Seg(*a), G.Seg(*b))
    if r is None:
        return None
    t, u = r
    la, lb = G.dist(*a), G.dist(*b)
    ma, mb = (margin / la if la else 1), (margin / lb if lb else 1)
    if ma < t < 1 - ma and mb < u < 1 - mb:
        return G.Seg(*a).at(t)
    return None


def _collinear_overlap(a: Seg, b: Seg, tol: float) -> float:
    """Length along which two segments lie on top of each other."""
    da = G.sub(a[1], a[0])
    la = G.norm(da)
    if not la or G.dist(*b) == 0:
        return 0.0
    d = G.mul(da, 1 / la)
    if abs(G.cross(d, G.unit(G.sub(b[1], b[0])))) > 0.01 or \
            any(abs(G.cross(G.sub(p, a[0]), d)) > tol for p in b):
        return 0.0
    t = sorted(G.dot(G.sub(p, a[0]), d) for p in b)
    return max(0.0, min(la, t[1]) - max(0.0, t[0]))


def _bbox(d) -> tuple[float, float, float, float]:
    pts = [p for s in d["lines"] for p in s] + [p for b in d["texts"] for p in b]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _dimension_overlaps(dims: list[dict], issue) -> list[dict[str, Any]]:
    out = []
    boxes = sorted(((_bbox(d), d) for d in dims), key=lambda bd: bd[0][0])
    overlaps: list[tuple[str, str, str]] = []
    crossings: dict[tuple, dict] = {}
    for i, (ba, a) in enumerate(boxes):
        for bb, b in boxes[i + 1:]:
            if bb[0] > ba[2]:
                break
            if bb[1] > ba[3] or bb[3] < ba[1]:
                continue
            tol, h = max(a["tol"], b["tol"]), max(a["height"], b["height"], 1e-6)
            why = None
            if any(_collinear_overlap(s, t, tol) > h for s in a["lines"] for t in b["lines"]):
                why = "their dimension lines lie on top of each other"
            elif any(_boxes_meet(_shrink(p), _shrink(q)) for p in a["texts"] for q in b["texts"]):
                why = "their texts overlap"
            elif any(_segment_meets_box(s, _shrink(q)) for s in a["lines"] for q in b["texts"]) or \
                    any(_segment_meets_box(s, _shrink(q)) for s in b["lines"] for q in a["texts"]):
                why = "a dimension line runs through the other's text"
            if why:
                overlaps.append((a["id"], b["id"], why))
                continue
            for s in a["lines"]:
                for t in b["lines"]:
                    p = _cross_point(s, t, h * 0.5)
                    if p is None:
                        continue
                    key = (round(p[0] / h), round(p[1] / h))
                    c = crossings.setdefault(key, {"at": p, "ids": set(), "centers": True})
                    c["ids"].update((a["id"], b["id"]))
                    c["centers"] &= all(d["center"] is not None and G.dist(d["center"], p) <= h for d in (a, b))
    # One warning per group of dimensions piled on one another: 50 lengths of 1 mm steps are one problem, not 144
    group: dict[str, str] = {}

    def root(h: str) -> str:
        while group.setdefault(h, h) != h:
            h = group[h]
        return h

    for a, b, _ in overlaps:
        group[root(a)] = root(b)
    clusters: dict[str, list] = {}
    for a, b, why in overlaps:
        clusters.setdefault(root(a), []).append((a, b, why))
    for pairs in clusters.values():
        ids = sorted({h for a, b, _ in pairs for h in (a, b)})
        whys = ", ".join(dict.fromkeys(why for _, _, why in pairs))
        what = f"Dimensions {ids[0]} and {ids[1]} are" if len(ids) == 2 else \
            f"{len(ids)} dimensions ({len(pairs)} pairs) are"
        out.append(issue("DIMENSION_OVERLAP", "warning", f"{what} drawn over one another: {whys}", ids[:50],
                         hint="Move one: another angle for a diameter or radius dimension, another offset "
                              "for a linear one (modify, or delete and add it again); steps too short to "
                              "dimension one by one take a single dimension or a table"))
    for c in crossings.values():
        # Two diameters of concentric circles have to meet at the common center; a third there is clutter.
        if c["centers"] and len(c["ids"]) <= 2:
            continue
        ids = sorted(c["ids"])
        at = [round(v, 3) for v in c["at"]]
        out.append(issue("DIMENSION_LINES_CROSS", "warning",
                         f"The dimension lines of {len(ids)} dimensions cross at {at}", ids,
                         hint="Dimension lines should not cross. Concentric circles: keep at most two diameter "
                              "dimensions through the center and add the others with add_diameter_dim(outside=true) "
                              "at angles clear of the holes; linear dimensions: put the shorter ones nearer the "
                              "part"))
    return out


# --- turned parts: the edge of every shoulder and chamfer -------------------------------------------------------

def _axis_lines(doc: Drawing, space) -> list[Seg]:
    out = []
    for e in space.query("LINE"):
        lt = e.dxf.get("linetype", "BYLAYER")
        if lt.upper() == "BYLAYER" and e.dxf.layer in doc.layers:
            lt = doc.layers.get(e.dxf.layer).dxf.get("linetype", "")
        if CENTER_RE.search(lt) or CENTER_RE.search(e.dxf.layer):
            s, q = (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
            if G.dist(s, q) > 0:
                out.append((s, q))
    return out


def _turned_edges(doc: Drawing, space, feats: Features, issue) -> list[dict[str, Any]]:
    """A turned part (shaft, pin, bushing) in a view along its axis shows each diameter change as a line across
    the part: the circular edge seen edge-on. Checked for outlines symmetric about a center line that carry a
    diameter dimension across that line, so a flat stepped plate (no such line) is left alone."""
    out = []
    axes = _axis_lines(doc, space)
    if not axes or not feats.contours:
        return out
    diam = [((e.dxf.defpoint2.x, e.dxf.defpoint2.y), (e.dxf.defpoint3.x, e.dxf.defpoint3.y))
            for e in space.query("DIMENSION") if measure_dimension(e)[0] in ("linear", "aligned") and _shows_diameter(e)]
    if not diam:
        return out
    for o, q in axes:
        u = G.unit(G.sub(q, o))
        for c in feats.contours:
            local = [(G.dot(G.sub(p, o), u), G.cross(u, G.sub(p, o))) for p in c.polygon]
            if len(local) < 4:
                continue
            us, vs = [p[0] for p in local], [p[1] for p in local]
            span, half = max(us) - min(us), max(abs(min(vs)), abs(max(vs)))
            tol = max(span, half) * 1e-4
            if min(vs) > -tol or max(vs) < tol or abs(max(vs) + min(vs)) > tol * 10:
                continue
            if not _mirrored(local, tol * 10):
                continue
            if not any(_across(a, b, o, u, min(us), max(us), tol * 10) for a, b in diam):
                continue
            missing = []
            n = len(local)
            for i, p in enumerate(local):
                prev, nxt = local[i - 1], local[(i + 1) % n]
                if p[1] < tol or G.dist(prev, p) < tol or G.dist(p, nxt) < tol:
                    continue  # one side is enough: the outline is symmetric
                turn = abs(G.cross(G.unit(G.sub(p, prev)), G.unit(G.sub(nxt, p))))
                back = G.dot(G.unit(G.sub(p, prev)), G.unit(G.sub(nxt, p)))
                if turn < 0.5 and back > 0:  # under 30 degrees: a straight run or a flattened arc
                    continue
                if not _covered(feats.segments, o, u, p[0], p[1], tol * 10):
                    missing.append(p)
            seen: list[G.Vec] = []
            for p in sorted(missing):
                if any(abs(p[0] - s[0]) <= tol * 10 for s in seen):
                    continue
                seen.append(p)
            if seen:
                at = [[[round(v, 6) for v in G.add(o, G.add(G.mul(u, p[0]), G.mul((-u[1], u[0]), s)))]
                       for s in (-p[1], p[1])] for p in seen]
                out.append(issue("TURNED_EDGE_MISSING", "warning",
                                 f"Turned outline {'/'.join(c.entities[:3])} lacks the line across it at "
                                 f"{len(seen)} diameter change(s): shoulders and chamfers are circular edges, seen "
                                 "edge-on as a line across the part", list(c.entities[:50]), lines=at,
                                 hint="add_line from each 'lines' start to end, on the outline's layer"))
    return out


def _shows_diameter(e) -> bool:
    txt = e.dxf.get("text", "") or ""
    if DIAMETER_RE.search(txt):
        return True
    try:
        return bool(DIAMETER_RE.search(e.override().get("dimpost", "") or ""))
    except Exception:
        return False


def _mirrored(local: list[G.Vec], tol: float) -> bool:
    pts = sorted(local)
    return all(any(abs(p[0] - q[0]) <= tol and abs(p[1] + q[1]) <= tol for q in pts) for p in pts)


def _across(a: G.Vec, b: G.Vec, o: G.Vec, u: G.Vec, u0: float, u1: float, tol: float) -> bool:
    la = (G.dot(G.sub(a, o), u), G.cross(u, G.sub(a, o)))
    lb = (G.dot(G.sub(b, o), u), G.cross(u, G.sub(b, o)))
    return abs(la[1] + lb[1]) <= tol and abs(la[1]) > tol and u0 - tol <= la[0] <= u1 + tol and \
        u0 - tol <= lb[0] <= u1 + tol


def _covered(segments: list[Seg], o: G.Vec, u: G.Vec, at: float, r: float, tol: float) -> bool:
    """Whether straight edges at axial position ``at`` cover the part from -r to r (90 %)."""
    spans = []
    for s, q in segments:
        a = (G.dot(G.sub(s, o), u), G.cross(u, G.sub(s, o)))
        b = (G.dot(G.sub(q, o), u), G.cross(u, G.sub(q, o)))
        if abs(a[0] - at) <= tol and abs(b[0] - at) <= tol:
            lo, hi = sorted((a[1], b[1]))
            spans.append((max(lo, -r), min(hi, r)))
    covered, reach = 0.0, -r
    for lo, hi in sorted(spans):
        if hi > reach:
            covered += hi - max(lo, reach)
            reach = hi
    return covered >= 1.8 * r
