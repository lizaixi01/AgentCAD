"""Geometry editing operations (AutoCAD MOVE/COPY/ROTATE/MIRROR/SCALE/STRETCH/
OFFSET/TRIM/EXTEND/FILLET/CHAMFER/ARRAY/ERASE equivalents)."""
from __future__ import annotations

import math
from typing import Any

from ezdxf.math import Matrix44, Vec3

from .. import geom as G
from ..errors import geometry_error, input_error, policy_error
from ..model import get_tag, select, set_tag
from .registry import Ctx, Param, op

P = Param
TARGET = P("selector", True, description="Entities to operate on")


def _vec(v) -> G.Vec:
    return (float(v[0]), float(v[1]))


# --- transform helpers ---------------------------------------------------------

def rerender_dimension(ctx: Ctx, dim) -> None:
    old = dim.dxf.get("geometry")
    dim.override().render()
    from .annotate import store_measurement
    store_measurement(dim)
    new = dim.dxf.get("geometry")
    if old and old != new and old in ctx.doc.blocks:
        try:
            ctx.doc.blocks.delete_block(old, safe=False)
        except Exception:
            pass


def normalize_extrusion(e) -> None:
    """Map entities with OCS extrusion (0,0,-1) (produced by reflections) back to
    the WCS-aligned (0,0,1) representation so that coordinates stay readable."""
    if not e.dxf.hasattr("extrusion"):
        return
    ex = Vec3(e.dxf.extrusion)
    if not ex.isclose(Vec3(0, 0, -1)):
        return
    t = e.dxftype()
    if t in ("CIRCLE", "ARC"):
        c = e.dxf.center
        e.dxf.center = (-c.x, c.y, -c.z)
        if t == "ARC":
            s, en = e.dxf.start_angle, e.dxf.end_angle
            e.dxf.start_angle = (180.0 - en) % 360.0
            e.dxf.end_angle = (180.0 - s) % 360.0
        e.dxf.extrusion = (0, 0, 1)
    elif t == "LWPOLYLINE":
        pts = [(-x, y, s, en, -b) for x, y, s, en, b in e.get_points("xyseb")]
        closed = e.closed
        e.set_points(pts, format="xyseb")
        e.closed = closed
        e.dxf.elevation = -e.dxf.get("elevation", 0.0)
        e.dxf.extrusion = (0, 0, 1)


def transform(ctx: Ctx, e, m: Matrix44, *, reflect: bool = False) -> None:
    t = e.dxftype()
    if reflect and t in ("TEXT", "MTEXT", "INSERT"):
        # MIRRTEXT=0 semantics: reflect the insertion point only, keep text readable
        ins = e.dxf.insert
        newp = m.transform(ins)
        e.translate(newp.x - ins.x, newp.y - ins.y, 0)
    else:
        e.transform(m)
        normalize_extrusion(e)
    if t == "DIMENSION":
        rerender_dimension(ctx, e)
    ctx.touched(e)


def _about(center: G.Vec, m: Matrix44) -> Matrix44:
    return Matrix44.chain(Matrix44.translate(-center[0], -center[1], 0), m, Matrix44.translate(center[0], center[1], 0))


def reflection(p1: G.Vec, p2: G.Vec) -> Matrix44:
    a = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    c, s = math.cos(2 * a), math.sin(2 * a)
    refl = Matrix44([c, s, 0, 0, s, -c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])  # row-major, row vectors
    return _about(p1, refl)


def _copy_into_msp(ctx: Ctx, e):
    try:
        c = e.copy()
    except Exception as exc:
        raise input_error("UNSUPPORTED_ENTITY", f"Cannot copy {e.dxftype()} {e.dxf.handle}: {exc}",
                          entities=[e.dxf.handle])
    ctx.msp.add_entity(c)
    tag = get_tag(e)
    if tag is not None:  # copies must not share a tag with the original
        set_tag(ctx.doc, c, None)
    if c.dxftype() == "DIMENSION":
        rerender_dimension(ctx, c)
    ctx.created(c)
    return c


# --- basic transforms ---------------------------------------------------------------

@op("move", "edit", "Translate entities by a displacement (or from 'base' to 'to').",
    {"target": TARGET, "delta": P("point", description="Displacement [dx, dy]"),
     "base": P("point", description="Base point"), "to": P("point", description="Destination of the base point")})
