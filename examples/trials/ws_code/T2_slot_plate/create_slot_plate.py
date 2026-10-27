"""Generate and independently check the dimensioned mounting plate (mm)."""
import json
import math
from pathlib import Path

import ezdxf
from ezdxf import bbox, units


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "slot_plate.dxf"
doc = ezdxf.new("R2010", setup=True)
doc.units = units.MM
doc.header["$MEASUREMENT"] = 1
doc.header["$LUNITS"] = 2
doc.header["$LUPREC"] = 2
doc.header["$INSBASE"] = (0, 0, 0)
doc.layers.new("OUTLINE", dxfattribs={"color": 7, "lineweight": 35})
doc.layers.new("HOLES", dxfattribs={"color": 7, "lineweight": 35})
doc.layers.new("DIMENSIONS", dxfattribs={"color": 2, "lineweight": 18})
doc.linetypes.new("CENTER_PLATE", dxfattribs={
    "description": "Center line", "pattern": [16.0, 10.0, -2.0, 2.0, -2.0]})
doc.layers.new("CENTER", dxfattribs={
    "color": 4, "linetype": "CENTER_PLATE", "lineweight": 13})
doc.dimstyles.new("PLATE_MM", dxfattribs={
    "dimtxt": 3.5, "dimasz": 2.5, "dimgap": 1.0,
    "dimexo": 1.5, "dimexe": 2.0, "dimtad": 1,
    "dimdec": 0, "dimzin": 8, "dimlunit": 2,
    "dimclrd": 2, "dimclre": 2, "dimclrt": 2,
    "dimtxsty": "Standard", "dimlfac": 1.0, "dimscale": 1.0,
})
msp = doc.modelspace()
quarter_bulge = math.tan(math.pi / 8)
msp.add_lwpolyline([
    (8, 0, 0), (152, 0, quarter_bulge),
    (160, 8, 0), (160, 92, quarter_bulge),
    (152, 100, 0), (8, 100, quarter_bulge),
    (0, 92, 0), (0, 8, quarter_bulge),
], format="xyb", close=True, dxfattribs={"layer": "OUTLINE"})

for cx in (40, 120):
    msp.add_lwpolyline([
        (cx - 10, 45, 0), (cx + 10, 45, 1),
        (cx + 10, 55, 0), (cx - 10, 55, 1),
    ], format="xyb", close=True, dxfattribs={"layer": "HOLES"})
    msp.add_line((cx - 18, 50), (cx + 18, 50),
                 dxfattribs={"layer": "CENTER"})
    msp.add_line((cx, 40), (cx, 60), dxfattribs={"layer": "CENTER"})

msp.add_circle((80, 50), 10, dxfattribs={"layer": "HOLES"})
msp.add_line((66, 50), (94, 50), dxfattribs={"layer": "CENTER"})
msp.add_line((80, 36), (80, 64), dxfattribs={"layer": "CENTER"})

def linear(p1, p2, base, angle=0):
    dim = msp.add_linear_dim(
        base=base, p1=p1, p2=p2, angle=angle,
        dimstyle="PLATE_MM", dxfattribs={"layer": "DIMENSIONS"})
    dim.render()


linear((0, 8), (160, 8), (0, -18))
linear((152, 0), (152, 100), (180, 0), 90)
linear((25, 50), (55, 50), (25, 26))
linear((30, 45), (30, 55), (17, 45), 90)
linear((40, 50), (120, 50), (40, 120))
radius_dim = msp.add_radius_dim(
    center=(8, 92), radius=8, angle=135, location=(-14, 114),
    dimstyle="PLATE_MM", dxfattribs={"layer": "DIMENSIONS"})
radius_dim.render()
diameter_dim = msp.add_diameter_dim(
    center=(80, 50), radius=10, angle=55, location=(99, 77),
    dimstyle="PLATE_MM", dxfattribs={"layer": "DIMENSIONS"})
