"""Generate and independently re-read flange DXFs; ezdxf + standard library only."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

import ezdxf
from ezdxf import units
from ezdxf.enums import TextEntityAlignment


ROOT = Path(__file__).resolve().parent
TABLE = """零件号,外径,中心孔,节圆,孔数,孔径,材料
FL-101,150,60,110,6,12,Q235
FL-102,180,75,135,8,14,Q235
FL-103,120,40,90,4,11,45钢
FL-104,200,90,160,8,18,Q345
FL-105,160,60,120,6,14,Q235
FL-106,100,30,70,4,9,304不锈钢
FL-107,220,110,180,12,14,Q235
FL-108,140,50,105,6,11,45钢
FL-109,130,60,118,6,14,Q235
FL-110,250,120,200,16,18,Q345
FL-111,90,40,66,16,14,Q235
FL-112,170,80,130,8,13,304不锈钢
"""
TOL = 1e-7


def rows():
    for raw in csv.DictReader(io.StringIO(TABLE)):
        yield {
            "id": raw["零件号"], "D": float(raw["外径"]),
            "B": float(raw["中心孔"]), "P": float(raw["节圆"]),
            "n": int(raw["孔数"]), "d": float(raw["孔径"]),
            "material": raw["材料"],
        }


def clearances(p):
    return {
        "outer_edge_mm": (p["D"] - p["P"] - p["d"]) / 2,
        "center_hole_mm": (p["P"] - p["B"] - p["d"]) / 2,
        "adjacent_center_distance_mm": p["P"] * math.sin(math.pi / p["n"]),
        "adjacent_hole_gap_mm": p["P"] * math.sin(math.pi / p["n"]) - p["d"],
    }


def invalid_reasons(p):
    reasons = []
    if min(p["D"], p["B"], p["P"], p["d"]) <= 0 or p["n"] < 2:
        return ["直径必须为正且孔数至少为 2"]
    if p["B"] >= p["D"]:
        reasons.append("中心孔直径不小于外径")
    c = clearances(p)
    if c["outer_edge_mm"] <= TOL:
        reasons.append(f"螺栓孔超出或接触外圆，边缘净距 {c['outer_edge_mm']:.6f} mm")
    if c["center_hole_mm"] <= TOL:
        reasons.append(f"螺栓孔与中心孔相交或接触，净距 {c['center_hole_mm']:.6f} mm")
    if c["adjacent_hole_gap_mm"] <= TOL:
        reasons.append(
            f"相邻螺栓孔重叠或接触，中心距 {c['adjacent_center_distance_mm']:.6f} mm"
            f" < 孔径 {p['d']:g} mm，净距 {c['adjacent_hole_gap_mm']:.6f} mm"
        )
    return reasons


def create_drawing(p):
    doc = ezdxf.new("R2013", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 2
    doc.header["$LTSCALE"] = 1.0
    doc.header["$LWDISPLAY"] = True
    doc.header["$INSBASE"] = (0, 0, 0)
    # The pattern starts with its full length, then dash/gap/dot/gap.
    if "CENTER" not in doc.linetypes:
        doc.linetypes.new("CENTER", dxfattribs={
            "description": "Center ____ _ ____ _ ____",
            "pattern": [20.0, 12.0, -3.0, 2.0, -3.0],
        })
    else:
        doc.linetypes.get("CENTER").setup_pattern([20.0, 12.0, -3.0, 2.0, -3.0])
    for name, weight, ltype in [
        ("OUTLINE", 35, "CONTINUOUS"),
        ("BORE", 35, "CONTINUOUS"),
        ("BOLT_HOLES", 35, "CONTINUOUS"),
        ("CENTER", 18, "CENTER"),
        ("DIMENSIONS", 18, "CONTINUOUS"),
        ("NOTES", 25, "CONTINUOUS"),
    ]:
        doc.layers.new(name, dxfattribs={"color": 7, "lineweight": weight, "linetype": ltype})
    doc.styles.new("CN", dxfattribs={"font": "simsun.ttc"})
    doc.dimstyles.new("FLANGE_DIM", dxfattribs={
        "dimtxt": 3.5, "dimasz": 2.5, "dimgap": 1.0,
        "dimtad": 1, "dimtih": 1, "dimtoh": 1,
        "dimtmove": 1, "dimtofl": 0, "dimcen": 0,
        "dimdec": 0, "dimzin": 8, "dimlfac": 1,
        "dimclrd": 7, "dimclre": 7, "dimclrt": 7,
        "dimtxsty": "CN",
    })
    msp = doc.modelspace()
    R, b, r, h = p["D"] / 2, p["B"] / 2, p["P"] / 2, p["d"] / 2
    msp.add_circle((0, 0), R, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), b, dxfattribs={"layer": "BORE"})
    msp.add_circle((0, 0), r, dxfattribs={"layer": "CENTER", "linetype": "CENTER"})
    # Clockwise from +Y, giving the first bolt hole exactly at (0, P/2).
    for i in range(p["n"]):
        a = 2 * math.pi * i / p["n"]
        x, y = r * math.sin(a), r * math.cos(a)
        x = 0.0 if abs(x) < TOL else x
        y = 0.0 if abs(y) < TOL else y
        msp.add_circle((x, y), h, dxfattribs={"layer": "BOLT_HOLES"})
    for start, end in [((-(R + 10), 0), (R + 10, 0)), ((0, -(R + 10)), (0, R + 10))]:
        msp.add_line(start, end, dxfattribs={"layer": "CENTER", "linetype": "CENTER"})

    # Each is a true DIAMETER DIMENSION with a rendered anonymous block.
    # Three separate quadrants keep the annotation tails apart.
    for radius, location, text in [
        (R, (-R - 22, 0.72 * R), "<>"),
        (b, (-R - 22, -0.55 * R), "<>"),
        (r, (R + 22, -0.55 * R), "节圆 <>"),
    ]:
        dim = msp.add_diameter_dim(
            (0, 0), radius=radius, location=location, text=text,
            dimstyle="FLANGE_DIM", dxfattribs={"layer": "DIMENSIONS"},
        )
        dim.render()

    # Leader starts on the circumference of the first bolt hole.
    tip = (h / math.sqrt(2), r + h / math.sqrt(2))
    elbow = (R + 15, R + 20)
    end = (R + 52, R + 20)
    msp.add_leader(
        [tip, elbow, end], dimstyle="FLANGE_DIM",
        dxfattribs={"layer": "DIMENSIONS"},
    )
    msp.add_mtext(
        f"{p['n']}×Ø{p['d']:g}",
        dxfattribs={"insert": (elbow[0] + 1, elbow[1] + 2),
                    "char_height": 3.5, "style": "CN", "attachment_point": 7,
                    "layer": "DIMENSIONS"},
    )
    msp.add_text(
        f"{p['id']}  材料 {p['material']}",
        dxfattribs={"height": 4.5, "style": "CN", "layer": "NOTES"},
    ).set_placement((0, -R - 28), align=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(
        "单位：mm", dxfattribs={"height": 3.0, "style": "CN", "layer": "NOTES"},
    ).set_placement((0, -R - 37), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.set_modelspace_vport(height=2 * R + 110, center=(0, -4))
    path = ROOT / f"{p['id']}.dxf"
    doc.saveas(path)
    return path


def near(a, b):
    assert abs(a - b) < TOL, (a, b)


def verify_drawing(p, path):
    """Checks use entities reloaded from disk, not the drawing's in-memory objects."""
    doc = ezdxf.readfile(path)
    audit = doc.audit()
    assert not audit.errors and not audit.fixes, (path.name, audit.errors, audit.fixes)
    assert doc.units == units.MM
    assert doc.dxfversion == "AC1027"
    assert "CENTER" in doc.linetypes
    assert doc.layers.get("CENTER").dxf.linetype == "CENTER"
    pattern = [tag.value for tag in doc.linetypes.get("CENTER").pattern_tags.tags if tag.code == 49]
    assert pattern == [12.0, -3.0, 2.0, -3.0]
    assert any(v > 0 for v in pattern) and any(v < 0 for v in pattern)
    msp = doc.modelspace()
    circles = list(msp.query("CIRCLE"))
    assert len(circles) == p["n"] + 3
    for layer, diameter in [("OUTLINE", p["D"]), ("BORE", p["B"]), ("CENTER", p["P"])]:
        selected = [c for c in circles if c.dxf.layer == layer]
        assert len(selected) == 1
        c = selected[0]
        near(c.dxf.center.magnitude, 0)
        near(c.dxf.radius * 2, diameter)
        if layer == "CENTER":
            assert c.dxf.linetype == "CENTER"
    holes = [c for c in circles if c.dxf.layer == "BOLT_HOLES"]
    assert len(holes) == p["n"]
    expected = [(p["P"] / 2 * math.sin(2 * math.pi * i / p["n"]),
                 p["P"] / 2 * math.cos(2 * math.pi * i / p["n"])) for i in range(p["n"])]
    for c, (x, y) in zip(holes, expected):
        near(c.dxf.center.x, x)
        near(c.dxf.center.y, y)
        near(c.dxf.center.z, 0)
        near(c.dxf.radius * 2, p["d"])
        near(c.dxf.center.magnitude, p["P"] / 2)
    near(holes[0].dxf.center.x, 0)
    near(holes[0].dxf.center.y, p["P"] / 2)
    # Independent collision checks on the actual saved circles, all pairs.
    edge_gaps = [p["D"] / 2 - c.dxf.center.magnitude - c.dxf.radius for c in holes]
    bore_gaps = [c.dxf.center.magnitude - c.dxf.radius - p["B"] / 2 for c in holes]
    pair_gaps = [(a.dxf.center - b.dxf.center).magnitude - a.dxf.radius - b.dxf.radius
                 for i, a in enumerate(holes) for b in holes[i + 1:]]
    assert min(edge_gaps) > TOL and min(bore_gaps) > TOL and min(pair_gaps) > TOL
    lines = list(msp.query('LINE[layer=="CENTER"]'))
    assert len(lines) == 2 and all(e.dxf.linetype == "CENTER" for e in lines)
    assert any(abs(e.dxf.start.y) < TOL and abs(e.dxf.end.y) < TOL
               and e.dxf.start.x < -p["D"] / 2 and e.dxf.end.x > p["D"] / 2 for e in lines)
    assert any(abs(e.dxf.start.x) < TOL and abs(e.dxf.end.x) < TOL
               and e.dxf.start.y < -p["D"] / 2 and e.dxf.end.y > p["D"] / 2 for e in lines)
    dims = list(msp.query("DIMENSION"))
    assert len(dims) == 3 and all(d.dimtype == 3 for d in dims)
    for dim, measurement in zip(dims, [p["D"], p["B"], p["P"]]):
        near(dim.get_measurement(), measurement)
        assert (dim.dxf.defpoint + dim.dxf.defpoint4).magnitude < TOL
        near(dim.dxf.defpoint.magnitude, measurement / 2)
        assert dim.dxf.geometry in doc.blocks
        rendered = list(doc.blocks.get(dim.dxf.geometry))
        assert len(rendered) >= 3
        texts = [e.plain_text().replace("%%c", "Ø") for e in rendered if e.dxftype() == "MTEXT"]
        expected_text = ("节圆 " if dim is dims[2] else "") + f"Ø{measurement:g}"
        assert texts == [expected_text], texts
    assert "节圆" in dims[2].dxf.text
    callouts = list(msp.query("MTEXT"))
    assert len(callouts) == 1
    assert callouts[0].plain_text() == f"{p['n']}×Ø{p['d']:g}"
    leader = list(msp.query("LEADER"))
    assert len(leader) == 1 and leader[0].dxf.has_arrowhead == 1
    near((leader[0].vertices[0] - holes[0].dxf.center).magnitude, p["d"] / 2)
    notes = list(msp.query('TEXT[layer=="NOTES"]'))
    assert any(e.dxf.text == f"{p['id']}  材料 {p['material']}" for e in notes)
    assert all(e.dxf.insert.y < -p["D"] / 2 for e in notes)
    return {
        **p, "file": path.name, "status": "PASS",
        "diameters_mm": [d.get_measurement() for d in dims],
        "circle_count": len(circles), "bolt_hole_count": len(holes),
        "first_hole_center_mm": list(holes[0].dxf.center),
        "minimum_outer_edge_mm": min(edge_gaps),
        "minimum_center_hole_gap_mm": min(bore_gaps),
        "minimum_bolt_hole_gap_mm": min(pair_gaps),
        "diameter_dimension_count": len(dims),
        "centerline_count": len(lines), "audit_errors": len(audit.errors),
        "audit_fixes": len(audit.fixes), "bytes": path.stat().st_size,
    }