def move(ctx: Ctx, target, delta, base, to):
    d = _delta(delta, base, to)
    ents = select(ctx.doc, target, ctx.refs)
    for e in ents:
        transform(ctx, e, Matrix44.translate(d[0], d[1], 0))
    return {"modified": [e.dxf.handle for e in ents]}


def _delta(delta, base, to) -> G.Vec:
    if delta is not None:
        return delta
    if base is not None and to is not None:
        return G.sub(to, base)
    raise input_error("MISSING_PARAM", "Give 'delta' or both 'base' and 'to'")


@op("copy", "edit", "Copy entities by a displacement; 'count' > 1 repeats the displacement cumulatively.",
    {"target": TARGET, "delta": P("point", description="Displacement [dx, dy]"),
     "base": P("point", description="Base point"), "to": P("point", description="Destination of the base point"),
     "count": P("int", default=1, ge=1, le=10000, description="Number of copies")})
def copy(ctx: Ctx, target, delta, base, to, count):
    d = _delta(delta, base, to)
    ents = select(ctx.doc, target, ctx.refs)
    created = []
    for k in range(1, count + 1):
        for e in ents:
            c = _copy_into_msp(ctx, e)
            transform(ctx, c, Matrix44.translate(d[0] * k, d[1] * k, 0))
            created.append(c.dxf.handle)
    return {"created": created}


@op("rotate", "edit", "Rotate entities about a center point (degrees, CCW).",
    {"target": TARGET, "angle": P("angle", True, description="Rotation angle"),
     "center": P("point", True, description="Rotation center")})
def rotate(ctx: Ctx, target, angle, center):
    ents = select(ctx.doc, target, ctx.refs)
    m = _about(center, Matrix44.z_rotate(math.radians(angle)))
    for e in ents:
        transform(ctx, e, m)
    return {"modified": [e.dxf.handle for e in ents]}


@op("scale", "edit", "Uniformly scale entities about a base point.",
    {"target": TARGET, "factor": P("number", True, gt=0, description="Scale factor"),
     "center": P("point", True, description="Base point")})
def scale(ctx: Ctx, target, factor, center):
    ents = select(ctx.doc, target, ctx.refs)
    m = _about(center, Matrix44.scale(factor, factor, factor))
    for e in ents:
        transform(ctx, e, m)
    return {"modified": [e.dxf.handle for e in ents]}


@op("mirror", "edit", "Mirror entities about the line p1-p2. Text stays readable (MIRRTEXT=0).",
    {"target": TARGET, "p1": P("point", True, description="First point of mirror line"),
     "p2": P("point", True, description="Second point of mirror line"),
     "keep_original": P("bool", default=True, description="Keep the source entities (mirror a copy)")})
def mirror(ctx: Ctx, target, p1, p2, keep_original):
    if G.dist(p1, p2) < 1e-9:
        raise geometry_error("DEGENERATE_GEOMETRY", "Mirror line points coincide")
    ents = select(ctx.doc, target, ctx.refs)
    m = reflection(p1, p2)
    out = []
    for e in ents:
        tgt = _copy_into_msp(ctx, e) if keep_original else e
        transform(ctx, tgt, m, reflect=True)
        out.append(tgt.dxf.handle)
    return {"created": out} if keep_original else {"modified": out}


@op("array_rect", "edit", "Rectangular array: copies arranged in rows and columns (the original is cell [0,0]).",
    {"target": TARGET, "rows": P("int", True, ge=1, le=1000, description="Number of rows"),
     "cols": P("int", True, ge=1, le=1000, description="Number of columns"),
     "row_spacing": P("length", default=0.0, description="Distance between rows (Y)"),
     "col_spacing": P("length", default=0.0, description="Distance between columns (X)")})
def array_rect(ctx: Ctx, target, rows, cols, row_spacing, col_spacing):
    ents = select(ctx.doc, target, ctx.refs)
    _budget(ctx, len(ents) * (rows * cols - 1))
    created = []
    for i in range(rows):
        for j in range(cols):
            if i == 0 and j == 0:
                continue
            for e in ents:
                c = _copy_into_msp(ctx, e)
                transform(ctx, c, Matrix44.translate(j * col_spacing, i * row_spacing, 0))
                created.append(c.dxf.handle)
    return {"created": created}


