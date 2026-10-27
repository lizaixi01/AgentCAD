"""Create room.dxf in millimetres and independently check the saved drawing."""

import json
import math
from pathlib import Path

import ezdxf
from ezdxf import units


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "room.dxf"


def create_drawing():
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 0
    doc.header["$LTSCALE"] = 1.0
    doc.header["$INSBASE"] = (0, 0, 0)
    doc.linetypes.new(
        "AXIS_DASHDOT",
        dxfattribs={
            "description": "Axis dash-dot, 600 dash / 120 gap / dot / 120 gap",
            "pattern": [840.0, 600.0, -120.0, 0.0, -120.0],
        },
    )
    for name, color, weight, linetype in [
        ("WALL", 7, 35, "CONTINUOUS"),
        ("WINDOW", 4, 18, "CONTINUOUS"),
        ("AXIS", 1, 13, "AXIS_DASHDOT"),
        ("DIM", 3, 18, "CONTINUOUS"),
    ]:
        doc.layers.new(name, dxfattribs={
            "color": color, "lineweight": weight, "linetype": linetype,
        })

    msp = doc.modelspace()

    def line(layer, x1, y1, x2, y2):
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})

    # Mitered outer and inner wall faces; horizontal faces stop at openings.
    for left, right, south, north in [
        (-120, 6120, -120, 4120),
        (120, 5880, 120, 3880),
    ]:
        line("WALL", left, south, left, north)
        line("WALL", right, south, right, north)
        line("WALL", left, south, 2550, south)
        line("WALL", 3450, south, right, south)
        line("WALL", left, north, 2250, north)
        line("WALL", 3750, north, right, north)

    # Four jambs close the cut wall ends across the full 240 mm thickness.
    for x in (2550, 3450):
        line("WALL", x, -120, x, 120)
    for x in (2250, 3750):
        line("WALL", x, 3880, x, 4120)

    # The two window boundary lines and two additional interior parallel lines.
    # Keeping them on WINDOW preserves an actual gap in the WALL layer.
    for y in (3880, 3960, 4040, 4120):
        line("WINDOW", 2250, y, 3750, y)

    for x in (0, 6000):
        line("AXIS", x, -400, x, 4400)
    for y in (0, 4000):
        line("AXIS", -400, y, 6400, y)

    overrides = {
        "dimtxt": 120, "dimasz": 90, "dimexo": 50, "dimexe": 90,
        "dimgap": 40, "dimtad": 1, "dimdec": 0, "dimzin": 8,
        "dimclrd": 0, "dimclre": 0, "dimclrt": 0,
        "dimtxsty": "Standard", "dimtih": 0, "dimtoh": 0,
    }
    specs = [
        ((0, -1150), (0, 0), (6000, 0), 0),
        ((-950, 0), (0, 0), (0, 4000), 90),
        ((0, -550), (2550, -120), (3450, -120), 0),
        ((0, 4650), (2250, 4120), (3750, 4120), 0),
    ]
    for base, p1, p2, angle in specs:
        dim = msp.add_linear_dim(
            base=base, p1=p1, p2=p2, angle=angle,
            dimstyle="Standard", override=overrides,
            dxfattribs={"layer": "DIM"},
        )
        dim.render()

    # Set an initial view containing the dimensions as well as the plan.
    doc.set_modelspace_vport(height=6800, center=(2700, 1800))
    doc.saveas(OUTPUT)


