"""Catalog of 3D part operations (``apply_operations`` on a ``.FCStd`` part).

The definitions drive the schemas in ``list_operations`` and the checks made before FreeCAD starts (known op,
known parameters, required parameters, basic types). FreeCAD executes them in ``_fc_runner.py``, which also parses
lengths and expressions, so a value means the same thing whether it was typed or recorded.

Every op makes native PartDesign features only, the editable feature tree that CADBench accepts.
"""
from __future__ import annotations

import difflib
from typing import Any

from ..errors import input_error, policy_error
from ..ops.registry import OpDef, Param, coerce

PART_REGISTRY: dict[str, OpDef] = {}


def _unrunnable(*_a: Any, **_k: Any) -> dict[str, Any]:  # executed by the FreeCAD runner, never in-process
    raise RuntimeError("part operations run in FreeCAD")


BODY = "Body to add to (default: the part's only Body, created on first use)"
TAG = "Name for later reference as 'tag:<name>'"


def part_op(name: str, category: str, description: str, params: dict[str, Param], *, creates: bool = True) -> None:
    if creates:
        params = {**params, "body": Param("string", description=BODY), "tag": Param("string", description=TAG)}
    PART_REGISTRY[name] = OpDef(name, category, description, params, _unrunnable, common_all=False)


def part_schema(d: OpDef) -> dict[str, Any]:
    """A part op's JSON schema with the text many ops share replaced by a pointer into PART_CONVENTIONS, which
    list_operations sends once."""
    def short(v: Any) -> Any:
        if isinstance(v, str):
            for long, brief in _SHORT:
                v = v.replace(long, brief)
            return v
        if isinstance(v, dict):
            return {k: short(x) for k, x in v.items()}
        if isinstance(v, list):
            return [short(x) for x in v]
        return v
    s = d.schema()
    s["params"] = short(s["params"])
    return s


REF = "feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001'"
EDGES = ("edge selector, re-resolved after every edit: 'all', 'Edge3', or an object with any of type "
         "(line|circle|...), direction (x|y|z|-z|[x,y,z], lines parallel to it), axis (circles around it), "
         "radius|diameter, length, x|y|z (all points on that coordinate), box [[x0,y0,z0],[x1,y1,z1]], "
         "face (a face selector: edges of those faces), near [x,y,z] + count (nearest ones); a list unites "
         "selectors")
FACES = ("face selector, re-resolved after every edit: 'top'|'bottom'|'front'|'back'|'left'|'right' (outermost "
         "planar face), 'Face2', or an object with any of type (plane|cylinder|...), normal (+z|-x|[x,y,z]), "
         "extreme (max|min along the normal), axis, radius|diameter, inner (holes), x|y|z, box, near + count")
DIM_SUFFIX = " (mm, a string with a unit such as '0.5in', or an expression such as '=Params.width * 2')"
# Sent once per list_operations result instead of inside every part schema.
PART_CONVENTIONS = {
    "dim": "a length or angle: a number (mm or degrees), a string with a unit ('0.5in', '30deg'), or an expression "
           "such as '=Params.width * 2'",
    "edges": EDGES, "faces": FACES, "feature": REF,
    "body": BODY + " (every op that adds a feature)", "tag": TAG + " (every op that adds a feature)",
}
_SHORT = ((DIM_SUFFIX, " (dim)"), (EDGES, "edge selector (see conventions.edges)"),
          (FACES, "face selector (see conventions.faces)"), (REF, "feature reference (see conventions.feature)"),
          (BODY, "see conventions.body"), (TAG, "see conventions.tag"))

SHAPES = ("closed profiles (or construction geometry), each {type, ...}: rectangle {corner [x,y] (lower left) | "
          "center, width, height, name}; circle {center, diameter | radius, name}; polygon {points: [[x,y] | "
          "[x,y,bulge], ...]}; polyline {points, closed}; regular_polygon {center, sides, circumradius | "
          "across_flats, rotation}; slot {start, end, width}; line {start, end}; arc {center, radius, "
          "start_angle, end_angle}; point {at}. Any shape: construction=true. Rectangle sizes and circle "
          "diameters accept expressions ('=Params.w'). End points that touch are joined; every shape is fully "
          "constrained. Coordinates are in the sketch plane")

part_op("set_parameters", "part_edit",
        "Create or change named parameters (a FreeCAD spreadsheet 'Params'). Reference them in any dimension as "
        "'=Params.<name>'; changing one later re-solves every feature that uses it. Names must not be units or "
        "reserved words (t, m, mm, deg, pi)",
        {"params": Param("object", required=True, description="{name: number | '8mm' | '=expression'}")},
        creates=False)