@op("array_polar", "edit", "Polar array about a center: 'count' items (including the original) over 'total_angle'.",
    {"target": TARGET, "center": P("point", True, description="Array center"),
     "count": P("int", True, ge=2, le=10000, description="Total number of items including the original"),
     "total_angle": P("angle", default=360.0, description="Angle to fill"),
     "rotate_items": P("bool", default=True, description="Rotate the copies (else only translate)")})
def array_polar(ctx: Ctx, target, center, count, total_angle, rotate_items):
    ents = select(ctx.doc, target, ctx.refs)
    _budget(ctx, len(ents) * (count - 1))
    full = abs(abs(total_angle) - 360.0) < 1e-9
    step = total_angle / (count if full else count - 1)
    created = []
    for k in range(1, count):
        a = math.radians(step * k)
        for e in ents:
            c = _copy_into_msp(ctx, e)
            if rotate_items:
                transform(ctx, c, _about(center, Matrix44.z_rotate(a)))
            else:
                ref = _ref_point(e)
                rx = center[0] + (ref[0] - center[0]) * math.cos(a) - (ref[1] - center[1]) * math.sin(a)
                ry = center[1] + (ref[0] - center[0]) * math.sin(a) + (ref[1] - center[1]) * math.cos(a)
                transform(ctx, c, Matrix44.translate(rx - ref[0], ry - ref[1], 0))
            created.append(c.dxf.handle)
    return {"created": created}


def _ref_point(e) -> G.Vec:
    x = e.dxf
    for name in ("center", "insert", "location", "start"):
        if x.hasattr(name):
            return _vec(x.get(name))
    if e.dxftype() == "LWPOLYLINE":
        return _vec(e.get_points("xy")[0])
    return (0.0, 0.0)


def _budget(ctx: Ctx, n: int) -> None:
    if n > ctx.policy.max_new_entities_per_batch:
        raise policy_error("BUDGET_EXCEEDED", f"Operation would create {n} entities (limit "
                           f"{ctx.policy.max_new_entities_per_batch})", hint="Split the work or raise the limit")


@op("delete", "edit", "Erase entities. Deleting more than the policy threshold needs confirm_large=true.",
    {"target": TARGET, "confirm_large": P("bool", default=False, description="Confirm a large deletion")})
def delete(ctx: Ctx, target, confirm_large):
    ents = select(ctx.doc, target, ctx.refs)
    if len(ents) > ctx.policy.delete_confirm_threshold and not confirm_large:
        raise policy_error("CONFIRMATION_REQUIRED", f"Refusing to delete {len(ents)} entities without confirm_large=true",
                           entities=[e.dxf.handle for e in ents[:20]])
    hs = [e.dxf.handle for e in ents]
    for e in ents:
        ctx.removed(e)
    return {"deleted": hs}


@op("set_properties", "edit", "Change layer / color / linetype / lineweight / tag of entities.",
    {"target": TARGET, "layer": P("string"), "color": P("int", ge=0, le=257), "linetype": P("string"),
     "lineweight": P("int"), "tag": P("string", description="New tag (only valid for a single entity)")})
def set_properties(ctx: Ctx, target, tag, **p):
    ents = select(ctx.doc, target, ctx.refs)
    attrs = ctx.attribs(p)
    if tag is not None and len(ents) != 1:
        raise input_error("TAG_NOT_UNIQUE", "A tag can only be assigned to exactly one entity",
                          entities=[e.dxf.handle for e in ents])
    for e in ents:
        for k, v in attrs.items():
            e.dxf.set(k, v)
        if tag is not None:
            set_tag(ctx.doc, e, tag)
            ctx._tags = None
        ctx.touched(e)
    return {"modified": [e.dxf.handle for e in ents]}


GEOM_FIELDS = {
    "LINE": {"start", "end"}, "CIRCLE": {"center", "radius"}, "ARC": {"center", "radius", "start_angle", "end_angle"},
    "LWPOLYLINE": {"points", "closed"}, "POINT": {"location"}, "TEXT": {"text", "insert", "height", "rotation"},
    "MTEXT": {"text", "insert", "char_height"}, "INSERT": {"insert", "rotation", "xscale", "yscale"},
}


@op("modify", "edit", "Set geometric fields of ONE entity, e.g. {target, set: {radius: 5}} for a circle, "
    "{set: {start: [0,0], end: [10,0]}} for a line, {set: {points: [...], closed: true}} for a polyline, "
    "{set: {text: 'A'}} for text.",
    {"target": TARGET, "set": P("object", True, description="Field -> new value")})
