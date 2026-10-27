"""Generate and independently re-read flange front views (mm); ezdxf only.

Run without arguments to generate and verify; --check only verifies existing DXFs.
All inputs and outputs live beside this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

ROOT = Path(__file__).resolve().parent
TOL = 1e-7


@dataclass(frozen=True)
class Flange:
    part: str
    outer: float
    bore: float
    pitch: float
    count: int
    hole: float
    material: str

    def margins(self):
        return {
            "outer_edge_clearance_mm": (self.outer - self.pitch - self.hole) / 2,
            "bore_edge_clearance_mm": (self.pitch - self.bore - self.hole) / 2,
            "adjacent_center_distance_mm": self.pitch * math.sin(math.pi / self.count),
            "adjacent_edge_clearance_mm": self.pitch * math.sin(math.pi / self.count) - self.hole,
        }

    def invalid_reasons(self):
        reasons = []
        if min(self.outer, self.bore, self.pitch, self.hole) <= 0 or self.count < 2:
            return ["直径必须为正数，孔数至少为 2"]
        if self.bore >= self.outer:
            reasons.append("中心孔直径不小于外径")
        m = self.margins()
        if m["outer_edge_clearance_mm"] <= TOL:
            reasons.append(f"螺栓孔超出或接触外圆，外缘余量 {m['outer_edge_clearance_mm']:.6f} mm")
        if m["bore_edge_clearance_mm"] <= TOL:
            reasons.append(f"螺栓孔接触或侵入中心孔，间隙 {m['bore_edge_clearance_mm']:.6f} mm")
        if m["adjacent_edge_clearance_mm"] <= TOL:
            reasons.append(
                f"相邻螺栓孔重叠或相切，中心距 {m['adjacent_center_distance_mm']:.6f} mm，孔径 {self.hole:g} mm"
            )
        return reasons


def load_parts():
    with (ROOT / "flanges.csv").open(encoding="utf-8-sig", newline="") as stream:
        return [Flange(r["零件号"], *(float(r[k]) for k in ("外径", "中心孔", "节圆")),
                       int(r["孔数"]), float(r["孔径"]), r["材料"]) for r in csv.DictReader(stream)]


def polar(radius, degrees):
    a = math.radians(degrees)
    return radius * math.cos(a), radius * math.sin(a)


def gap_angle(part, target):
    """Route the bore/pitch leaders through a gap between bolt holes."""
    choices = [(90 + (i + 0.5) * 360 / part.count) % 360 for i in range(part.count)]
    return min(choices, key=lambda a: abs((a - target + 180) % 360 - 180))


def generate(part):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 3
    doc.header["$LTSCALE"] = 1.0
    doc.header["$CELTSCALE"] = 1.0
    doc.header["$DIMASSOC"] = 1
    if "CENTER" not in doc.linetypes:
        doc.linetypes.new("CENTER", dxfattribs={
            "description": "Center ____ _ ____ _ ____", "pattern": [20.0, 12.0, -3.0, 2.0, -3.0]})
    # Replace setup=True's short default pattern with a metric 20 mm pattern.
    doc.linetypes.get("CENTER").setup_pattern([20.0, 12.0, -3.0, 2.0, -3.0])
    for name, weight, linetype in (
        ("OUTER", 35, "Continuous"), ("BORE", 35, "Continuous"),
        ("HOLES", 25, "Continuous"), ("PITCH", 13, "CENTER"),
        ("AXES", 13, "CENTER"), ("DIMENSIONS", 18, "Continuous"),
        ("NOTES", 25, "Continuous"),
    ):
        doc.layers.new(name, dxfattribs={"color": 7, "lineweight": weight, "linetype": linetype})
    # A real Windows Chinese font; DXF stores the font name, not an embedded font.
    doc.styles.new("CN", dxfattribs={"font": "simhei.ttf"})
    doc.dimstyles.new("FLANGE_MM", dxfattribs={
        "dimtxsty": "CN", "dimtxt": 3.5, "dimasz": 2.5, "dimgap": 1.0,
        "dimdec": 0, "dimtad": 1, "dimtih": 1, "dimtoh": 1,
        "dimtmove": 1, "dimcen": 0, "dimclrd": 0, "dimclre": 0, "dimclrt": 0,
    })
    doc.appids.new("FLANGE_QA")
    msp = doc.modelspace()
    radius = part.outer / 2
    msp.add_circle((0, 0), radius, dxfattribs={"layer": "OUTER"})
    msp.add_circle((0, 0), part.bore / 2, dxfattribs={"layer": "BORE"})
    msp.add_circle((0, 0), part.pitch / 2,
                   dxfattribs={"layer": "PITCH", "linetype": "CENTER"})
    # Counterclockwise numbering, first hole exactly on +Y.
    for i in range(part.count):
        p = (0.0, part.pitch / 2) if i == 0 else polar(part.pitch / 2, 90 + i * 360 / part.count)
        circle = msp.add_circle(p, part.hole / 2, dxfattribs={"layer": "HOLES"})
        circle.set_xdata("FLANGE_QA", [(1000, f"HOLE_{i + 1}")])
    extent = radius + 8
    for a, b in (((-extent, 0), (extent, 0)), ((0, -extent), (0, extent))):
        msp.add_line(a, b, dxfattribs={"layer": "AXES", "linetype": "CENTER"})

    def diameter(role, center, r, location, label):
        dim = msp.add_diameter_dim(center=center, radius=r, location=location,
                                   text=label, dimstyle="FLANGE_MM",
                                   dxfattribs={"layer": "DIMENSIONS"})
        dim.dimension.set_xdata("FLANGE_QA", [(1000, role)])
        dim.render()

    diameter("OUTER", (0, 0), radius, polar(radius + 42, 145), f"%%c{part.outer:g}")
    diameter("PITCH", (0, 0), part.pitch / 2,
             polar(radius + 42, gap_angle(part, 225)), f"%%c{part.pitch:g}")
    diameter("BORE", (0, 0), part.bore / 2,
             polar(radius + 42, gap_angle(part, 315)), f"%%c{part.bore:g}")
    # Native diameter dimension on the top bolt hole, with the required group callout.
    diameter("BOLT_GROUP", (0, part.pitch / 2), part.hole / 2,
             (radius + 35, radius + 20), f"{part.count}×%%c{part.hole:g}")
    msp.add_text(f"{part.part}  材料 {part.material}", dxfattribs={
        "layer": "NOTES", "style": "CN", "height": 5,
    }).set_placement((0, -radius - 57), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.set_modelspace_vport(height=2 * radius + 140, center=(0, -12))
    doc.saveas(ROOT / f"{part.part}.dxf")


def close(actual, expected, label):
    assert math.isclose(actual, expected, abs_tol=TOL, rel_tol=0), f"{label}: {actual} != {expected}"


def verify(part):
    """Checks are based on entities read back from disk, including all hole pairs."""
    path = ROOT / f"{part.part}.dxf"
    doc = ezdxf.readfile(path)
    audit = doc.audit()
    assert not audit.errors and not audit.fixes, f"DXF audit: {audit.errors}, {audit.fixes}"
    assert doc.units == ezdxf.units.MM
    msp = doc.modelspace()
    circles = list(msp.query("CIRCLE"))
    assert len(circles) == part.count + 3
    for layer, diameter in (("OUTER", part.outer), ("BORE", part.bore), ("PITCH", part.pitch)):
        found = [c for c in circles if c.dxf.layer == layer]
        assert len(found) == 1
        close(found[0].dxf.center.magnitude, 0, f"{layer} center")
        close(found[0].dxf.radius * 2, diameter, f"{layer} diameter")
    holes = [c for c in circles if c.dxf.layer == "HOLES"]
    assert len(holes) == part.count
    centers = [c.dxf.center for c in holes]
    angles = []
    for c in holes:
        close(c.dxf.radius * 2, part.hole, "hole diameter")
        close(c.dxf.center.z, 0, "hole plane")
        close(c.dxf.center.magnitude, part.pitch / 2, "pitch radius")
        angles.append(math.atan2(c.dxf.center.y, c.dxf.center.x) % math.tau)
        assert c.dxf.center.magnitude + c.dxf.radius < part.outer / 2 - TOL
        assert c.dxf.center.magnitude - c.dxf.radius > part.bore / 2 + TOL
    assert any(p.isclose((0, part.pitch / 2, 0), abs_tol=TOL) for p in centers)
    angles.sort()
    for i in range(part.count):
        close((angles[(i + 1) % part.count] - angles[i]) % math.tau,
              math.tau / part.count, "angular spacing")
    distances = [centers[i].distance(centers[j])
                 for i in range(part.count) for j in range(i + 1, part.count)]
    assert min(distances) > part.hole + TOL
    close(min(distances), part.pitch * math.sin(math.pi / part.count), "minimum hole distance")
    # compile() discards gap signs; the original DXF group-49 values retain them.
    center_pattern = [tag.value for tag in doc.linetypes.get("CENTER").pattern_tags.tags if tag.code == 49]
    assert any(p < 0 for p in center_pattern), "CENTER must contain gaps"
    assert len({p for p in center_pattern if p > 0}) >= 2, "CENTER needs long and short strokes"
    for e in [*msp.query('CIRCLE[layer=="PITCH"]'), *msp.query('LINE[layer=="AXES"]')]:
        assert e.dxf.linetype == "CENTER"
    axes = list(msp.query('LINE[layer=="AXES"]'))
    assert len(axes) == 2
    assert any(abs(a.dxf.start.y) < TOL and abs(a.dxf.end.y) < TOL and a.dxf.start.x < 0 < a.dxf.end.x for a in axes)
    assert any(abs(a.dxf.start.x) < TOL and abs(a.dxf.end.x) < TOL and a.dxf.start.y < 0 < a.dxf.end.y for a in axes)
    dimensions = list(msp.query("DIMENSION"))
    assert len(dimensions) == 4
    expected = {"OUTER": (part.outer, (0, 0, 0), f"%%c{part.outer:g}"),
                "BORE": (part.bore, (0, 0, 0), f"%%c{part.bore:g}"),
                "PITCH": (part.pitch, (0, 0, 0), f"%%c{part.pitch:g}"),
                "BOLT_GROUP": (part.hole, (0, part.pitch / 2, 0), f"{part.count}×%%c{part.hole:g}")}
    roles = []
    for dim in dimensions:
        role = dim.get_xdata("FLANGE_QA")[0].value
        roles.append(role)
        value, center, text = expected[role]
        assert dim.dimtype == 3, "must be a native diameter DIMENSION"
        close(dim.get_measurement(), value, f"{role} dimension measurement")
        assert dim.dxf.defpoint.lerp(dim.dxf.defpoint4).isclose(center, abs_tol=TOL)
        assert dim.dxf.text == text
        block = doc.blocks.get(dim.dxf.geometry)
        assert len(block) > 0 and any(e.dxftype() in ("TEXT", "MTEXT") for e in block)
        rendered_text = " ".join(e.dxf.text for e in block if e.dxftype() == "MTEXT")
        assert text in rendered_text, f"rendered dimension text: {role}"
    assert set(roles) == set(expected)
    notes = list(msp.query('TEXT[layer=="NOTES"]'))
    assert len(notes) == 1 and notes[0].dxf.text == f"{part.part}  材料 {part.material}"
    assert notes[0].dxf.align_point.y < -part.outer / 2
    assert doc.styles.get("CN").dxf.font == "simhei.ttf"
    return {"part": part.part, "file": path.name, "status": "PASS", "outer_mm": part.outer,
            "bore_mm": part.bore, "pitch_mm": part.pitch, "hole_count": part.count,
            "hole_diameter_mm": part.hole, "angular_spacing_deg": 360 / part.count,
            "first_hole_center_mm": [0, part.pitch / 2], "native_diameter_dimensions": 4,
            "audit_errors": len(audit.errors), "audit_fixes": len(audit.fixes), **part.margins()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    parts = load_parts()
    valid, invalid = [], []
    for part in parts:
        reasons = part.invalid_reasons()
        if reasons:
            assert not (ROOT / f"{part.part}.dxf").exists(), f"Invalid part has a pre-existing DXF: {part.part}"
            invalid.append({"part": part.part, "reasons": reasons, **part.margins()})
        else:
            if not args.check:
                generate(part)
            valid.append(verify(part))
    report = {"units": "mm", "ezdxf_version": ezdxf.__version__,
              "input_count": len(parts), "generated_count": len(valid), "skipped_count": len(invalid),
              "verification": "All generated DXFs re-read and verified; all hole pairs checked.",
              "valid": valid, "skipped": invalid}
    (ROOT / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
