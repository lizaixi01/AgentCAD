"""Domain operations participate in the same transaction and permission policy as primitives."""

from .registry import Ctx, Param as P, op


@op(
    "draw_pid",
    "engineering",
    "Create a port-connected P&ID from equipment, valves, instruments, connectors "
    "and lines. Entity-local semantic records survive DXF; read_engineering reconstructs and checks the graph.",
    {"spec": P("object", True)},
)
def draw_pid(ctx: Ctx, spec):
    from ..engineering.pid import draw

    return draw(ctx, spec)


@op(
    "draw_arch_plan",
    "engineering",
    "Draw an orthogonal wall plan with hosted doors/windows, stairs, "
    "measured room labels, dimensions and schedules. Room detection reads wall solids and opening thresholds.",
    {"spec": P("object", True, description=(
        "Millimetres, model space. "
        "walls: [{id, axis: [[x,y],...] axis-aligned centre-line points, thickness, closed: true for a loop "
        "(exterior wall), material?}]. "
        "openings: [{id, kind: door|window, wall: wall id, offset: distance along that wall's axis from its first "
        "point (cumulative over its segments, closed loops include the closing segment) to the opening's start, "
        "width, hand?: left|right (door hinge side), tag? (mark shown, default id), height?, sill?}]; an opening "
        "must lie on one segment. "
        "rooms: [{id, number, name, at: [x,y] inside the room, area? in mm2, refused if it disagrees with the "
        "walls}]; the label reads '<number> <name> <area> m²'. "
        "stairs: [{id, start: [x,y], width, going, risers, riser_height, direction_deg?}]. "
        "chains: {sides: [bottom|top|left|right]}: a chain through every wall and opening corner on that "
        "exterior face, plus an overall dimension when the chain has more than one segment. "
        "schedules: [{kind: rooms|doors|windows, at: [x,y]}]. "
        "sheet: {scale: N} for 1:N (text and dimension sizes, default 50). poche: fill walls (default true). "
        "lang: 'en' only (schedule headings). "
        "Example: {walls: [{id: 'ext', axis: [[120,120],[8880,120],[8880,5880],[120,5880]], closed: true, "
        "thickness: 240}], openings: [{id: 'M1', kind: 'door', wall: 'ext', offset: 1080, width: 1000}], "
        "rooms: [{id: 'r1', number: '1', name: 'Living', at: [4500,3000]}], chains: {sides: ['bottom']}}"))},
)
def draw_arch_plan(ctx: Ctx, spec):
    from ..engineering.architecture import draw

    return draw(ctx, spec)


@op(
    "draw_mechanical_assembly",
    "engineering",
    "Draw revolved parts with front/end/longitudinal-section views, "
    "segment/overall lengths, outer/bore diameters, hole quantity/diameter/PCD/orientation, "
    "standard fasteners, an A3 sheet, a drawing-derived BOM and linked balloons. "
    "Saved annotation checks bind actual geometry, native definitions and displayed values. "
    "Hole depth, tolerances and finish are not inferred.",
    {"spec": P("object", True)},
)
def draw_mechanical_assembly(ctx: Ctx, spec):
    from ..engineering.mechanical import draw

    return draw(ctx, spec)