def modify(ctx: Ctx, target, set):  # noqa: A002 - matches the public parameter name
    from .registry import _point
    from ..units import parse_length
    ents = select(ctx.doc, target, ctx.refs)
    if len(ents) != 1:
        raise input_error("TARGET_NOT_UNIQUE", f"modify needs exactly one entity, selector matched {len(ents)}",
                          entities=[e.dxf.handle for e in ents])
    e = ents[0]
    t = e.dxftype()
    allowed = GEOM_FIELDS.get(t)
    if not allowed:
        raise input_error("UNSUPPORTED_ENTITY", f"modify does not support {t}", entities=[e.dxf.handle])
    bad = [k for k in set if k not in allowed]
    if bad:
        raise input_error("UNKNOWN_FIELD", f"{t} has no editable field(s) {bad}", hint=f"Editable: {sorted(allowed)}",
                          entities=[e.dxf.handle])
    for k, v in set.items():
        if k in ("start", "end", "center", "insert", "location"):
            e.dxf.set(k, _point(v, ctx.unit, k))
        elif k in ("radius", "height", "char_height"):
            val = parse_length(v, ctx.unit, k)
            if val <= 0:
                raise input_error("OUT_OF_RANGE", f"{k} must be > 0", entities=[e.dxf.handle])
            e.dxf.set(k, val)
        elif k in ("start_angle", "end_angle", "rotation", "xscale", "yscale"):
            e.dxf.set(k, float(v))
        elif k == "text":
            if t == "MTEXT":
                e.text = str(v)
            else:
                e.dxf.text = str(v)
        elif k == "points":
            pts = [_point(q, ctx.unit, "points", allow_bulge=True) for q in v]
            closed = set.get("closed", e.closed)
            e.set_points([(q[0], q[1], q[2] if len(q) == 3 else 0.0) for q in pts], format="xyb")
            e.closed = closed
        elif k == "closed":
            e.closed = bool(v)
    ctx.touched(e)
    return {"modified": [e.dxf.handle]}


# --- stretch -------------------------------------------------------------------------

def _inside(p, lo, hi) -> bool:
    return lo[0] - 1e-9 <= p[0] <= hi[0] + 1e-9 and lo[1] - 1e-9 <= p[1] <= hi[1] + 1e-9


@op("stretch", "edit", "AutoCAD STRETCH with a crossing window: entities entirely inside move; LINE end points, "
    "polyline vertices and dimension definition points inside the window move; circles/arcs/text/blocks move "
    "if their center/insert point is inside. Dimensions are re-measured.",
    {"window": P("points", True, description="Two opposite corners of the crossing window"),
     "delta": P("point", True, description="Displacement [dx, dy]")})
def stretch(ctx: Ctx, window, delta):
    if len(window) != 2:
        raise input_error("INVALID_WINDOW", "window needs exactly 2 corner points")
    lo = (min(window[0][0], window[1][0]), min(window[0][1], window[1][1]))
    hi = (max(window[0][0], window[1][0]), max(window[0][1], window[1][1]))
    dx, dy = delta
    changed = []
    for e in list(ctx.msp):
        t = e.dxftype()
        x = e.dxf
        hit = False
        if t == "LINE":
            for name in ("start", "end"):
                p = x.get(name)
                if _inside(p, lo, hi):
                    x.set(name, (p.x + dx, p.y + dy, p.z))
                    hit = True
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyseb"))
            new = []
            for px, py, s, en, b in pts:
                if _inside((px, py), lo, hi):
                    px, py = px + dx, py + dy
                    hit = True
                new.append((px, py, s, en, b))
            if hit:
                closed = e.closed
                e.set_points(new, format="xyseb")
                e.closed = closed
        elif t == "DIMENSION":
            for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5"):
                if x.hasattr(name):
                    p = x.get(name)
                    if _inside(p, lo, hi):
                        x.set(name, (p.x + dx, p.y + dy, p.z))
                        hit = True
            if hit:
                if x.hasattr("text_midpoint"):
                    x.discard("text_midpoint")
                rerender_dimension(ctx, e)
        elif t in ("CIRCLE", "ARC", "ELLIPSE"):
            if _inside(x.center, lo, hi):
                e.translate(dx, dy, 0)
                hit = True
        elif t in ("TEXT", "MTEXT", "INSERT"):
            if _inside(x.insert, lo, hi):
                e.translate(dx, dy, 0)
                hit = True
        elif t == "POINT":
            if _inside(x.location, lo, hi):
                e.translate(dx, dy, 0)
                hit = True
        if hit:
            ctx.touched(e)
            changed.append(x.handle)
    return {"modified": changed}