def main():
    generated, skipped = [], []
    for p in rows():
        reasons = invalid_reasons(p)
        if reasons:
            assert not (ROOT / f"{p['id']}.dxf").exists(), "无效零件存在旧图纸，请人工检查"
            skipped.append({**p, **clearances(p), "reasons": reasons})
            continue
        path = create_drawing(p)
        generated.append(verify_drawing(p, path))
        print(f"PASS {path.name}: {p['n']} holes, diameters {p['D']:g}/{p['B']:g}/{p['P']:g} mm")
    assert len(generated) == 10 and len(skipped) == 2
    assert {p["id"] for p in skipped} == {"FL-109", "FL-111"}
    assert {p.name for p in ROOT.glob("FL-*.dxf")} == {r["file"] for r in generated}
    report = {"units": "mm", "ezdxf_version": ezdxf.__version__,
              "generated_count": len(generated), "skipped_count": len(skipped),
              "generated": generated, "skipped": skipped}
    (ROOT / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["法兰盘 DXF 生成与核验报告", "单位：mm；DXF：R2013；ezdxf：" + ezdxf.__version__,
             "有效零件 10 个，逐个重新读取并核验通过；无效零件 2 个，未出图。", "",
             "零件号 | 外径 | 中心孔 | 节圆 | 螺栓孔 | 外缘净距 | 中心孔净距 | 最小孔间净距"]
    for r in generated:
        lines.append(f"{r['id']} | {r['D']:g} | {r['B']:g} | {r['P']:g} | {r['n']}×Ø{r['d']:g} | "
                     f"{r['minimum_outer_edge_mm']:.3f} | {r['minimum_center_hole_gap_mm']:.3f} | {r['minimum_bolt_hole_gap_mm']:.3f}")
    lines += ["", "未出图："]
    lines += [r["id"] + "：" + "；".join(r["reasons"]) for r in skipped]
    lines += ["", "核验：尺寸单位、同心圆、全部孔位及孔径、首孔在正上方、全部孔对净距、CENTER 点画线、水平/竖直中心线、",
              "三条原生直径尺寸及其图块显示文字、螺栓孔数量与直径引出标注、下方零件号与材料。",
              "全部文件 DXF audit：0 错误、0 修复。几何与尺寸数值核验容差 1e-7 mm。",
              "问题及处理：修正探查用的 DiameterDimension 模块名；可选预览缺少 Pillow，未安装包，采用 DXF 回读核验。",
              "首次核验误将编译后的线型间隔当作有符号值，已改为核对原始 DXF 49 组码；同时发现节圆直径符号重复，已修正并严格核对完整标注文字。",
              "限制：未在 CAD 软件中目视复核；中文字体样式为 simsun.ttc，其他电脑需有相应字体或进行字体替换。"]
    (ROOT / "verification_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Generated 10 DXFs; skipped FL-109 and FL-111; all reload checks passed.")


if __name__ == "__main__":
    main()
