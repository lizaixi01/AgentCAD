"""Create and independently validate the dimensioned stepped shaft (mm)."""
import json
from pathlib import Path

import ezdxf
from ezdxf import units


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "shaft.dxf"

# Longitudinal section outline of the outside surface; each end has C2.
PROFILE = [
    (0, -13), (2, -15), (50, -15), (50, -20),
    (130, -20), (130, -15), (198, -15), (200, -13),
    (200, 13), (198, 15), (130, 15), (130, 20),
    (50, 20), (50, 15), (2, 15), (0, 13),
]


def build():
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 0
    doc.header["$LTSCALE"] = 1.0
    doc.header["$LWDISPLAY"] = True
    if "CENTER" not in doc.linetypes:
        doc.linetypes.new(
            "CENTER", dxfattribs={
                "description": "Center ____ _ ____ _ ____",
                "pattern": [25.0, 16.0, -3.0, 3.0, -3.0],
            },
        )
    doc.layers.new("OUTLINE", dxfattribs={"color": 7, "lineweight": 50})
    doc.layers.new("CENTERLINE", dxfattribs={
        "color": 7, "linetype": "CENTER", "lineweight": 18,
    })
    doc.layers.new("DIMENSIONS", dxfattribs={"color": 7, "lineweight": 18})
    doc.layers.new("NOTES", dxfattribs={"color": 7, "lineweight": 18})
    msp = doc.modelspace()
    msp.add_lwpolyline(PROFILE, close=True, dxfattribs={"layer": "OUTLINE"})
    msp.add_line((-8, 0), (208, 0), dxfattribs={
        "layer": "CENTERLINE", "linetype": "CENTER",
    })

    style = {
        "dimtxt": 3.0, "dimasz": 2.5, "dimgap": 0.8,
        "dimexo": 1.0, "dimexe": 1.5, "dimtad": 1,
        "dimdec": 0, "dimzin": 8, "dimtih": 0, "dimtoh": 0,
        "dimlfac": 1.0,
        "dimclrd": 7, "dimclre": 7, "dimclrt": 7,
        "dimlwd": 18, "dimlwe": 18,
    }

    def linear(p1, p2, base, angle=0, text="<>"):
        dim = msp.add_linear_dim(
            base=base, p1=p1, p2=p2, angle=angle,
            text=text, dimstyle="EZDXF", override=style,
            dxfattribs={"layer": "DIMENSIONS"},
        )
        dim.render()

    # Chain lengths measure theoretical end planes, including the chamfers.
    linear((0, -13), (50, -20), (0, -32))
    linear((50, -20), (130, -20), (50, -32))
    linear((130, -20), (200, -13), (130, -32))
    linear((0, -13), (200, -13), (0, -45))

    # Diameter callouts on the longitudinal view use the diameter prefix.
    for x, radius in [(25, 15), (90, 20), (165, 15)]:
        linear((x, -radius), (x, radius), (x, 0), angle=90, text="%%c<>")

    # Leader arrows identify the upper representative edge of each end chamfer.
    for tip, elbow, end, label_at in [
        ((1, 14), (-7, 29), (22, 29), (-7, 30)),
        ((199, 14), (207, 29), (236, 29), (207, 30)),
    ]:
        msp.add_leader(
            [tip, elbow, end], dimstyle="EZDXF",
            override={"dimasz": 2.0}, dxfattribs={"layer": "NOTES"},
        )
        msp.add_text("C2 (2x45%%d)", dxfattribs={
            "height": 3.0, "insert": label_at, "layer": "NOTES",
        })
    doc.set_modelspace_vport(height=110, center=(108, -5))
    doc.saveas(OUTPUT)