# --- offset / trim / extend / fillet / chamfer ---------------------------------------------

@op("offset", "edit", "Create an offset copy of a LINE, CIRCLE, ARC or straight-segment LWPOLYLINE. The side is "
    "given by 'side_point' (preferred) or by the sign of 'distance' (positive = left of line direction / "
    "outside of circles and closed polylines).",
    {"target": TARGET, "distance": P("length", True, description="Offset distance"),
     "side_point": P("point", description="A point on the side to offset towards")}, common_draw=True)
def offset(ctx: Ctx, target, distance, side_point, **p):
    ents = select(ctx.doc, target, ctx.refs)
    created = []
    for e in ents:
        t = e.dxftype()
        d = abs(distance)
        sign = 1.0 if distance >= 0 else -1.0
        attrs = {"layer": e.dxf.layer, **ctx.attribs(p)}
        if t == "LINE":
            a, b = _vec(e.dxf.start), _vec(e.dxf.end)
            if side_point is not None:
                sign = 1.0 if G.cross(G.sub(b, a), G.sub(side_point, a)) > 0 else -1.0
            u = G.unit(G.sub(b, a))
            n = (-u[1] * d * sign, u[0] * d * sign)
            c = ctx.msp.add_line(G.add(a, n), G.add(b, n), dxfattribs=attrs)
        elif t in ("CIRCLE", "ARC"):
            cen = _vec(e.dxf.center)
            if side_point is not None:
                sign = 1.0 if G.dist(side_point, cen) > e.dxf.radius else -1.0
            nr = e.dxf.radius + sign * d
            if nr <= 1e-9:
                raise geometry_error("OFFSET_COLLAPSES", f"Offset radius {nr:.6g} <= 0", entities=[e.dxf.handle])
            if t == "CIRCLE":
                c = ctx.msp.add_circle(cen, nr, dxfattribs=attrs)
            else:
                c = ctx.msp.add_arc(cen, nr, e.dxf.start_angle, e.dxf.end_angle, dxfattribs=attrs)
        elif t == "LWPOLYLINE":
            raw = list(e.get_points("xyb"))
            if any(abs(q[2]) > 1e-12 for q in raw):
                raise input_error("UNSUPPORTED_GEOMETRY", "offset of polylines with arc segments is not implemented",
                                  entities=[e.dxf.handle], hint="Explode or use straight segments")
            pts = [(q[0], q[1]) for q in raw]
            closed = e.closed
            if closed:
                ccw = G.polygon_area(pts) > 0
                outward = sign > 0
                if side_point is not None:
                    outward = not G.point_in_polygon(side_point, pts)
                # the interior of a CCW polygon is on the left of its edges
                left = -d if ccw == outward else d
            else:
                left = d * sign
                if side_point is not None:
                    best = min(range(len(pts) - 1), key=lambda i: _seg_dist(side_point, pts[i], pts[i + 1]))
                    left = d if G.cross(G.sub(pts[best + 1], pts[best]), G.sub(side_point, pts[best])) > 0 else -d
            new = G.offset_polyline(pts, left, closed)
            c = ctx.msp.add_lwpolyline(new, format="xy", close=closed, dxfattribs=attrs)
        else:
            raise input_error("UNSUPPORTED_ENTITY", f"offset does not support {t}", entities=[e.dxf.handle])
        if p.get("tag"):
            set_tag(ctx.doc, c, p["tag"])
        created.append(ctx.created(c))
    return {"created": created}


def _seg_dist(p, a, b) -> float:
    ab = G.sub(b, a)
    t = max(0.0, min(1.0, G.dot(G.sub(p, a), ab) / max(G.dot(ab, ab), 1e-18)))
    return G.dist(p, G.add(a, G.mul(ab, t)))


