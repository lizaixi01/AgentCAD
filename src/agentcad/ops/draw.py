"""Primitive creation operations."""
from __future__ import annotations

import math
from typing import Any

from ezdxf.enums import TextEntityAlignment

from ..errors import geometry_error, input_error
from .registry import Ctx, Param, check_tag, op

P = Param


def _single(ctx: Ctx, e, p: dict[str, Any]) -> dict[str, Any]:
    return {"created": [ctx.finish(e, p)]}


def _guard(ctx: Ctx, p: dict[str, Any]):
    existing = check_tag(ctx, p)
    if existing is not None:
        return {"created": [], "skipped": True, "existing": existing}
    return None


@op("add_line", "draw", "Draw a straight line segment.",
    {"start": P("point", True, description="Start point"), "end": P("point", True, description="End point")},
    common_draw=True)
def add_line(ctx: Ctx, start, end, **p):
    if (s := _guard(ctx, p)):
        return s
    if math.dist(start, end) < 1e-9:
        raise geometry_error("DEGENERATE_GEOMETRY", "Line start and end coincide")
    return _single(ctx, ctx.layout.add_line(start, end, dxfattribs=ctx.attribs(p)), p)


@op("add_polyline", "draw", "Draw a 2D polyline (LWPOLYLINE). Points may carry a bulge as third value "
    "(bulge = tan(arc_angle/4), positive = CCW arc to the next vertex).",
    {"points": P("points", True, description="Vertices"), "closed": P("bool", default=False, description="Close the polyline"),
     "width": P("length", default=0.0, ge=0, description="Constant segment width, drawn filled (PLINE Width)")},
    common_draw=True)
def add_polyline(ctx: Ctx, points, closed, width, **p):
    if (s := _guard(ctx, p)):
        return s
    if len(points) < 2:
        raise input_error("TOO_FEW_POINTS", "A polyline needs at least 2 points")
    pts = [(q[0], q[1], q[2] if len(q) == 3 else 0.0) for q in points]
    e = ctx.layout.add_lwpolyline(pts, format="xyb", close=closed, dxfattribs=ctx.attribs(p))
    if width:
        e.dxf.const_width = width
    return _single(ctx, e, p)


@op("add_polygon", "draw", "Regular polygon (AutoCAD POLYGON) as a closed polyline. Size by 'radius' with mode "
    "'inscribed' (corners on the circle) or 'circumscribed' (edge midpoints on the circle, e.g. a hex nut across "
    "flats), or by 'side_length'. Without 'rotation' the bottom edge is horizontal, as AutoCAD does for a typed "
    "radius; 'rotation' is the direction of the first corner (inscribed / side_length) or of the first edge "
    "midpoint (circumscribed).",
    {"center": P("point", True, description="Center"), "sides": P("int", True, ge=3, le=1024, description="Number of sides"),
     "radius": P("length", gt=0, description="Radius of the construction circle"),
     "mode": P("enum", enum=["inscribed", "circumscribed"], default="inscribed", description="How 'radius' is measured"),
     "side_length": P("length", gt=0, description="Edge length (instead of 'radius')"),
     "rotation": P("angle", description="Direction of the first corner / edge midpoint")}, common_draw=True)
