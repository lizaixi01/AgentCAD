"""Drawing operations that derive geometry or clean existing entities."""

import json
import math

from .. import geom as G
from ..errors import input_error, policy_error
from ..measure import flatten, poly_metrics
from ..model import select
from .edit import _segments, _reverse
from .registry import Ctx, Param as P, op


@op(
    "trace_boundary",
    "draw",
    "BPOLY / BOUNDARY: trace a simple closed LINE/ARC/open-polyline chain around an "
    "interior point. Sources remain. Intersecting or branching networks require trimming first.",
    {"point": P("point", True), "tolerance": P("length", default=1e-6, gt=0)},
    common_draw=True,
)
def trace_boundary(ctx: Ctx, point, tolerance, **p):
    pieces = []
    candidates = []
    for e in ctx.layout:
        if e.dxftype() == "LWPOLYLINE" and e.closed:
            verts = list(e.get_points("xyb"))
            if G.point_in_polygon(point, flatten(verts)):
                candidates.append((abs(poly_metrics(verts)[0]), verts, [e.dxf.handle]))
        elif e.dxftype() in {"LINE", "ARC", "LWPOLYLINE"}:
            pieces.append((e.dxf.handle, _segments(e)))
    while pieces:
        handle, chain = pieces.pop(0)
        sources = [handle]
        while math.dist(chain[0][0], chain[-1][1]) > tolerance:
            matches = [
                (i, rev)
                for i, (_, segs) in enumerate(pieces)
                for rev, endpoint in [(False, segs[0][0]), (True, segs[-1][1])]
                if math.dist(chain[-1][1], endpoint) <= tolerance
            ]
            if len(matches) != 1:
                break
            i, reverse = matches[0]
            h, segs = pieces.pop(i)
            sources.append(h)
            chain += _reverse(segs) if reverse else segs
        if math.dist(chain[0][0], chain[-1][1]) <= tolerance:
            verts = [(a[0], a[1], bulge) for a, _, bulge in chain]
            if G.point_in_polygon(point, flatten(verts)):
                candidates.append((abs(poly_metrics(verts)[0]), verts, sources))
    if not candidates:
        raise input_error("BOUNDARY_NOT_FOUND", "No simple closed chain encloses the point")
    area, verts, sources = min(candidates, key=lambda row: row[0])
    e = ctx.layout.add_lwpolyline(verts, format="xyb", close=True, dxfattribs=ctx.attribs(p))
    return {"created": [ctx.finish(e, p)], "sources": sources, "closed": True, "area": area}


@op(
    "edit_hatch",
    "edit",
    "Change HATCH island style, preserving its boundaries.",
    {"target": P("selector", True), "style": P("enum", True, enum=["normal", "outer", "ignore"])},
)
def edit_hatch(ctx: Ctx, target, style):
    entities = select(ctx.doc, target, ctx.refs)
    changes = []
    for e in entities:
        if e.dxftype() != "HATCH":
            raise input_error("WRONG_ENTITY_TYPE", "edit_hatch requires HATCH entities")
        old = {0: "normal", 1: "outer", 2: "ignore"}[e.dxf.hatch_style]
        e.dxf.hatch_style = {"normal": 0, "outer": 1, "ignore": 2}[style]
        ctx.touched(e)
        changes.append({"handle": e.dxf.handle, "changed": {"style": {"old": old, "new": style}}})
    return {"modified": [e.dxf.handle for e in entities], "edits": changes}


@op(
    "remove_duplicates",
    "edit",
    "OVERKILL: remove exact duplicate geometry on each layout, keeping the first.",
    {"tolerance": P("length", default=1e-6, gt=0), "confirm_large": P("bool", default=False)},
)
def remove_duplicates(ctx: Ctx, tolerance, confirm_large):
    from ..validate.checks import geometry_key

    seen, duplicates = set(), []
    for e in list(ctx.layout):
        key = geometry_key(e, tolerance)
        if key is None:
            continue
        # Geometry similarity alone cannot justify deleting distinct attributes,
        # widths, elevations, domain records or dimension overrides.
        attrs = {k: v for k, v in e.dxfattribs().items() if k not in {"handle", "owner"}}
        if e.dxftype() == "LINE":
            attrs["start"], attrs["end"] = sorted([tuple(e.dxf.start), tuple(e.dxf.end)])
        semantic = {
            "dxf": attrs,
            "xdata": getattr(getattr(e, "xdata", None), "data", {}),
            "attributes": [(a.dxf.tag, a.dxf.text) for a in getattr(e, "attribs", ())],
        }
        if e.dxftype() == "LWPOLYLINE":
            semantic["vertices"] = list(e.get_points("xyseb"))
        key = (key, json.dumps(semantic, sort_keys=True, default=str))
        if key in seen:
            duplicates.append(e)
        else:
            seen.add(key)
    if len(duplicates) > ctx.policy.delete_confirm_threshold and not confirm_large:
        raise policy_error("CONFIRMATION_REQUIRED", "Large duplicate removal needs confirm_large=true")
    deleted = [e.dxf.handle for e in duplicates]
    for e in duplicates:
        ctx.removed(e)
    return {"deleted": deleted}