def _prims(e) -> list:
    """Bounded primitives (Seg / Circ) of an entity, for intersection tests."""
    t = e.dxftype()
    if t == "LINE":
        return [G.Seg(_vec(e.dxf.start), _vec(e.dxf.end))]
    if t == "CIRCLE":
        return [G.Circ(_vec(e.dxf.center), e.dxf.radius)]
    if t == "ARC":
        return [G.Circ(_vec(e.dxf.center), e.dxf.radius, e.dxf.start_angle % 360, e.dxf.end_angle % 360)]
    if t == "LWPOLYLINE":
        out = []
        for v in e.virtual_entities():
            out.extend(_prims(v))
        return out
    return []


def _edge_prims(ctx: Ctx, edges, exclude: str) -> list:
    prims = []
    for e in select(ctx.doc, edges, ctx.refs, field="edges"):
        if e.dxf.handle != exclude:
            prims.extend(_prims(e))
    if not prims:
        raise input_error("NO_EDGES", "Cutting/boundary edges contain no LINE/CIRCLE/ARC/LWPOLYLINE geometry")
    return prims


@op("trim", "edit", "AutoCAD TRIM: remove the part of the target (LINE, ARC or CIRCLE) that contains 'pick', "
    "bounded by its nearest intersections with the cutting edges. A LINE trimmed in the middle is split in two.",
    {"target": P("selector", True, description="Single LINE / ARC / CIRCLE to trim"),
     "edges": P("selector", True, description="Cutting edges"),
     "pick": P("point", True, description="A point on the portion to remove")})
def trim(ctx: Ctx, target, edges, pick):
    ents = select(ctx.doc, target, ctx.refs)
    if len(ents) != 1:
        raise input_error("TARGET_NOT_UNIQUE", "trim needs exactly one target", entities=[e.dxf.handle for e in ents])
    e = ents[0]
    t = e.dxftype()
    prims = _edge_prims(ctx, edges, e.dxf.handle)
    if t == "LINE":
        seg = G.Seg(_vec(e.dxf.start), _vec(e.dxf.end))
        ts = sorted({round(seg.param(q), 12) for pr in prims for q in G.intersections(seg, pr)})
        ts = [x for x in ts if 1e-9 < x < 1 - 1e-9]
        tp = seg.param(pick)
        lo = max((x for x in ts if x < tp), default=None)
        hi = min((x for x in ts if x > tp), default=None)
        if lo is None and hi is None:
            raise geometry_error("NO_INTERSECTION", "Target does not intersect the cutting edges",
                                 entities=[e.dxf.handle], hint="Check the edge selection or use extend")
        created = []
        if lo is not None and hi is not None:
            c = ctx.msp.add_line(seg.at(hi), seg.q, dxfattribs={"layer": e.dxf.layer, "color": e.dxf.get("color", 256)})
            created.append(ctx.created(c))
            e.dxf.end = seg.at(lo)
        elif lo is not None:
            e.dxf.end = seg.at(lo)
        else:
            e.dxf.start = seg.at(hi)
        ctx.touched(e)
        return {"modified": [e.dxf.handle], "created": created}
    if t in ("ARC", "CIRCLE"):
        c = G.Circ(_vec(e.dxf.center), e.dxf.radius)
        angs = sorted({round(G.angle_of(G.sub(q, c.c)), 10) for pr in prims for q in G.intersections(c, pr)})
        start = e.dxf.start_angle % 360 if t == "ARC" else None
        end = e.dxf.end_angle % 360 if t == "ARC" else None
        ap = G.angle_of(G.sub(pick, c.c))
        if t == "CIRCLE":
            if len(angs) < 2:
                raise geometry_error("NO_INTERSECTION", "A circle needs at least 2 intersections to be trimmed",
                                     entities=[e.dxf.handle])
            # the removed portion is between the nearest crossing before and after the pick angle
            rel = sorted(((a - ap) % 360, a) for a in angs)
            after = rel[0][1]
            before = rel[-1][1]
            attrs = {"layer": e.dxf.layer}
            arc = ctx.msp.add_arc(c.c, c.r, after, before, dxfattribs=attrs)
            tag = get_tag(e)
            h = e.dxf.handle
            ctx.removed(e)
            if tag:
                set_tag(ctx.doc, arc, tag)
            return {"deleted": [h], "created": [ctx.created(arc)]}
        span = G.ccw_span(start, end)
        rel_pick = (ap - start) % 360
        if rel_pick > span:
            raise input_error("PICK_OFF_TARGET", "pick point is not on the arc", entities=[e.dxf.handle])
        rels = [(a - start) % 360 for a in angs if 1e-7 < (a - start) % 360 < span - 1e-7]
        lo = max((x for x in rels if x < rel_pick), default=None)
        hi = min((x for x in rels if x > rel_pick), default=None)
        if lo is None and hi is None:
            raise geometry_error("NO_INTERSECTION", "Arc does not intersect the cutting edges", entities=[e.dxf.handle])
        created = []
        if lo is not None and hi is not None:
            c2 = ctx.msp.add_arc(c.c, c.r, (start + hi) % 360, end, dxfattribs={"layer": e.dxf.layer})
            created.append(ctx.created(c2))
            e.dxf.end_angle = (start + lo) % 360
        elif lo is not None:
            e.dxf.end_angle = (start + lo) % 360
        else:
            e.dxf.start_angle = (start + hi) % 360
        ctx.touched(e)
        return {"modified": [e.dxf.handle], "created": created}
    raise input_error("UNSUPPORTED_ENTITY", f"trim does not support {t}", entities=[e.dxf.handle])