diameter_dim.render()
doc.set_modelspace_vport(height=170, center=(80, 52))
doc.saveas(TARGET)

# Reopen the on-disk file and verify actual entities and rendered dimensions.
check = ezdxf.readfile(TARGET)
audit = check.audit()
assert not audit.errors, str(audit.errors)
assert not audit.fixes, str(audit.fixes)
assert check.units == units.MM
space = check.modelspace()


def near(a, b):
    assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-7), (a, b)


def extents(entities):
    box = bbox.extents(entities)
    return tuple(box.extmin)[:2], tuple(box.extmax)[:2]


outline, = list(space.query('LWPOLYLINE[layer=="OUTLINE"]'))
assert outline.closed
for actual, expected in zip(extents([outline]), ((0.0, 0.0), (160.0, 100.0))):
    for coordinate, target in zip(actual, expected):
        near(coordinate, target)
outer_parts = list(outline.virtual_entities())
outer_arcs = [e for e in outer_parts if e.dxftype() == "ARC"]
assert len(outer_arcs) == 4
assert len([e for e in outer_parts if e.dxftype() == "LINE"]) == 4
for arc, expected in zip(outer_arcs, [(152, 8), (152, 92), (8, 92), (8, 8)]):
    near(arc.dxf.radius, 8)
    near(arc.dxf.center.x, expected[0])
    near(arc.dxf.center.y, expected[1])
    near((arc.dxf.end_angle - arc.dxf.start_angle) % 360, 90)

slots = sorted(space.query('LWPOLYLINE[layer=="HOLES"]'),
               key=lambda e: e.get_points()[0][0])
assert len(slots) == 2
slot_results = []
for slot, cx in zip(slots, (40, 120)):
    assert slot.closed
    low, high = extents([slot])
    near(low[0], cx - 15)
    near(high[0], cx + 15)
    near(low[1], 45)
    near(high[1], 55)
    parts = list(slot.virtual_entities())
    arcs = [e for e in parts if e.dxftype() == "ARC"]
    lines = [e for e in parts if e.dxftype() == "LINE"]
    assert len(arcs) == len(lines) == 2
    for arc in arcs:
        near(arc.dxf.radius, 5)
        near(arc.dxf.center.y, 50)
        near((arc.dxf.end_angle - arc.dxf.start_angle) % 360, 180)
    for line in lines:
        near((line.dxf.end - line.dxf.start).magnitude, 20)
        near(line.dxf.start.y, line.dxf.end.y)
    slot_results.append({"center": [cx, 50], "length": 30, "width": 10})

hole, = list(space.query("CIRCLE"))
near(hole.dxf.center.x, 80)
near(hole.dxf.center.y, 50)
near(hole.dxf.radius, 10)
dims = list(space.query("DIMENSION"))
assert len(dims) == 7
dim_results = []
for dim in dims:
    measurement = dim.get_measurement()
    assert isinstance(measurement, (int, float)), measurement
    assert dim.dxf.geometry in check.blocks
    block_entities = list(check.blocks[dim.dxf.geometry])
    assert block_entities
    texts = [e.dxf.text for e in block_entities if e.dxftype() in ("TEXT", "MTEXT")]
    assert texts
    dim_results.append({"type": dim.dimtype, "value": measurement,
                        "rendered_text": texts})
for result, expected_type, expected_value in zip(
        dim_results, [0, 0, 0, 0, 0, 4, 3], [160, 100, 30, 10, 80, 8, 20]):
    assert result["type"] == expected_type, result
    near(result["value"], expected_value)

report = {
    "file": TARGET.name, "units": "mm", "audit_errors": 0, "audit_fixes": 0,
    "outline_bounds": [[0, 0], [160, 100]], "corner_radii": [8] * 4,
    "slots": slot_results, "slot_center_distance": 80,
    "center_hole": {"center": [80, 50], "diameter": 20},
    "dimensions": dim_results,
}
(ROOT / "slot_plate_check.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