part_op("add_sketch", "part_sketch",
        "Add a sketch: placed on an origin plane (plane + offset), on a planar face of the solid (on_face; "
        "sketch x/y then follow the global axes projected onto the face, origin = global origin projected), "
        "or by origin + normal (+ x_dir)",
        {"shapes": Param("list", required=True, description=SHAPES),
         "plane": Param("enum", enum=["XY", "XZ", "YZ"], description="Origin plane (default XY). XY: x=X, y=Y, "
                        "normal +Z. XZ: x=X, y=Z, normal -Y. YZ: x=Y, y=Z, normal +X"),
         "offset": Param("dim", description="Distance along the plane's normal"),
         "on_face": Param("any", description=FACES + "; must match one planar face"),
         "origin": Param("list", description="[x, y, z] of the sketch origin (with normal)"),
         "normal": Param("list", description="[x, y, z] sketch normal (with origin)"),
         "x_dir": Param("list", description="[x, y, z] sketch x axis (default: global X projected)")})
part_op("pad", "part_feature", "Extrude a sketch's closed profiles into solid, along the sketch normal",
        {"sketch": Param("string", required=True, description="Sketch " + REF),
         "length": Param("dim", required=True, description="Extrusion length"),
         "symmetric": Param("bool", default=False, description="Extrude half to each side of the sketch"),
         "reversed": Param("bool", default=False, description="Extrude against the normal")})
part_op("pocket", "part_feature", "Cut a sketch's closed profiles out of the solid, against the sketch normal",
        {"sketch": Param("string", required=True, description="Sketch " + REF),
         "depth": Param("dim", description="Cut depth (or through_all)"),
         "through_all": Param("bool", default=False, description="Cut through the whole solid"),
         "symmetric": Param("bool", default=False, description="Cut half to each side"),
         "reversed": Param("bool", default=False, description="Cut along the normal instead")})
for _n, _d in (("revolve", "Revolve a sketch's profile into solid around an axis"),
               ("groove", "Revolve a sketch's profile around an axis and cut it out of the solid")):
    part_op(_n, "part_feature", _d,
            {"sketch": Param("string", required=True, description="Sketch " + REF),
             "axis": Param("string", default="V", description="'V' / 'H' (the sketch's vertical / horizontal "
                           "axis), 'X'|'Y'|'Z' (origin axes) or 'sketch_edge:<i>' (a line of the sketch)"),
             "angle": Param("dim", default=360, description="Degrees"),
             "symmetric": Param("bool", default=False, description="Revolve half to each side"),
             "reversed": Param("bool", default=False, description="Revolve the other way")})
part_op("hole", "part_feature",
        "Drill a hole at every circle centre of a sketch, into the solid against the sketch normal (sketch on the "
        "face you drill from). Optional counterbore/countersink and ISO metric thread",
        {"sketch": Param("string", required=True, description="Sketch with circles " + REF),
         "diameter": Param("dim", description="Hole diameter (not with thread)"),
         "depth": Param("dim", description="Depth (or through_all)"),
         "through_all": Param("bool", default=False, description="Through the whole solid"),
         "thread": Param("string", description="ISO metric size such as 'M8' (diameter then follows the "
                         "standard tap drill)"),
         "model_thread": Param("bool", default=False, description="Model the thread geometry (slow)"),
         "counterbore": Param("object", description="{diameter, depth}"),
         "countersink": Param("object", description="{diameter, angle (default 90)}"),
         "drill_point": Param("enum", enum=["flat", "angled"], default="flat", description="Blind hole bottom"),
         "reversed": Param("bool", default=False, description="Drill along the normal instead")})
part_op("fillet", "part_feature", "Round edges of the solid",
        {"edges": Param("any", required=True, description=EDGES),
         "radius": Param("dim", required=True, description="Fillet radius")})
part_op("chamfer", "part_feature", "Bevel edges of the solid",
        {"edges": Param("any", required=True, description=EDGES),
         "size": Param("dim", required=True, description="Chamfer distance"),
         "size2": Param("dim", description="Second distance (unequal chamfer)"),
         "angle": Param("dim", description="Angle in degrees (distance-and-angle chamfer)")})
part_op("thickness", "part_feature", "Shell the solid: remove the selected faces and keep walls of a thickness",
        {"faces": Param("any", required=True, description=FACES + " (the faces to open)"),
         "thickness": Param("dim", required=True, description="Wall thickness"),
         "outward": Param("bool", default=False, description="Grow walls outward instead of inward"),
         "join": Param("enum", enum=["arc", "intersection"], default="arc", description="Corner style")})
part_op("linear_pattern", "part_feature", "Repeat features along an axis",
        {"features": Param("list", required=True, description="Features to repeat, each a " + REF),
         "direction": Param("string", default="X", description="'X'|'Y'|'Z'"),
         "length": Param("dim", description="Distance from the first to the last copy (or spacing)"),
         "spacing": Param("dim", description="Distance between neighbouring copies (or length)"),
         "occurrences": Param("dim", required=True, description="Number of copies including the original (>= 2)"),
         "reversed": Param("bool", default=False, description="Repeat in the negative direction")})