def validate():
    # Read the saved artifact, rather than checking the in-memory drawing.
    doc = ezdxf.readfile(OUTPUT)
    msp = doc.modelspace()
    audit = doc.audit()
    assert not audit.errors, f"DXF audit errors: {audit.errors}"
    assert not audit.fixes, f"DXF audit repairs: {audit.fixes}"
    assert doc.units == units.MM
    outlines = list(msp.query('LWPOLYLINE[layer=="OUTLINE"]'))
    assert len(outlines) == 1 and outlines[0].closed
    points = list(outlines[0].get_points("xy"))
    assert points == PROFILE
    assert min(x for x, y in points) == 0
    assert max(x for x, y in points) == 200
    segments = list(zip(points, points[1:] + points[:1]))
    chamfers = []
    for (x1, y1), (x2, y2) in segments:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx and dy:
            assert dx == dy == 2
            chamfers.append(((x1, y1), (x2, y2)))
    assert len(chamfers) == 4
    for x in (0, 200):
        end_face = [p for p in points if p[0] == x]
        assert len(end_face) == 2 and sum(y for _, y in end_face) == 0

    # Intersect the saved outline at representative axial positions.
    diameters = []
    for x in (25, 90, 165):
        ys = []
        for (x1, y1), (x2, y2) in segments:
            if min(x1, x2) < x < max(x1, x2):
                ys.append(y1 + (y2 - y1) * (x - x1) / (x2 - x1))
        assert len(ys) == 2
        diameters.append(max(ys) - min(ys))
    assert diameters == [30, 40, 30]
    shoulder_x = sorted({x1 for (x1, y1), (x2, y2) in segments
                         if x1 == x2 and x1 not in (0, 200)})
    assert shoulder_x == [50, 130]
    lengths = [shoulder_x[0], shoulder_x[1] - shoulder_x[0], 200 - shoulder_x[1]]
    assert lengths == [50, 80, 70]

    dimensions = list(msp.query("DIMENSION"))
    assert len(dimensions) == 7
    measured_lengths = sorted(round(d.get_measurement(), 8) for d in dimensions
                              if d.dxf.text == "<>")
    measured_diameters = sorted(round(d.get_measurement(), 8) for d in dimensions
                                if d.dxf.text == "%%c<>")
    assert measured_lengths == [50, 70, 80, 200]
    assert measured_diameters == [30, 30, 40]
    rendered_labels = []
    for dim in dimensions:
        assert dim.dxf.geometry in doc.blocks
        block = doc.blocks[dim.dxf.geometry]
        assert len(block) > 0
        assert any(entity.dxftype() in ("TEXT", "MTEXT") for entity in block)
        rendered_labels.extend(entity.dxf.text for entity in block
                               if entity.dxftype() in ("TEXT", "MTEXT"))
    assert rendered_labels == ["50", "80", "70", "200", "%%c30", "%%c40", "%%c30"], rendered_labels
    centerlines = list(msp.query('LINE[layer=="CENTERLINE"]'))
    assert len(centerlines) == 1
    center = centerlines[0]
    assert center.dxf.linetype == "CENTER"
    assert tuple(center.dxf.start) == (-8, 0, 0)
    assert tuple(center.dxf.end) == (208, 0, 0)
    assert "CENTER" in doc.linetypes
    notes = list(msp.query('TEXT[layer=="NOTES"]'))
    assert len(notes) == 2 and all(n.dxf.text == "C2 (2x45%%d)" for n in notes)
    report = {
        "file": OUTPUT.name, "units": "mm", "audit_errors": len(audit.errors),
        "audit_repairs": len(audit.fixes), "closed_outline": True,
        "left_end_face_center": [0, 0], "diameters": diameters,
        "segment_lengths": lengths, "total_length": 200,
        "shoulder_positions": shoulder_x, "chamfer_edges": len(chamfers),
        "chamfer_axial_and_radial_size": 2, "chamfer_angle_degrees": 45,
        "centerline": {"linetype": "CENTER", "start": [-8, 0], "end": [208, 0]},
        "dimension_entities": len(dimensions), "rendered_dimension_blocks": True,
        "rendered_dimension_labels": rendered_labels,
    }
    (ROOT / "shaft_check.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    build()
    validate()
