"""Feature recognition from *actual file geometry*.

This module never looks at the spec or at the operations that produced a
drawing: it re-reads entities and derives closed contours, holes and
dimension measurements on its own.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ezdxf import path as ezpath
from ezdxf.document import Drawing

from .. import geom as G
from ..model import get_tag

CONNECT_TOL = 1e-6
FLATTEN = 0.01


@dataclass
class Contour:
    entities: list[str]
    polygon: list[G.Vec]
    layer: str
    source: str  # "polyline" | "loop"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def size(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return x1 - x0, y1 - y0

    @property
    def area(self) -> float:
        return abs(G.polygon_area(self.polygon))


@dataclass
class Hole:
    id: str
    center: G.Vec
    diameter: float
    layer: str
    tag: str | None = None


@dataclass
class Features:
    contours: list[Contour] = field(default_factory=list)
    open_chains: list[list[str]] = field(default_factory=list)
    circles: list[Hole] = field(default_factory=list)
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    points: list[tuple[G.Vec, str]] = field(default_factory=list)  # snap points (vertex/center) + entity
    curves: list[tuple[G.Vec, float, str]] = field(default_factory=list)  # circles/arcs: center, radius, entity
    texts: list[tuple[str, str]] = field(default_factory=list)


def _flatten(e) -> list[G.Vec]:
    p = ezpath.make_path(e)
    return [(v.x, v.y) for v in p.flattening(FLATTEN)]


def measure_dimension(e) -> tuple[str, float | None]:
    """Independent re-measurement from DIMENSION definition points."""
    x = e.dxf
    kind = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular3p",
            6: "ordinate"}.get(x.dimtype & 0x0F, "unknown")
    try:
        if kind == "linear":
            a = math.radians(x.get("angle", 0.0))
            d = x.defpoint3 - x.defpoint2
            return kind, abs(d.x * math.cos(a) + d.y * math.sin(a))
        if kind == "aligned":
            return kind, (x.defpoint3 - x.defpoint2).magnitude
        if kind in ("diameter", "radius"):
            return kind, (x.defpoint4 - x.defpoint).magnitude
        if kind == "angular3p":
            c = x.defpoint4
            a1 = G.angle_of((x.defpoint2.x - c.x, x.defpoint2.y - c.y))
            a2 = G.angle_of((x.defpoint3.x - c.x, x.defpoint3.y - c.y))
            return kind, G.ccw_span(a1, a2)
        if kind == "angular":
            v1 = x.defpoint3 - x.defpoint2
            v2 = x.defpoint - x.defpoint4
            return kind, math.degrees(math.acos(max(-1, min(1, v1.normalize().dot(v2.normalize())))))
    except Exception:
        return kind, None
    return kind, None


def dimension_anchor_points(e) -> list[G.Vec]:
    """Points of the measured geometry a dimension refers to."""
    x = e.dxf
    kind, _ = measure_dimension(e)
    if kind in ("linear", "aligned"):
        return [(x.defpoint2.x, x.defpoint2.y), (x.defpoint3.x, x.defpoint3.y)]
    if kind in ("diameter",):
        return [(x.defpoint.x, x.defpoint.y), (x.defpoint4.x, x.defpoint4.y)]
    if kind == "radius":
        return [(x.defpoint.x, x.defpoint.y)]
    if kind == "angular3p":
        return [(x.defpoint4.x, x.defpoint4.y)]
    return []


def extract(doc: Drawing) -> Features:
    f = Features()
    msp = doc.modelspace()
    loose: list[tuple[str, str, G.Vec, G.Vec, Any]] = []  # handle, layer, start, end, entity
    for e in msp:
        t = e.dxftype()
        h = e.dxf.handle
        if t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            for p in pts:
                f.points.append((p, h))
            closed = e.closed or (len(pts) > 2 and G.dist(pts[0], pts[-1]) < CONNECT_TOL)
            if closed and len(pts) >= 3:
                f.contours.append(Contour([h], _flatten(e), e.dxf.layer, "polyline"))
            elif len(pts) >= 2:
                loose.append((h, e.dxf.layer, pts[0], pts[-1], e))
        elif t == "LINE":
            s, q = (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
            f.points += [(s, h), (q, h), (((s[0] + q[0]) / 2, (s[1] + q[1]) / 2), h)]
            loose.append((h, e.dxf.layer, s, q, e))
        elif t == "ARC":
            c = (e.dxf.center.x, e.dxf.center.y)
            s = G.polar(c, e.dxf.radius, e.dxf.start_angle)
            q = G.polar(c, e.dxf.radius, e.dxf.end_angle)
            f.points += [(c, h), (s, h), (q, h)]
            f.curves.append((c, e.dxf.radius, h))
            loose.append((h, e.dxf.layer, s, q, e))
        elif t == "CIRCLE":
            c = (e.dxf.center.x, e.dxf.center.y)
            r = e.dxf.radius
            f.circles.append(Hole(h, c, 2 * r, e.dxf.layer, get_tag(e)))
            f.curves.append((c, r, h))
            f.points.append((c, h))
            for a in (0, 90, 180, 270):
                f.points.append((G.polar(c, r, a), h))
        elif t == "DIMENSION":
            kind, m = measure_dimension(e)
            f.dimensions.append({"id": h, "kind": kind, "measurement": m, "layer": e.dxf.layer,
                                 "text": e.dxf.get("text", ""), "anchors": dimension_anchor_points(e),
                                 "stored": e.dxf.get("actual_measurement"), "tag": get_tag(e)})
        elif t in ("TEXT", "MTEXT"):
            f.texts.append((e.dxf.text if t == "TEXT" else e.plain_text(), h))
        elif t == "INSERT":
            for a in e.attribs:
                f.texts.append((a.dxf.text, h))
    _chain_loops(f, loose)
    return f


def _chain_loops(f: Features, loose) -> None:
    """Join LINE/ARC/open-polyline pieces with coincident end points into closed loops."""
    used = [False] * len(loose)

    def key(p):
        return (round(p[0] / CONNECT_TOL) * CONNECT_TOL, round(p[1] / CONNECT_TOL) * CONNECT_TOL)

    for i in range(len(loose)):
        if used[i]:
            continue
        used[i] = True
        chain = [i]
        start, cur = loose[i][2], loose[i][3]
        closed = False
        progressed = True
        while progressed:
            progressed = False
            if G.dist(start, cur) < CONNECT_TOL * 10 and len(chain) > 1:
                closed = True
                break
            for j in range(len(loose)):
                if used[j] or loose[j][1] != loose[i][1]:
                    continue
                if G.dist(loose[j][2], cur) < CONNECT_TOL * 10:
                    cur = loose[j][3]
                elif G.dist(loose[j][3], cur) < CONNECT_TOL * 10:
                    cur = loose[j][2]
                else:
                    continue
                used[j] = True
                chain.append(j)
                progressed = True
                break
        if not closed and len(chain) > 1 and G.dist(start, cur) < CONNECT_TOL * 10:
            closed = True
        if closed:
            poly: list[G.Vec] = []
            last = None
            for j in chain:
                pts = _flatten(loose[j][4])
                if last is not None and G.dist(pts[0], last) > CONNECT_TOL * 10:
                    pts.reverse()
                if last is None and len(chain) > 1:
                    nxt = loose[chain[1]]
                    if min(G.dist(pts[0], nxt[2]), G.dist(pts[0], nxt[3])) < CONNECT_TOL * 10:
                        pts.reverse()
                poly.extend(pts if not poly else pts[1:])
                last = pts[-1]
            f.contours.append(Contour([loose[j][0] for j in chain], poly, loose[i][1], "loop"))
        else:
            f.open_chains.append([loose[j][0] for j in chain])


def pick_outline(f: Features, layer: str | None = None) -> Contour | None:
    cands = [c for c in f.contours if layer is None or c.layer == layer]
    if not cands:
        return None
    return max(cands, key=lambda c: c.area)


def holes_in(f: Features, outline: Contour, layer: str | None = None) -> list[Hole]:
    return [h for h in f.circles if (layer is None or h.layer == layer) and G.point_in_polygon(h.center, outline.polygon)]