def add_polygon(ctx: Ctx, center, sides, radius, mode, side_length, rotation, **p):
    if (s := _guard(ctx, p)):
        return s
    if (radius is None) == (side_length is None):
        raise input_error("AMBIGUOUS_PARAMS", "add_polygon: give exactly one of 'radius' or 'side_length'")
    half = math.pi / sides
    if side_length is not None:
        r, mode = side_length / (2 * math.sin(half)), "inscribed"
    else:
        r = radius if mode == "inscribed" else radius / math.cos(half)
    if rotation is None:  # bottom edge horizontal: an edge midpoint points straight down
        first = -90.0 + (180.0 / sides)
    else:
        first = rotation + (180.0 / sides if mode == "circumscribed" else 0.0)
    pts = [(center[0] + r * math.cos(math.radians(first) + 2 * half * k),
            center[1] + r * math.sin(math.radians(first) + 2 * half * k)) for k in range(sides)]
    e = ctx.layout.add_lwpolyline(pts, format="xy", close=True, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


@op("add_donut", "draw", "AutoCAD DONUT: a filled ring (inner_diameter 0 = filled disc), stored as AutoCAD does: "
    "a closed LWPOLYLINE of two half-circle segments with a constant width.",
    {"center": P("point", True, description="Center"), "outer_diameter": P("length", True, gt=0, description="Outer diameter"),
     "inner_diameter": P("length", default=0.0, ge=0, description="Inner diameter (0 = solid disc)")}, common_draw=True)
def add_donut(ctx: Ctx, center, outer_diameter, inner_diameter, **p):
    if (s := _guard(ctx, p)):
        return s
    if inner_diameter >= outer_diameter:
        raise geometry_error("DEGENERATE_GEOMETRY", "inner_diameter must be smaller than outer_diameter")
    r = (outer_diameter + inner_diameter) / 4
    e = ctx.layout.add_lwpolyline([(center[0] - r, center[1], 1.0), (center[0] + r, center[1], 1.0)], format="xyb",
                                  close=True, dxfattribs=ctx.attribs(p))
    e.dxf.const_width = (outer_diameter - inner_diameter) / 2
    return _single(ctx, e, p)


def _direction(base, through, angle, name: str):
    if (through is None) == (angle is None):
        raise input_error("AMBIGUOUS_PARAMS", f"{name}: give exactly one of 'through' or 'angle'")
    if through is not None:
        d = (through[0] - base[0], through[1] - base[1])
        n = math.hypot(*d)
        if n < 1e-9:
            raise geometry_error("DEGENERATE_GEOMETRY", f"{name}: 'through' coincides with 'point'")
        return (d[0] / n, d[1] / n, 0.0)
    a = math.radians(angle)
    return (math.cos(a), math.sin(a), 0.0)


XL_PARAMS = {"point": P("point", True, description="A point on the line"),
             "through": P("point", description="Second point that gives the direction"),
             "angle": P("angle", description="Direction (instead of 'through')")}


@op("add_xline", "draw", "Construction line infinite in both directions (AutoCAD XLINE). Not counted in extents.",
    XL_PARAMS, common_draw=True)
def add_xline(ctx: Ctx, point, through, angle, **p):
    if (s := _guard(ctx, p)):
        return s
    d = _direction(point, through, angle, "add_xline")
    return _single(ctx, ctx.layout.add_xline(point, d, dxfattribs=ctx.attribs(p)), p)


@op("add_ray", "draw", "Construction line from 'point' to infinity in one direction (AutoCAD RAY).",
    XL_PARAMS, common_draw=True)
def add_ray(ctx: Ctx, point, through, angle, **p):
    if (s := _guard(ctx, p)):
        return s
    d = _direction(point, through, angle, "add_ray")
    return _single(ctx, ctx.layout.add_ray(point, d, dxfattribs=ctx.attribs(p)), p)


def _loop_area(pts) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _hatch_loops(ctx: Ctx, boundary, points, holes) -> list[tuple[str, Any]]:
    """Boundary loops as ('poly', [(x, y, bulge)]), ('circle', (center, r)) or ('ellipse', entity)."""
    from ..model import circle_wcs, lwpoly_wcs, select
    if (boundary is None) == (points is None):
        raise input_error("AMBIGUOUS_PARAMS", "add_hatch: give exactly one of 'boundary' (entities) or 'points'")
    if holes and points is None:
        raise input_error("AMBIGUOUS_PARAMS", "add_hatch: 'holes' goes with 'points'; with 'boundary' select the "
                          "hole entities too")
    loops: list[tuple[str, Any]] = []
    if points is not None:
        for i, loop in enumerate([points, *(holes or [])]):
            name = "points" if i == 0 else f"holes[{i - 1}]"
            if i and (not isinstance(loop, list) or not loop):
                raise input_error("INVALID_POINTS", f"{name}: expected a list of points")
            if i:
                from .registry import _point
                loop = [_point(q, ctx.unit, f"{name}[{k}]", allow_bulge=True) for k, q in enumerate(loop)]
            pts = [(q[0], q[1], q[2] if len(q) == 3 else 0.0) for q in loop]
            if len(pts) > 1 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-9:
                pts = pts[:-1]
            if (len(pts) < 3 and not any(b for _, _, b in pts)) or len(pts) < 2:
                raise geometry_error("DEGENERATE_GEOMETRY", f"{name}: a hatch loop needs at least 3 points")
            if not any(b for _, _, b in pts) and abs(_loop_area([q[:2] for q in pts])) < 1e-12:
                raise geometry_error("DEGENERATE_GEOMETRY", f"{name}: hatch loop encloses no area")
            loops.append(("poly", pts))
        return loops
    for e in select(ctx.doc, boundary, ctx.refs, field="boundary"):
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = lwpoly_wcs(e)
            if not e.closed and not (len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-9):
                raise geometry_error("BOUNDARY_NOT_CLOSED", f"Polyline {e.dxf.handle} is not closed",
                                     entities=[e.dxf.handle], hint="Close it (modify closed=true) or use 'points'")
            loops.append(("poly", pts))
        elif t == "CIRCLE":
            c, r, _, _ = circle_wcs(e)
            loops.append(("circle", (c, r)))
        elif t == "ELLIPSE" and abs(abs(e.dxf.end_param - e.dxf.start_param) - 2 * math.pi) < 1e-9:
            loops.append(("ellipse", e))
        else:
            raise input_error("UNSUPPORTED_BOUNDARY", f"{t} {e.dxf.handle} is not a closed boundary",
                              entities=[e.dxf.handle],
                              hint="Use closed LWPOLYLINE / CIRCLE / full ELLIPSE entities, or 'points'")
    return loops


@op("add_hatch", "draw", "Fill an area (AutoCAD HATCH). Boundary: 'boundary' = closed LWPOLYLINE / CIRCLE / full "
    "ELLIPSE entities (several = islands, filled by the odd-even rule), or 'points' (outer loop, bulges allowed) "
    "plus optional 'holes' (list of point loops). 'pattern' is SOLID (default) or a standard pattern such as "
    "ANSI31 (section lines), ANSI37, ANGLE, BRICK, DOTS, NET, AR-CONC, AR-SAND, with 'pattern_scale' and "
    "'pattern_angle'. The hatch is not associative: editing the boundary later does not update it. 'behind' "
    "(default true) draws it under everything already in the layout.",
    {"boundary": P("selector", description="Closed boundary entities"),
     "points": P("points", description="Outer loop (instead of 'boundary')"),
     "holes": P("list", description="Inner loops, each a list of [x, y] (or [x, y, bulge])"),
     "pattern": P("string", default="SOLID", description="SOLID or a pattern name (ANSI31, ...)"),
     "pattern_scale": P("number", default=1.0, gt=0, description="Pattern scale"),
     "pattern_angle": P("angle", default=0.0, description="Pattern rotation"),
     "behind": P("bool", default=True, description="Send the hatch to the back of the draw order")}, common_draw=True)
def add_hatch(ctx: Ctx, boundary, points, holes, pattern, pattern_scale, pattern_angle, behind, **p):
    from ezdxf.tools import pattern as patterns
    if (s := _guard(ctx, p)):
        return s
    name = pattern.upper()
    if name != "SOLID" and name not in patterns.ISO_PATTERN:
        raise input_error("UNKNOWN_PATTERN", f"Hatch pattern {pattern!r} is not defined",
                          hint=f"SOLID or one of {sorted(patterns.ISO_PATTERN)}")
    loops = _hatch_loops(ctx, boundary, points, holes)
    attrs = ctx.attribs(p)
    color = attrs.pop("color", 256)  # ezdxf's fill setters default to color 7: pass it explicitly
    h = ctx.layout.add_hatch(color=color, dxfattribs=attrs)
    if name == "SOLID":
        h.set_solid_fill(color=color, style=0)
    else:  # ezdxf picks the ISO or imperial definition from $MEASUREMENT, which create_drawing sets
        h.set_pattern_fill(name, color=color, angle=pattern_angle, scale=pattern_scale, style=0)
    for i, (kind, data) in enumerate(loops):
        flags = 1 if i == 0 else 0  # first loop external, the rest default (odd-even nesting)
        if kind == "poly":
            h.paths.add_polyline_path(data, is_closed=True, flags=flags | 2)
        elif kind == "circle":
            h.paths.add_edge_path(flags).add_arc(data[0], data[1], 0, 360)
        else:
            el = data
            h.paths.add_edge_path(flags).add_ellipse(el.dxf.center, el.dxf.major_axis, el.dxf.ratio, 0, 360)
    created = _single(ctx, h, p)
    if behind:
        restack(ctx.layout, [h.dxf.handle], front=False)
    return created


def restack(space, moved: list[str], front: bool) -> None:
    """Draw order (SORTENTS): put 'moved' on top of or under every other entity of 'space'. The sort handles
    are the space's own entity handles redistributed, as AutoCAD's DRAWORDER does."""
    current = dict(space.get_redraw_order())
    ents = [e.dxf.handle for e in space]
    key = {h: int(current.get(h, h), 16) for h in ents}
    order = sorted(ents, key=lambda h: (key[h], int(h, 16)))
    mset = set(moved)
    rest = [h for h in order if h not in mset]
    mv = [h for h in order if h in mset]
    new = rest + mv if front else mv + rest
    slots = sorted(int(h, 16) for h in ents)
    space.set_redraw_order({h: format(k, "X") for h, k in zip(new, slots)})


@op("add_rectangle", "draw", "Draw an axis-aligned (optionally rotated) rectangle as a closed polyline. "
    "Give either 'corner' (lower-left) or 'center'.",
    {"corner": P("point", description="Lower-left corner"), "center": P("point", description="Center point"),
     "width": P("length", True, gt=0, description="Size along X"), "height": P("length", True, gt=0, description="Size along Y"),
     "corner_radius": P("length", default=0.0, ge=0, description="Fillet radius of all four corners"),
     "rotation": P("angle", default=0.0, description="Rotation about the corner/center")},
    common_draw=True)
def add_rectangle(ctx: Ctx, corner, center, width, height, corner_radius, rotation, **p):
    if (s := _guard(ctx, p)):
        return s
    if (corner is None) == (center is None):
        raise input_error("AMBIGUOUS_PARAMS", "add_rectangle: give exactly one of 'corner' or 'center'")
    if corner_radius * 2 > min(width, height) + 1e-9:
        raise geometry_error("RADIUS_TOO_LARGE", f"corner_radius {corner_radius} exceeds half of the shorter side")
    if center is not None:
        ox, oy = center[0] - width / 2, center[1] - height / 2
        pivot = center
    else:
        ox, oy = corner
        pivot = corner
    r = corner_radius
    if r <= 0:
        pts = [(ox, oy, 0.0), (ox + width, oy, 0.0), (ox + width, oy + height, 0.0), (ox, oy + height, 0.0)]
    else:
        b = math.tan(math.radians(90) / 4)
        pts = [(ox + r, oy, 0.0), (ox + width - r, oy, b), (ox + width, oy + r, 0.0), (ox + width, oy + height - r, b),
               (ox + width - r, oy + height, 0.0), (ox + r, oy + height, b), (ox, oy + height - r, 0.0), (ox, oy + r, b)]
    if rotation:
        a = math.radians(rotation)
        c, s_ = math.cos(a), math.sin(a)
        pts = [(pivot[0] + (x - pivot[0]) * c - (y - pivot[1]) * s_,
                pivot[1] + (x - pivot[0]) * s_ + (y - pivot[1]) * c, bb) for x, y, bb in pts]
    e = ctx.layout.add_lwpolyline(pts, format="xyb", close=True, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


@op("add_circle", "draw", "Draw a circle. Give 'radius' or 'diameter'.",
    {"center": P("point", True, description="Center"), "radius": P("length", gt=0, description="Radius"),
     "diameter": P("length", gt=0, description="Diameter")}, common_draw=True)
def add_circle(ctx: Ctx, center, radius, diameter, **p):
    if (s := _guard(ctx, p)):
        return s
    if (radius is None) == (diameter is None):
        raise input_error("AMBIGUOUS_PARAMS", "add_circle: give exactly one of 'radius' or 'diameter'")
    rad = radius if radius is not None else diameter / 2
    return _single(ctx, ctx.layout.add_circle(center, rad, dxfattribs=ctx.attribs(p)), p)


@op("add_arc", "draw", "Draw a circular arc, counter-clockwise from start_angle to end_angle (degrees). "
    "Alternatively give three points 'start', 'mid', 'end' on the arc.",
    {"center": P("point", description="Center"), "radius": P("length", gt=0, description="Radius"),
     "start_angle": P("angle", description="Start angle"), "end_angle": P("angle", description="End angle"),
     "start": P("point", description="3-point form: start point"), "mid": P("point", description="3-point form: point on arc"),
     "end": P("point", description="3-point form: end point")}, common_draw=True)
def add_arc(ctx: Ctx, center, radius, start_angle, end_angle, start, mid, end, **p):
    if (s := _guard(ctx, p)):
        return s
    if start is not None or mid is not None or end is not None:
        if None in (start, mid, end):
            raise input_error("MISSING_PARAM", "add_arc 3-point form needs start, mid and end")
        center, radius, start_angle, end_angle = arc_from_3p(start, mid, end)
    elif None in (center, radius, start_angle, end_angle):
        raise input_error("MISSING_PARAM", "add_arc needs center, radius, start_angle, end_angle (or start/mid/end)")
    if abs((end_angle - start_angle) % 360.0) < 1e-9:
        raise geometry_error("DEGENERATE_GEOMETRY", "Arc start and end angle coincide (use add_circle for a full circle)")
    e = ctx.layout.add_arc(center, radius, start_angle % 360.0, end_angle % 360.0, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


def arc_from_3p(s, m, e):
    """Arc through start, mid, end. DXF arcs are always CCW, so a clockwise pick
    order is stored as the CCW arc from end to start (AutoCAD 2027 does the same,
    tests/golden/autocad_ops.json: arc_three_point_cw)."""
    from .. import geom as G
    ax, ay = s[0], s[1]
    bx, by = m[0], m[1]
    cx, cy = e[0], e[1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        raise geometry_error("DEGENERATE_GEOMETRY", "Cannot fit an arc through 3 collinear or coincident points")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    c = (ux, uy)
    a_s, a_m, a_e = (G.angle_of(G.sub(p, c)) for p in (s, m, e))
    if G.angle_in_arc(a_m, a_s, a_e):
        return c, G.dist(c, s), a_s, a_e
    return c, G.dist(c, s), a_e, a_s


@op("add_ellipse", "draw", "Draw an ellipse (or elliptical arc) by semi-axes rx, ry and rotation.",
    {"center": P("point", True, description="Center"), "rx": P("length", True, gt=0, description="Semi-axis along the rotated X"),
     "ry": P("length", True, gt=0, description="Semi-axis along the rotated Y"),
     "rotation": P("angle", default=0.0, description="Rotation of the rx axis"),
     "start_angle": P("angle", default=0.0, description="Start parameter angle"),
     "end_angle": P("angle", default=360.0, description="End parameter angle")}, common_draw=True)
def add_ellipse(ctx: Ctx, center, rx, ry, rotation, start_angle, end_angle, **p):
    if (s := _guard(ctx, p)):
        return s
    rot = math.radians(rotation)
    sp, ep = math.radians(start_angle), math.radians(end_angle)
    if ry > rx:  # DXF requires ratio <= 1: swap axes, shift parameters by 90 deg
        rx, ry = ry, rx
        rot += math.pi / 2
        sp -= math.pi / 2
        ep -= math.pi / 2
    major = (rx * math.cos(rot), rx * math.sin(rot), 0)
    e = ctx.layout.add_ellipse(center, major, ry / rx, sp, ep, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


@op("add_spline", "draw", "Draw a spline through fit points.",
    {"fit_points": P("points", True, description="Fit points"), "degree": P("int", default=3, ge=1, le=11, description="Degree")},
    common_draw=True)
def add_spline(ctx: Ctx, fit_points, degree, **p):
    if (s := _guard(ctx, p)):
        return s
    if len(fit_points) < 2:
        raise input_error("TOO_FEW_POINTS", "A spline needs at least 2 fit points")
    e = ctx.layout.add_spline([(q[0], q[1]) for q in fit_points], degree=degree, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


@op("add_point", "draw", "Draw a point entity.", {"location": P("point", True, description="Location")}, common_draw=True)
def add_point(ctx: Ctx, location, **p):
    if (s := _guard(ctx, p)):
        return s
    return _single(ctx, ctx.layout.add_point(location, dxfattribs=ctx.attribs(p)), p)


ALIGN = {"left": TextEntityAlignment.LEFT, "center": TextEntityAlignment.CENTER, "right": TextEntityAlignment.RIGHT,
         "middle": TextEntityAlignment.MIDDLE, "middle_center": TextEntityAlignment.MIDDLE_CENTER,
         "top_left": TextEntityAlignment.TOP_LEFT, "top_center": TextEntityAlignment.TOP_CENTER,
         "bottom_center": TextEntityAlignment.BOTTOM_CENTER, "middle_left": TextEntityAlignment.MIDDLE_LEFT}


@op("add_text", "annotate", "Single-line text.",
    {"text": P("string", True, description="Text content"), "insert": P("point", True, description="Alignment point"),
     "height": P("length", default=2.5, gt=0, description="Text height"), "rotation": P("angle", default=0.0, description="Rotation"),
     "align": P("enum", enum=list(ALIGN), default="left", description="Alignment of the insert point"),
     "style": P("string", description="Text style (see create_text_style); default Standard")},
    common_draw=True)
def add_text(ctx: Ctx, text, insert, height, rotation, align, style, **p):
    from .annotate import text_style
    if (s := _guard(ctx, p)):
        return s
    attrs = ctx.attribs(p)
    attrs.update(height=height, rotation=rotation, **text_style(ctx, style))
    e = ctx.layout.add_text(text, dxfattribs=attrs)
    e.set_placement(insert, align=ALIGN[align])
    return _single(ctx, e, p)


@op("add_mtext", "annotate", "Multi-line text (MTEXT). Use '\\P' or newlines for line breaks.",
    {"text": P("string", True, description="Text content"), "insert": P("point", True, description="Top-left insert point"),
     "char_height": P("length", default=2.5, gt=0, description="Character height"),
     "width": P("length", gt=0, description="Reference column width (optional)"),
     "style": P("string", description="Text style (see create_text_style); default Standard")}, common_draw=True)
def add_mtext(ctx: Ctx, text, insert, char_height, width, style, **p):
    from .annotate import text_style
    if (s := _guard(ctx, p)):
        return s
    attrs = ctx.attribs(p)
    attrs.update(insert=insert, char_height=char_height, **text_style(ctx, style))
    if width:
        attrs["width"] = width
    e = ctx.layout.add_mtext(text.replace("\n", "\\P"), dxfattribs=attrs)
    return _single(ctx, e, p)
