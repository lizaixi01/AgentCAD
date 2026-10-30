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
    {"spec": P("object", True)},
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
