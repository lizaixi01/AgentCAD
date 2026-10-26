"""Primitive creation operations."""
from __future__ import annotations

import math
from typing import Any

from ezdxf.enums import TextEntityAlignment
from ezdxf.math import ConstructionArc

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
    {"points": P("points", True, description="Vertices"), "closed": P("bool", default=False, description="Close the polyline")},
    common_draw=True)
def add_polyline(ctx: Ctx, points, closed, **p):
    if (s := _guard(ctx, p)):
        return s
    if len(points) < 2:
        raise input_error("TOO_FEW_POINTS", "A polyline needs at least 2 points")
    pts = [(q[0], q[1], q[2] if len(q) == 3 else 0.0) for q in points]
    e = ctx.layout.add_lwpolyline(pts, format="xyb", close=closed, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


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
        try:
            ca = ConstructionArc.from_3p(start, end, mid)
        except Exception as exc:
            raise geometry_error("DEGENERATE_GEOMETRY", f"Cannot fit an arc through the 3 points: {exc}")
        center, radius, start_angle, end_angle = ca.center, ca.radius, ca.start_angle, ca.end_angle
    elif None in (center, radius, start_angle, end_angle):
        raise input_error("MISSING_PARAM", "add_arc needs center, radius, start_angle, end_angle (or start/mid/end)")
    if abs((end_angle - start_angle) % 360.0) < 1e-9:
        raise geometry_error("DEGENERATE_GEOMETRY", "Arc start and end angle coincide (use add_circle for a full circle)")
    e = ctx.layout.add_arc(center, radius, start_angle % 360.0, end_angle % 360.0, dxfattribs=ctx.attribs(p))
    return _single(ctx, e, p)


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
     "align": P("enum", enum=list(ALIGN), default="left", description="Alignment of the insert point")},
    common_draw=True)
def add_text(ctx: Ctx, text, insert, height, rotation, align, **p):
    if (s := _guard(ctx, p)):
        return s
    attrs = ctx.attribs(p)
    attrs.update(height=height, rotation=rotation)
    e = ctx.layout.add_text(text, dxfattribs=attrs)
    e.set_placement(insert, align=ALIGN[align])
    return _single(ctx, e, p)


@op("add_mtext", "annotate", "Multi-line text (MTEXT). Use '\\P' or newlines for line breaks.",
    {"text": P("string", True, description="Text content"), "insert": P("point", True, description="Top-left insert point"),
     "char_height": P("length", default=2.5, gt=0, description="Character height"),
     "width": P("length", gt=0, description="Reference column width (optional)")}, common_draw=True)
def add_mtext(ctx: Ctx, text, insert, char_height, width, **p):
    if (s := _guard(ctx, p)):
        return s
    attrs = ctx.attribs(p)
    attrs.update(insert=insert, char_height=char_height)
    if width:
        attrs["width"] = width
    e = ctx.layout.add_mtext(text.replace("\n", "\\P"), dxfattribs=attrs)
    return _single(ctx, e, p)