def verify_saved_drawing():
    # Read from disk: all checks below use persisted entities, not creation state.
    doc = ezdxf.readfile(OUTPUT)
    msp = doc.modelspace()
    assert doc.units == units.MM
    assert tuple(doc.header["$INSBASE"]) == (0, 0, 0)

    def point(v):
        assert abs(v.z) < 1e-9
        return (round(v.x, 6), round(v.y, 6))

    def segment(a, b):
        return tuple(sorted((a, b)))

    def segments(layer):
        entities = list(msp.query(f'LINE[layer=="{layer}"]'))
        result = [segment(point(e.dxf.start), point(e.dxf.end)) for e in entities]
        assert len(result) == len(set(result)), f"Duplicate lines on {layer}"
        return set(result)

    wall = segments("WALL")
    # Independent explicit inventory also catches missing, extra or unsplit faces.
    expected_wall = {
        segment((-120, -120), (-120, 4120)),
        segment((6120, -120), (6120, 4120)),
        segment((120, 120), (120, 3880)),
        segment((5880, 120), (5880, 3880)),
        segment((-120, -120), (2550, -120)),
        segment((3450, -120), (6120, -120)),
        segment((120, 120), (2550, 120)),
        segment((3450, 120), (5880, 120)),
        segment((-120, 4120), (2250, 4120)),
        segment((3750, 4120), (6120, 4120)),
        segment((120, 3880), (2250, 3880)),
        segment((3750, 3880), (5880, 3880)),
        segment((2550, -120), (2550, 120)),
        segment((3450, -120), (3450, 120)),
        segment((2250, 3880), (2250, 4120)),
        segment((3750, 3880), (3750, 4120)),
    }
    assert wall == expected_wall, "Wall boundaries or jambs differ"
    assert segments("WINDOW") == {
        segment((2250, y), (3750, y)) for y in (3880, 3960, 4040, 4120)
    }
    assert segments("AXIS") == {
        segment((0, -400), (0, 4400)),
        segment((6000, -400), (6000, 4400)),
        segment((-400, 0), (6400, 0)),
        segment((-400, 4000), (6400, 4000)),
    }
    assert doc.layers.get("AXIS").dxf.linetype == "AXIS_DASHDOT"
    # Raw DXF group 49 retains negative gaps; compile() normalizes their signs.
    pattern = doc.linetypes.get("AXIS_DASHDOT").pattern_tags
    assert [tag.value for tag in pattern.tags if tag.code == 49] == [
        600.0, -120.0, 0.0, -120.0,
    ]

    # Verify each dimension's endpoints, measured value, and rendered label.
    expected_dims = {
        segment((0, 0), (6000, 0)): 6000,
        segment((0, 0), (0, 4000)): 4000,
        segment((2550, -120), (3450, -120)): 900,
        segment((2250, 4120), (3750, 4120)): 1500,
    }
    dimensions = list(msp.query("DIMENSION"))
    assert len(dimensions) == 4
    labels = []
    for dim in dimensions:
        assert dim.dxf.layer == "DIM"
        key = segment(point(dim.dxf.defpoint2), point(dim.dxf.defpoint3))
        expected = expected_dims.pop(key)
        assert math.isclose(dim.get_measurement(), expected, abs_tol=1e-6)
        assert dim.dxf.text in ("", "<>")
        block = doc.blocks.get(dim.dxf.geometry)
        texts = [e.dxf.text for e in block.query("MTEXT TEXT")]
        assert str(expected) in texts, (expected, texts)
        assert len(block) > 0
        labels.append(expected)
    assert not expected_dims

    audit = doc.audit()
    assert not audit.has_errors, [str(e) for e in audit.errors]
    assert not audit.has_fixes, [str(e) for e in audit.fixes]
    result = {
        "file": OUTPUT.name,
        "units": "mm",
        "axis_rectangle": {"lower_left": [0, 0], "width": 6000, "height": 4000},
        "wall_thickness": 240,
        "axis_to_wall_face": 120,
        "outer_bounds": [-120, -120, 6120, 4120],
        "inner_bounds": [120, 120, 5880, 3880],
        "door": {"x_range": [2550, 3450], "width": 900, "center_x": 3000},
        "window": {"x_range": [2250, 3750], "width": 1500, "center_x": 3000,
                   "line_y_values": [3880, 3960, 4040, 4120]},
        "entity_counts": {"WALL": len(wall), "WINDOW": 4, "AXIS": 4, "DIMENSION": 4},
        "rendered_dimension_labels": sorted(labels),
        "audit_errors": len(audit.errors),
        "audit_fixes": len(audit.fixes),
        "all_checks_passed": True,
    }
    (ROOT / "room_check.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    create_drawing()
    verify_saved_drawing()
