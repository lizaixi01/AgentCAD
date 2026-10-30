"""Small, dependency-free 2D geometry kernel used by edit operations and the
validator (intersections, angles, offsets). All angles are degrees, CCW."""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-9

Vec = tuple[float, float]


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec, b: Vec) -> float:
    return a[0] * b[1] - a[1] * b[0]


def norm(a: Vec) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n < EPS:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n)


def angle_of(v: Vec) -> float:
    return math.degrees(math.atan2(v[1], v[0])) % 360.0


def polar(c: Vec, r: float, deg: float) -> Vec:
    a = math.radians(deg)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def ccw_span(start: float, end: float) -> float:
    """CCW sweep from start to end in (0, 360]."""
    s = (end - start) % 360.0
    return 360.0 if s < EPS else s


def angle_in_arc(a: float, start: float, end: float, tol: float = 1e-7) -> bool:
    return (a - start) % 360.0 <= ccw_span(start, end) + tol


@dataclass
class Seg:
    p: Vec
    q: Vec

    def at(self, t: float) -> Vec:
        return (self.p[0] + (self.q[0] - self.p[0]) * t, self.p[1] + (self.q[1] - self.p[1]) * t)

    def param(self, x: Vec) -> float:
        d = sub(self.q, self.p)
        return dot(sub(x, self.p), d) / dot(d, d)


@dataclass
class Circ:
    c: Vec
    r: float
    start: float | None = None  # None = full circle
    end: float | None = None

    def contains_angle(self, a: float) -> bool:
        return self.start is None or angle_in_arc(a, self.start, self.end)


def line_line(a: Seg, b: Seg) -> tuple[float, float] | None:
    """Intersection of infinite lines; returns (t on a, u on b) or None if parallel."""
    r = sub(a.q, a.p)
    s = sub(b.q, b.p)
    den = cross(r, s)
    if abs(den) < EPS * max(1.0, norm(r) * norm(s)):
        return None
    qp = sub(b.p, a.p)
    return cross(qp, s) / den, cross(qp, r) / den


def angular_sector(a: Seg, b: Seg, arc: Vec) -> tuple[Vec, float, float]:
    """Centre and CCW sector selected by a two-line dimension's arc point."""
    intersection = line_line(a, b)
    if intersection is None:
        raise ValueError("Parallel angular dimension legs")
    center = a.at(intersection[0])
    if norm(sub(arc, center)) < EPS:
        raise ValueError("Angular dimension arc has zero radius")
    directions = [angle_of(sub(line.q, line.p)) for line in (a, b)]
    rays = sorted([*directions, *((v + 180) % 360 for v in directions)])
    selected = angle_of(sub(arc, center))
    for start, end in zip(rays, rays[1:] + rays[:1]):
        if (selected - start) % 360 < (end - start) % 360:
            return center, start, end
    raise ValueError("Angular dimension has no measurable sector")


def line_circle(a: Seg, c: Circ) -> list[float]:
    """Params t on infinite line ``a`` where it meets the full circle."""
    d = sub(a.q, a.p)
    f = sub(a.p, c.c)
    A = dot(d, d)
    B = 2 * dot(f, d)
    C = dot(f, f) - c.r * c.r
    disc = B * B - 4 * A * C
    if disc < -EPS * max(1.0, B * B):
        return []
    disc = max(disc, 0.0)
    sq = math.sqrt(disc)
    t1 = (-B - sq) / (2 * A)
    t2 = (-B + sq) / (2 * A)
    return [t1] if abs(t1 - t2) < 1e-12 else [t1, t2]


def circle_circle(a: Circ, b: Circ) -> list[Vec]:
    d = dist(a.c, b.c)
    if d < EPS or d > a.r + b.r + EPS or d < abs(a.r - b.r) - EPS:
        return []
    x = (d * d + a.r * a.r - b.r * b.r) / (2 * d)
    h2 = a.r * a.r - x * x
    h = math.sqrt(max(h2, 0.0))
    u = unit(sub(b.c, a.c))
    base = add(a.c, mul(u, x))
    if h < 1e-12:
        return [base]
    n = (-u[1], u[0])
    return [add(base, mul(n, h)), add(base, mul(n, -h))]


def intersections(a: Seg | Circ, b: Seg | Circ, *, a_infinite: bool = False) -> list[Vec]:
    """Intersection points; ``b`` is always treated as bounded; ``a`` optionally infinite."""
    pts: list[Vec] = []
    if isinstance(a, Seg) and isinstance(b, Seg):
        res = line_line(a, b)
        if res:
            t, u = res
            if (a_infinite or -EPS <= t <= 1 + EPS) and -EPS <= u <= 1 + EPS:
                pts.append(a.at(t))
    elif isinstance(a, Seg) and isinstance(b, Circ):
        for t in line_circle(a, b):
            p = a.at(t)
            if (a_infinite or -EPS <= t <= 1 + EPS) and b.contains_angle(angle_of(sub(p, b.c))):
                pts.append(p)
    elif isinstance(a, Circ) and isinstance(b, Seg):
        for t in line_circle(b, a):
            p = b.at(t)
            if -EPS <= t <= 1 + EPS and (a_infinite or a.contains_angle(angle_of(sub(p, a.c)))):
                pts.append(p)
    else:
        for p in circle_circle(a, b):  # type: ignore[arg-type]
            if (a_infinite or a.contains_angle(angle_of(sub(p, a.c)))) and b.contains_angle(angle_of(sub(p, b.c))):
                pts.append(p)
    return pts


def dist_to_segment(p: Vec, a: Vec, b: Vec) -> float:
    ab = sub(b, a)
    L2 = dot(ab, ab)
    if L2 == 0:
        return dist(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / L2))
    return dist(p, add(a, mul(ab, t)))


def polygon_area(pts: list[Vec]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def point_in_polygon(p: Vec, pts: list[Vec]) -> bool:
    x, y = p
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def offset_polyline(pts: list[Vec], d: float, closed: bool) -> list[Vec]:
    """Offset a straight-segment polyline by ``d`` to the left of its direction
    (mitred joins)."""
    n = len(pts)
    segs = []
    m = n if closed else n - 1
    for i in range(m):
        p, q = pts[i], pts[(i + 1) % n]
        u = unit(sub(q, p))
        nrm = (-u[1], u[0])
        segs.append(Seg(add(p, mul(nrm, d)), add(q, mul(nrm, d))))
    out: list[Vec] = []
    for i in range(n):
        if not closed and i == 0:
            out.append(segs[0].p)
            continue
        if not closed and i == n - 1:
            out.append(segs[-1].q)
            continue
        s_prev = segs[(i - 1) % len(segs)]
        s_next = segs[i % len(segs)]
        res = line_line(s_prev, s_next)
        out.append(s_next.p if res is None else s_prev.at(res[0]))
    return out