part_op("polar_pattern", "part_feature", "Repeat features around an axis",
        {"features": Param("list", required=True, description="Features to repeat, each a " + REF),
         "axis": Param("string", default="Z", description="'X'|'Y'|'Z' (through the origin)"),
         "angle": Param("dim", default=360, description="Total angle in degrees (360 = evenly around)"),
         "occurrences": Param("dim", required=True, description="Number of copies including the original (>= 2)"),
         "reversed": Param("bool", default=False, description="Repeat clockwise")})
part_op("mirror", "part_feature", "Mirror features across an origin plane",
        {"features": Param("list", required=True, description="Features to mirror, each a " + REF),
         "plane": Param("enum", required=True, enum=["XY", "XZ", "YZ"], description="Mirror plane")})
part_op("primitive", "part_feature",
        "Add (or with subtractive=true cut) a box, cylinder, cone, sphere, torus, prism or wedge",
        {"kind": Param("enum", required=True, enum=["box", "cylinder", "cone", "sphere", "torus", "prism", "wedge"],
                       description="Primitive"),
         "dims": Param("object", description="box {length, width, height}; cylinder {radius, height, angle}; "
                       "cone {radius1, radius2, height}; sphere {radius}; torus {radius1, radius2}; prism {sides, "
                       "circumradius, height}; wedge {xmin, xmax, ymin, ymax, zmin, zmax, x2min, x2max, z2min, "
                       "z2max}"),
         "position": Param("list", description="[x, y, z] of the primitive's origin (box: a corner; cylinder: "
                           "base centre)"),
         "direction": Param("list", description="[x, y, z] the primitive's local Z points along (default +Z)"),
         "subtractive": Param("bool", default=False, description="Cut instead of add")})
part_op("loft", "part_feature", "Loft through two or more sketches (in order)",
        {"sections": Param("list", required=True, description="Sketches, each a " + REF),
         "ruled": Param("bool", default=False, description="Straight faces between sections"),
         "closed": Param("bool", default=False, description="Loop back to the first section"),
         "subtractive": Param("bool", default=False, description="Cut instead of add")})
part_op("sweep", "part_feature", "Sweep a closed profile sketch along a path sketch",
        {"sketch": Param("string", required=True, description="Profile sketch " + REF),
         "path": Param("string", required=True, description="Path sketch (open wire) " + REF),
         "frenet": Param("bool", default=False, description="Frenet orientation (for helical paths)"),
         "subtractive": Param("bool", default=False, description="Cut instead of add")})
part_op("helix", "part_feature", "Sweep a sketch's profile along a helix (springs, threads)",
        {"sketch": Param("string", required=True, description="Profile sketch " + REF),
         "axis": Param("string", default="V", description="'V'|'H' (sketch axes) or 'X'|'Y'|'Z'"),
         "pitch": Param("dim", required=True, description="Rise per turn"),
         "height": Param("dim", required=True, description="Total height"),
         "left_handed": Param("bool", default=False, description="Left-hand helix"),
         "reversed": Param("bool", default=False, description="Grow the other way"),
         "subtractive": Param("bool", default=False, description="Cut instead of add")})
part_op("modify_feature", "part_edit",
        "Change parameters of a feature made by an earlier op (same names as that op, e.g. {length: 12} for a "
        "pad, {shapes: [...]} to redraw a sketch, {edges: ...} for a fillet). Later features follow",
        {"feature": Param("string", required=True, description=REF),
         "set": Param("object", required=True, description="{param: new value}")}, creates=False)
part_op("delete_feature", "part_edit", "Delete a feature (cascade=true also deletes the features that use it)",
        {"feature": Param("string", required=True, description=REF),
         "cascade": Param("bool", default=False, description="Delete dependent features too")}, creates=False)


def prevalidate(ops: list[Any], policy: Any) -> None:
    """Checks that need no FreeCAD: list shape, known ops, allow-list, parameter names, required values, types."""
    if not isinstance(ops, list):
        raise input_error("INVALID_PLAN", "operations must be a list")
    if not ops:
        raise input_error("INVALID_PLAN", "operations is empty")
    if len(ops) > policy.max_ops_per_batch:
        raise policy_error("BUDGET_EXCEEDED", f"{len(ops)} operations exceed the batch limit {policy.max_ops_per_batch}")
    for i, raw in enumerate(ops):
        if not isinstance(raw, dict) or not isinstance(raw.get("op"), str):
            raise input_error("INVALID_OP", f"operations[{i}] must be an object with an 'op' field", op_index=i)
        name = raw["op"]
        if name not in PART_REGISTRY:
            close = difflib.get_close_matches(name, PART_REGISTRY.keys(), n=3)
            raise input_error("UNKNOWN_OP", f"Unknown part operation {name!r}", op_index=i, op=name,
                              hint=f"Did you mean {close}?" if close else
                              "This is a 3D part (.FCStd); list_operations(category='part') lists its operations")
        policy.check_op_allowed(name, i)
        coerce(PART_REGISTRY[name], raw, "mm", i)