@op("extend", "edit", "AutoCAD EXTEND: lengthen a LINE end until it meets the nearest boundary edge.",
    {"target": P("selector", True, description="Single LINE"), "edges": P("selector", True, description="Boundary edges"),
     "end": P("enum", enum=["start", "end", "auto"], default="auto", description="Which end to extend ('auto' = the end nearer to an intersection)")})
def extend(ctx: Ctx, target, edges, end):
    ents = select(ctx.doc, target, ctx.refs)
    if len(ents) != 1 or ents[0].dxftype() != "LINE":
        raise input_error("UNSUPPORTED_ENTITY", "extend needs exactly one LINE target", entities=[x.dxf.handle for x in ents])
    e = ents[0]
    prims = _edge_prims(ctx, edges, e.dxf.handle)
    s, q = _vec(e.dxf.start), _vec(e.dxf.end)
    best = None
    for which in (["start", "end"] if end == "auto" else [end]):
        seg = G.Seg(s, q) if which == "end" else G.Seg(q, s)
        for pr in prims:
            for x in G.intersections(seg, pr, a_infinite=True):
                tt = seg.param(x)
                if tt > 1 + 1e-9 and (best is None or tt < best[0]):
                    best = (tt, which, x)
    if best is None:
        raise geometry_error("NO_BOUNDARY_INTERSECTION", "Extending the line never meets the boundary",
                             entities=[e.dxf.handle])
    e.dxf.set(best[1], (best[2][0], best[2][1], 0))
    ctx.touched(e)
    return {"modified": [e.dxf.handle], "extended_end": best[1]}


def _two_lines(ctx: Ctx, line1, line2):
    a = select(ctx.doc, line1, ctx.refs, field="line1")
    b = select(ctx.doc, line2, ctx.refs, field="line2")
    if len(a) != 1 or len(b) != 1 or a[0].dxftype() != "LINE" or b[0].dxftype() != "LINE":
        raise input_error("UNSUPPORTED_ENTITY", "fillet/chamfer need exactly one LINE for line1 and line2")
    e1, e2 = a[0], b[0]
    s1 = G.Seg(_vec(e1.dxf.start), _vec(e1.dxf.end))
    s2 = G.Seg(_vec(e2.dxf.start), _vec(e2.dxf.end))
    res = G.line_line(s1, s2)
    if res is None:
        raise geometry_error("PARALLEL_LINES", "Lines are parallel", entities=[e1.dxf.handle, e2.dxf.handle])
    P0 = s1.at(res[0])
    # keep the end farther from the corner
    def far(seg):
        return ("start", seg.p) if G.dist(seg.p, P0) > G.dist(seg.q, P0) else ("end", seg.q)
    return e1, e2, P0, far(s1), far(s2)


@op("fillet", "edit", "AutoCAD FILLET of two LINEs: trims/extends both to tangency and adds a tangent ARC "
    "(radius 0 = sharp corner).",
    {"line1": P("selector", True), "line2": P("selector", True), "radius": P("length", True, ge=0)}, common_draw=True)
