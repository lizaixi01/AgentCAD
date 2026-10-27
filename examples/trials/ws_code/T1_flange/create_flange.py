"""Create and independently validate the flange front view, in millimetres."""
from pathlib import Path
import json
import math

import ezdxf
from ezdxf import units


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "flange.dxf"


def create():
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 3
    doc.header["$LTSCALE"] = 1.0
    doc.header["$INSBASE"] = (0, 0, 0)
    doc.header["$LWDISPLAY"] = True
    # A long dash, gap, short dash, gap; all lengths are in drawing mm.
    if "CENTER" not in doc.linetypes:
        doc.linetypes.new("CENTER", dxfattribs={
            "description": "Center ____ _ ____ _ ____",
            "pattern": [20.0, 12.0, -3.0, 2.0, -3.0],
        })
    else:
        doc.linetypes.get("CENTER").setup_pattern([20.0, 12.0, -3.0, 2.0, -3.0])
    for name, linetype, weight in [
        ("OUTLINE", "CONTINUOUS", 35),
        ("CENTERLINES", "CENTER", 18),
        ("PCD", "CENTER", 18),
        ("DIMENSIONS", "CONTINUOUS", 18),
    ]:
        doc.layers.new(name, dxfattribs={
            "color": 7, "linetype": linetype, "lineweight": weight,
        })
    # Arial supports both the multiplication and diameter Unicode characters.
    doc.styles.new("FLANGE_TEXT", dxfattribs={"font": "arial.ttf"})
    doc.dimstyles.new("FLANGE_DIM", dxfattribs={
        "dimtxsty": "FLANGE_TEXT", "dimtxt": 3.5, "dimasz": 2.5,
        "dimgap": 0.8, "dimdec": 0, "dimtad": 1,
        "dimtih": 1, "dimtoh": 1, "dimtmove": 1,
        "dimtofl": 0, "dimcen": 0, "dimclrd": 0, "dimclre": 0,
        "dimclrt": 0, "dimlunit": 2, "dimlfac": 1,
    })
    msp = doc.modelspace()
    msp.add_circle((0, 0), 75, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), 30, dxfattribs={"layer": "OUTLINE"})
    holes = []
    # Clockwise from twelve o'clock.
    for index in range(6):
        angle = math.radians(90 - 60 * index)
        point = tuple(0.0 if abs(v) < 1e-10 else v for v in
                      (55 * math.cos(angle), 55 * math.sin(angle)))
        holes.append(point)
        msp.add_circle(point, 6, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), 55, dxfattribs={
        "layer": "PCD", "linetype": "CENTER",
    })
    for start, end in [((-85, 0), (85, 0)), ((0, -85), (0, 85))]:
        msp.add_line(start, end, dxfattribs={
            "layer": "CENTERLINES", "linetype": "CENTER",
        })
    for center, radius, angle, location, text in [
        ((0, 0), 75, 135, (-92, 92), "<>"),
        ((0, 0), 30, 225, (-92, -92), "<>"),
        (holes[1], 6, 45, (95, 65), "6\u00d7\u00d812"),
        ((0, 0), 55, 315, (92, -92), "<> PCD"),
    ]:
        dim = msp.add_diameter_dim(
            center=center, radius=radius, angle=angle, location=location,
            text=text, dimstyle="FLANGE_DIM",
            dxfattribs={"layer": "DIMENSIONS"},
        )
        dim.render()
    doc.set_modelspace_vport(height=250, center=(0, 0))
    doc.saveas(OUTPUT)


def verify():
    # Reopen the written file rather than validating the construction objects.
    doc = ezdxf.readfile(OUTPUT)
    assert doc.units == units.MM
    audit = doc.audit()
    assert not audit.errors, str(audit.errors)
    assert not audit.fixes, str(audit.fixes)
    msp = doc.modelspace()
    circles = list(msp.query("CIRCLE"))
    outlines = [c for c in circles if c.dxf.layer == "OUTLINE"]
    assert len(circles) == 9 and len(outlines) == 8
    near = lambda a, b: math.isclose(a, b, rel_tol=0, abs_tol=1e-8)
    for radius in (75, 30):
        found = [c for c in outlines if near(c.dxf.radius, radius)]
        assert len(found) == 1 and found[0].dxf.center.isclose((0, 0, 0))
    holes = [c for c in outlines if near(c.dxf.radius, 6)]
    assert len(holes) == 6
    angles = []
    for hole in holes:
        x, y, z = hole.dxf.center
        assert near(math.hypot(x, y), 55) and near(z, 0)
        angles.append(math.degrees(math.atan2(y, x)) % 360)
    assert any(h.dxf.center.isclose((0, 55, 0)) for h in holes)
    angles.sort()
    gaps = [(angles[(i + 1) % 6] - angles[i]) % 360 for i in range(6)]
    assert all(near(gap, 60) for gap in gaps)
    pitch = [c for c in circles if c.dxf.layer == "PCD"]
    assert len(pitch) == 1 and near(pitch[0].dxf.radius, 55)
    assert pitch[0].dxf.center.isclose((0, 0, 0))
    assert pitch[0].dxf.linetype == "CENTER"
    axes = list(msp.query('LINE[layer=="CENTERLINES"]'))
    assert len(axes) == 2
    endpoints = {(tuple(a.dxf.start), tuple(a.dxf.end)) for a in axes}
    assert endpoints == {
        ((-85., 0., 0.), (85., 0., 0.)),
        ((0., -85., 0.), (0., 85., 0.)),
    }
    assert all(a.dxf.linetype == "CENTER" for a in axes)
    pattern = doc.linetypes.get("CENTER").pattern_tags.compile()
    assert tuple(pattern) == (12.0, 3.0, 2.0, 3.0)
    dims = list(msp.query("DIMENSION"))
    assert len(dims) == 4
    assert all(d.dimtype == 3 for d in dims)
    measures = sorted(d.get_measurement() for d in dims)
    assert all(near(a, b) for a, b in zip(measures, [12, 60, 110, 150]))
    bolt = next(d for d in dims if near(d.get_measurement(), 12))
    assert bolt.dxf.text == "6\u00d7\u00d812"
    assert ((bolt.dxf.defpoint + bolt.dxf.defpoint4) / 2).isclose(holes[1].dxf.center)
    rendered = []
    for dim in dims:
        assert dim.dxf.geometry in doc.blocks
        entities = list(doc.blocks.get(dim.dxf.geometry))
        assert any(e.dxftype() == "LINE" for e in entities)
        text = [e.plain_text() for e in entities if e.dxftype() == "MTEXT"]
        assert len(text) == 1
        rendered.extend(t.replace("%%c", "\u00d8") for t in text)
    assert set(rendered) == {"\u00d8150", "\u00d860", "6\u00d7\u00d812", "\u00d8110 PCD"}, rendered
    report = {
        "file": OUTPUT.name, "units": "mm", "dxf_version": doc.dxfversion,
        "outer_diameter": 150, "bore_diameter": 60,
        "bolt_count": len(holes), "bolt_diameter": 12, "pcd": 110,
        "bolt_centers_clockwise_from_top": [list(h.dxf.center)[:2] for h in holes],
        "angular_gaps_degrees": gaps, "centerline_extents": [-85, 85],
        "center_linetype_pattern": list(pattern), "diameter_measurements": measures,
        "rendered_dimension_text": rendered,
        "audit_errors": len(audit.errors), "audit_fixes": len(audit.fixes),
        "result": "PASS",
    }
    (ROOT / "flange_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    create()
    verify()
