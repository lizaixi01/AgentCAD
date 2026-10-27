"""Create and verify an A3 paper layout without modifying model entities."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf import const
from ezdxf.lldxf.tagwriter import TagCollector


ROOT = Path(__file__).resolve().parent
FILE = ROOT / "part.dxf"
BACKUP = ROOT / "part.original.dxf"
REPORT = ROOT / "a3_check.json"


def entity_tags(entity, version):
    return tuple((t.code, str(t.value)) for t in TagCollector.dxftags(entity, version))


def model_snapshot(doc):
    """Include all model entities and their rendered dimension blocks."""
    model = doc.modelspace()
    result = {"entities": [entity_tags(e, doc.dxfversion) for e in model]}
    names = sorted({e.dxf.geometry for e in model.query("DIMENSION")})
    result["dimension_blocks"] = {
        name: [entity_tags(e, doc.dxfversion) for e in doc.blocks[name]]
        for name in names
    }
    # Existing presentation resources are also checked, so adding a paper-space
    # style or layer cannot accidentally change model appearance.
    result["styles"] = {
        e.dxf.name: entity_tags(e, doc.dxfversion) for e in doc.styles
        if e.dxf.name != "A3_CJK"
    }
    result["layers"] = {
        e.dxf.name: entity_tags(e, doc.dxfversion) for e in doc.layers
        if e.dxf.name not in {"A3_FRAME", "A3_TITLE", "A3_VIEWPORT"}
    }
    result["dimstyles"] = {
        e.dxf.name: entity_tags(e, doc.dxfversion) for e in doc.dimstyles
    }
    return result


def digest(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def rectangle(layout, bounds, layer, lineweight=35):
    x0, y0, x1, y1 = bounds
    return layout.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
        dxfattribs={"layer": layer, "lineweight": lineweight},
    )


def inside(inner, outer, tolerance=1e-7):
    return (inner[0] >= outer[0] - tolerance
            and inner[1] >= outer[1] - tolerance
            and inner[2] <= outer[2] + tolerance
            and inner[3] <= outer[3] + tolerance)


def overlaps(a, b):
    return (min(a[2], b[2]) > max(a[0], b[0])
            and min(a[3], b[3]) > max(a[1], b[1]))


def main():
    if not BACKUP.exists():
        shutil.copy2(FILE, BACKUP)
    doc = ezdxf.readfile(FILE)
    original = model_snapshot(doc)
    model = doc.modelspace()
    ext = bbox.extents(model)
    assert ext.has_data
    outline = list(model.query("LWPOLYLINE"))
    assert outline
    outline_ext = bbox.extents(outline)
    assert outline_ext.extmin.isclose((0, 0, 0))
    assert outline_ext.extmax.isclose((300, 160, 0))

    if "A3" in doc.layouts:
        doc.layouts.delete("A3")
    sheet = doc.layouts.new("A3")
    sheet.page_setup(
        size=(420, 297), margins=(0, 0, 0, 0), units="mm",
        offset=(0, 0), rotation=0, scale=(1, 1),
        name="ISO_A3_Landscape", device="DWG To PDF.pc3",
    )
    sheet.set_plot_type(5)
    # PlotFlags: lineweights (32), plot styles (128), draw viewports first (512).
    sheet.dxf.plot_layout_flags = 32 | 128 | 512
    sheet.dxf.current_style_sheet = "monochrome.ctb"

    for name, weight in [("A3_FRAME", 50), ("A3_TITLE", 25), ("A3_VIEWPORT", 0)]:
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={
                "color": 7, "lineweight": weight, "plot": name != "A3_VIEWPORT",
            })
    # Leave the viewport layer on: only its boundary is excluded from printing.
    doc.layers.get("A3_VIEWPORT").dxf.plot = 0
    if "A3_CJK" not in doc.styles:
        style = doc.styles.new("A3_CJK", dxfattribs={"font": "simsun.ttc"})
        style.set_extended_font_data("SimSun")

    outer = (0.0, 0.0, 420.0, 297.0)
    inner = (25.0, 5.0, 415.0, 292.0)
    title = (235.0, 5.0, 415.0, 45.0)
    rectangle(sheet, outer, "A3_FRAME", 25)
    rectangle(sheet, inner, "A3_FRAME", 50)
    # The bottom and right edges are shared with the inner frame.
    for start, end in [
        ((235, 5), (235, 45)), ((235, 45), (415, 45)),
        ((235, 25), (415, 25)), ((235, 15), (415, 15)),
        ((325, 5), (325, 15)),
    ]:
        sheet.add_line(start, end, dxfattribs={"layer": "A3_TITLE", "lineweight": 25})

    for text, center, height in [
        ("图名：底板", (325, 35), 5),
        ("图号：BP-300", (325, 20), 4),
        ("比例：1:2", (280, 10), 3.5),
        ("材料：Q235", (370, 10), 3.5),
    ]:
        sheet.add_text(text, dxfattribs={
            "height": height, "style": "A3_CJK", "layer": "A3_TITLE",
        }).set_placement(center, align=TextEntityAlignment.MIDDLE_CENTER)

    # Paper-space millimetres / model-space millimetres = 0.5 exactly.
    paper_center = (220.0, 170.0)
    viewport_size = (370.0, 220.0)
    view_center = ((ext.extmin.x + ext.extmax.x) / 2,
                   (ext.extmin.y + ext.extmax.y) / 2)
    viewport = sheet.add_viewport(
        center=paper_center, size=viewport_size,
        view_center_point=view_center, view_height=viewport_size[1] * 2,
        status=2, dxfattribs={
            "layer": "A3_VIEWPORT", "view_direction_vector": (0, 0, 1),
            "view_target_point": (0, 0, 0), "view_twist_angle": 0,
            "flags": const.VSF_CURRENTLY_ALWAYS_ENABLED | const.VSF_LOCK_ZOOM,
            "render_mode": 0, "ucs_icon": 0,
        },
    )
    doc.layouts.set_active_layout("A3")
    doc.header["$TILEMODE"] = 0
    # Enter the layout in paper space, with its overall-paper viewport current.
    overall = next(v for v in sheet.query("VIEWPORT") if v.dxf.id == 1)
    sheet.set_current_viewport_handle(overall.dxf.handle)
    assert model_snapshot(doc) == original, "In-memory model was changed"
    doc.saveas(FILE)

    # Verification deliberately re-opens the saved DXF instead of inspecting
    # only the objects that were used to generate it.
    check = ezdxf.readfile(FILE)
    after = model_snapshot(check)
    assert after == original, "Saved model/dimension tags differ from original"
    sheet = check.layouts.get("A3")
    settings = sheet.dxf
    assert (settings.paper_width, settings.paper_height) == (420, 297)
    assert settings.plot_paper_units == 1 and settings.plot_rotation == 0
    assert settings.scale_numerator / settings.scale_denominator == 1
    assert settings.plot_type == 5
    assert (settings.left_margin, settings.right_margin,
            settings.top_margin, settings.bottom_margin) == (0, 0, 0, 0)
    frames = list(sheet.query('LWPOLYLINE[layer=="A3_FRAME"]'))
    assert len(frames) == 2
    for frame, expected in zip(frames, [outer, inner]):
        assert frame.closed
        points = list(frame.get_points("xy"))
        x0, y0, x1, y1 = expected
        assert points == [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    viewports = [v for v in sheet.query("VIEWPORT") if v.dxf.id != 1]
    assert len(viewports) == 1
    viewport = viewports[0]
    assert viewport.dxf.status > 0
    assert viewport.dxf.flags & const.VSF_LOCK_ZOOM
    assert check.layers.get(viewport.dxf.layer).dxf.plot == 0
    scale = viewport.dxf.height / viewport.dxf.view_height
    assert abs(scale - 0.5) < 1e-12
    cx, cy, _ = viewport.dxf.center
    w, h = viewport.dxf.width, viewport.dxf.height
    viewport_bounds = (cx - w/2, cy - h/2, cx + w/2, cy + h/2)
    assert inside(viewport_bounds, inner)
    assert not overlaps(viewport_bounds, title)
    ext_after = bbox.extents(check.modelspace())
    vx, vy, _ = viewport.dxf.view_center_point
    plotted = (
        cx + (ext_after.extmin.x - vx) * scale,
        cy + (ext_after.extmin.y - vy) * scale,
        cx + (ext_after.extmax.x - vx) * scale,
        cy + (ext_after.extmax.y - vy) * scale,
    )
    assert inside(plotted, viewport_bounds)
    assert inside(plotted, inner)
    assert not overlaps(plotted, title)
    assert abs((plotted[0] + plotted[2])/2 - 220) < 1e-8
    assert abs((plotted[1] + plotted[3])/2 - 170) < 1e-8
    texts = [t.dxf.text for t in sheet.query("TEXT")]
    assert texts == ["图名：底板", "图号：BP-300", "比例：1:2", "材料：Q235"]
    for entity in sheet.query('LINE[layer=="A3_TITLE"]'):
        for point in (entity.dxf.start, entity.dxf.end):
            assert inside((point.x, point.y, point.x, point.y), title)
    for entity in sheet.query("TEXT"):
        text_bounds = bbox.extents([entity])
        assert inside((text_bounds.extmin.x, text_bounds.extmin.y,
                       text_bounds.extmax.x, text_bounds.extmax.y), title)
    auditor = check.audit()
    assert not auditor.errors, str(auditor.errors)
    assert not auditor.fixes, str(auditor.fixes)
    report = {
        "file": FILE.name,
        "layout": "A3",
        "paper_mm": [420, 297],
        "paper_plot_scale": "1:1",
        "outer_frame_mm": outer,
        "inner_frame_mm": inner,
        "frame_margins_mm": {"left": 25, "right": 5, "top": 5, "bottom": 5},
        "title_block_mm": {"bounds": title, "size": [180, 40], "texts": texts},
        "viewport_mm": viewport_bounds,
        "viewport_scale": scale,
        "viewport_locked": True,
        "viewport_overlaps_title": False,
        "model_part_mm": [300, 160],
        "model_bounds_with_dimensions_mm": [list(ext_after.extmin), list(ext_after.extmax)],
        "projected_bounds_with_dimensions_mm": plotted,
        "projected_part_size_mm": [150, 80],
        "model_entity_counts": dict(Counter(e.dxftype() for e in check.modelspace())),
        "model_and_dimension_resources_unchanged": True,
        "original_model_sha256": digest(original),
        "saved_model_sha256": digest(after),
        "audit_errors": len(auditor.errors),
        "audit_fixes": len(auditor.fixes),
        "limitations": "Outer border on physical paper edge requires borderless output or PDF; Chinese title font is SimSun (simsun.ttc).",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