def fillet(ctx: Ctx, line1, line2, radius, **p):
    e1, e2, P0, (k1, f1), (k2, f2) = _two_lines(ctx, line1, line2)
    u1, u2 = G.unit(G.sub(f1, P0)), G.unit(G.sub(f2, P0))
    theta = math.acos(max(-1.0, min(1.0, G.dot(u1, u2)))) / 2
    if theta < 1e-9 or abs(theta - math.pi / 2) < 1e-9:
        raise geometry_error("PARALLEL_LINES", "Lines are collinear", entities=[e1.dxf.handle, e2.dxf.handle])
    d = radius / math.tan(theta) if radius > 0 else 0.0
    if d > G.dist(P0, f1) + 1e-9 or d > G.dist(P0, f2) + 1e-9:
        raise geometry_error("FILLET_RADIUS_TOO_LARGE", f"Radius {radius} needs tangent length {d:.6g} which exceeds a line",
                             entities=[e1.dxf.handle, e2.dxf.handle], details={"tangent_length": d})
    t1, t2 = G.add(P0, G.mul(u1, d)), G.add(P0, G.mul(u2, d))
    near1 = "end" if k1 == "start" else "start"
    near2 = "end" if k2 == "start" else "start"
    e1.dxf.set(near1, (t1[0], t1[1], 0))
    e2.dxf.set(near2, (t2[0], t2[1], 0))
    ctx.touched(e1)
    ctx.touched(e2)
    created = []
    if radius > 0:
        bis = G.unit(G.add(u1, u2))
        c = G.add(P0, G.mul(bis, radius / math.sin(theta)))
        a1, a2 = G.angle_of(G.sub(t1, c)), G.angle_of(G.sub(t2, c))
        if G.ccw_span(a1, a2) > 180:
            a1, a2 = a2, a1
        attrs = {"layer": e1.dxf.layer, **ctx.attribs(p)}
        arc = ctx.msp.add_arc(c, radius, a1, a2, dxfattribs=attrs)
        if p.get("tag"):
            set_tag(ctx.doc, arc, p["tag"])
        created.append(ctx.created(arc))
    return {"modified": [e1.dxf.handle, e2.dxf.handle], "created": created}


@op("chamfer", "edit", "AutoCAD CHAMFER of two LINEs with distances d1 (on line1) and d2 (on line2).",
    {"line1": P("selector", True), "line2": P("selector", True), "d1": P("length", True, gt=0),
     "d2": P("length", description="Defaults to d1", gt=0)}, common_draw=True)
def chamfer(ctx: Ctx, line1, line2, d1, d2, **p):
    d2 = d1 if d2 is None else d2
    e1, e2, P0, (k1, f1), (k2, f2) = _two_lines(ctx, line1, line2)
    if d1 > G.dist(P0, f1) + 1e-9 or d2 > G.dist(P0, f2) + 1e-9:
        raise geometry_error("CHAMFER_TOO_LARGE", "Chamfer distance exceeds a line", entities=[e1.dxf.handle, e2.dxf.handle])
    u1, u2 = G.unit(G.sub(f1, P0)), G.unit(G.sub(f2, P0))
    t1, t2 = G.add(P0, G.mul(u1, d1)), G.add(P0, G.mul(u2, d2))
    e1.dxf.set("end" if k1 == "start" else "start", (t1[0], t1[1], 0))
    e2.dxf.set("end" if k2 == "start" else "start", (t2[0], t2[1], 0))
    ctx.touched(e1)
    ctx.touched(e2)
    attrs = {"layer": e1.dxf.layer, **ctx.attribs(p)}
    ln = ctx.msp.add_line(t1, t2, dxfattribs=attrs)
    if p.get("tag"):
        set_tag(ctx.doc, ln, p["tag"])
    return {"modified": [e1.dxf.handle, e2.dxf.handle], "created": [ctx.created(ln)]}


@op("explode", "edit", "Explode block references (INSERT) or polylines into their component entities.",
    {"target": TARGET})
def explode(ctx: Ctx, target):
    ents = select(ctx.doc, target, ctx.refs)
    created, deleted = [], []
    for e in ents:
        if e.dxftype() not in ("INSERT", "LWPOLYLINE"):
            raise input_error("UNSUPPORTED_ENTITY", f"explode does not support {e.dxftype()}", entities=[e.dxf.handle])
        h = e.dxf.handle
        parts = e.explode()
        ctx.deleted.append(h)
        if h in ctx.modified:
            ctx.modified.remove(h)
        deleted.append(h)
        for c in parts:
            created.append(ctx.created(c))
    ctx._tags = None
    return {"created": created, "deleted": deleted}
