"""Create and verify the A3 print layout without modifying model entities.

Run with the supplied Python interpreter; depends only on ezdxf and stdlib.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf.tagwriter import TagCollector


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "part.dxf"
BACKUP = ROOT / "part.original.dxf"
REPORT = ROOT / "a3_verification.json"


def entity_tags(entity):
    return [(tag.code, str(tag.value))
            for tag in TagCollector.dxftags(entity, dxfversion="AC1024")]


def protected_content(doc):
    """Include rendered dimension geometry and pre-existing resources."""
    return {
        "model": [entity_tags(e) for e in doc.modelspace()],
        "dimension_blocks": {
            block.name: [entity_tags(e) for e in block]
            for block in doc.blocks
            if block.name.upper().startswith("*D")
        },
        "styles": {e.dxf.name: entity_tags(e) for e in doc.styles},
        "dimstyles": {e.dxf.name: entity_tags(e) for e in doc.dimstyles},
        "layers": {e.dxf.name: entity_tags(e) for e in doc.layers},
    }


def check_original_content(before, after):
    assert before["model"] == after["model"], "Model entities changed"
    assert before["dimension_blocks"] == after["dimension_blocks"], \
        "Rendered dimension blocks changed"
    for resource in ("styles", "dimstyles", "layers"):
        for name, tags in before[resource].items():
            assert after[resource][name] == tags, (resource, name)


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-8), \
        (actual, expected)


def rectangle(layout, lower, upper, layer):
    x0, y0 = lower
    x1, y1 = upper
    return layout.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True, dxfattribs={"layer": layer},
    )


def verify(filename, original_content, expected_bbox):
    doc = ezdxf.readfile(filename)
    check_original_content(original_content, protected_content(doc))
    assert doc.units == 4
    layout = doc.layouts.get("A3")
    settings = layout.dxf
    close(settings.paper_width, 420)
    close(settings.paper_height, 297)
    assert settings.plot_rotation == 0
    assert settings.plot_paper_units == 1
    assert settings.plot_type == 5
    close(settings.scale_numerator / settings.scale_denominator, 1)
    for key in ("left_margin", "right_margin", "top_margin", "bottom_margin",
                "plot_origin_x_offset", "plot_origin_y_offset"):
        close(settings.get(key), 0)
    assert doc.layouts.active_layout().name == "A3"
    assert doc.header["$TILEMODE"] == 0

    for layer, expected in (
        ("A3_OUTER", [(0, 0), (420, 0), (420, 297), (0, 297)]),
        ("A3_FRAME", [(25, 5), (415, 5), (415, 292), (25, 292)]),
        ("A3_TITLE", [(235, 5), (415, 5), (415, 45), (235, 45)]),
    ):
        entities = list(layout.query(f'LWPOLYLINE[layer=="{layer}"]'))
        assert len(entities) == 1 and entities[0].closed
        actual = list(entities[0].get_points("xy"))
        for point, wanted in zip(actual, expected):
            close(point[0], wanted[0])
            close(point[1], wanted[1])

    texts = list(layout.query('TEXT[layer=="A3_TEXT"]'))
    assert {e.dxf.text for e in texts} == {
        "图名：底板", "图号：BP-300", "比例：1:2", "材料：Q235",
    }
    for text in texts:
        p = text.dxf.align_point
        assert 235 < p.x < 415 and 5 < p.y < 45
        assert text.dxf.style == "A3_CHINESE"

    # The automatic id=1 paper viewport is not a model display viewport.
    viewports = [v for v in layout.query("VIEWPORT") if v.dxf.id > 1]
    assert len(viewports) == 1
    vp = viewports[0]
    scale = vp.dxf.height / vp.dxf.view_height
    close(scale, 0.5)
    close(vp.get_scale(), 0.5)
    assert vp.dxf.status > 0 and vp.dxf.flags & 16384
    assert doc.layers.get(vp.dxf.layer).dxf.plot == 0
    assert tuple(vp.dxf.view_direction_vector) == (0, 0, 1)
    close(vp.dxf.view_twist_angle, 0)
    cx, cy, _ = vp.dxf.center
    vx0, vy0 = cx - vp.dxf.width / 2, cy - vp.dxf.height / 2
    vx1, vy1 = cx + vp.dxf.width / 2, cy + vp.dxf.height / 2
    assert 25 <= vx0 < vx1 <= 415 and 5 <= vy0 < vy1 <= 292
    assert vx1 <= 235 or vx0 >= 415 or vy1 <= 5 or vy0 >= 45
    bounds = bbox.extents(doc.modelspace())
    for actual, expected in zip((*bounds.extmin, *bounds.extmax), expected_bbox):
        close(actual, expected)
    mx = vp.dxf.view_center_point.x
    my = vp.dxf.view_center_point.y
    projected = [
        cx + (bounds.extmin.x - mx) * scale,
        cy + (bounds.extmin.y - my) * scale,
        cx + (bounds.extmax.x - mx) * scale,
        cy + (bounds.extmax.y - my) * scale,
    ]
    px0, py0, px1, py1 = projected
    assert vx0 < px0 < px1 < vx1 and vy0 < py0 < py1 < vy1
    close((px0 + px1) / 2, 220)
    close((py0 + py1) / 2, (45 + 292) / 2)
    close(300 * scale, 150)
    close(160 * scale, 80)
    audit = doc.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    model_digest = hashlib.sha256(
        json.dumps(original_content["model"], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "result": "PASS",
        "file": TARGET.name,
        "paper_mm": [420, 297],
        "paper_plot_scale": "1:1",
        "active_layout": "A3",
        "inner_frame_bounds_mm": [25, 5, 415, 292],
        "frame_margins_left_right_bottom_top_mm": [25, 5, 5, 5],
        "title_bounds_mm": [235, 5, 415, 45],
        "title_size_mm": [180, 40],
        "title_texts": sorted(e.dxf.text for e in texts),
        "model_viewport_count": len(viewports),
        "viewport_bounds_mm": [vx0, vy0, vx1, vy1],
        "viewport_scale": scale,
        "viewport_locked": True,
        "viewport_layer_printable": False,
        "model_view_center": list(vp.dxf.view_center_point),
        "model_and_dimension_bounds_mm": list(expected_bbox),
        "projected_model_and_dimension_bounds_mm": projected,
        "projected_part_size_mm": [150, 80],
        "model_entity_count": len(doc.modelspace()),
        "model_dimension_count": len(doc.modelspace().query("DIMENSION")),
        "model_entities_unchanged": True,
        "dimension_blocks_unchanged": True,
        "original_styles_dimstyles_layers_unchanged": True,
        "model_entities_sha256": model_digest,
        "audit_errors": len(audit.errors),
        "audit_fixes": len(audit.fixes),
    }


def main():
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
    doc = ezdxf.readfile(TARGET)
    original = protected_content(doc)
    bounds = bbox.extents(doc.modelspace())
    expected_bbox = (*bounds.extmin, *bounds.extmax)
    model_center = ((bounds.extmin.x + bounds.extmax.x) / 2,
                    (bounds.extmin.y + bounds.extmax.y) / 2)
    if "A3" in doc.layouts:
        doc.layouts.delete("A3")
    layout = doc.layouts.new("A3")
    # Landscape dimensions are explicit; no additional 90-degree rotation.
    # Plot paper 1:1, then set only the model viewport to 1:2.
    layout.page_setup(size=(420, 297), margins=(0, 0, 0, 0),
                      units="mm", offset=(0, 0), rotation=0, scale=(1, 1),
                      name="ISO_A3", device="DWG to PDF.pc3")
    layout.set_plot_type(5)
    for name, weight, printable in (
        ("A3_OUTER", 25, 1), ("A3_FRAME", 50, 1),
        ("A3_TITLE", 25, 1), ("A3_TEXT", 25, 1),
        ("A3_VIEWPORT", 0, 0),
    ):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={
                "color": 7, "lineweight": weight, "plot": printable,
            })
    if "A3_CHINESE" not in doc.styles:
        # Windows Microsoft YaHei is present on this host; leave model styles intact.
        doc.styles.new("A3_CHINESE", dxfattribs={"font": "msyh.ttc"})
    rectangle(layout, (0, 0), (420, 297), "A3_OUTER")
    rectangle(layout, (25, 5), (415, 292), "A3_FRAME")
    rectangle(layout, (235, 5), (415, 45), "A3_TITLE")
    layout.add_line((235, 25), (415, 25), dxfattribs={"layer": "A3_TITLE"})
    layout.add_line((325, 5), (325, 45), dxfattribs={"layer": "A3_TITLE"})
    for value, point, height in (
        ("图名：底板", (280, 35), 5),
        ("图号：BP-300", (370, 35), 4),
        ("比例：1:2", (280, 15), 4),
        ("材料：Q235", (370, 15), 4),
    ):
        text = layout.add_text(value, dxfattribs={
            "height": height, "layer": "A3_TEXT", "style": "A3_CHINESE",
        })
        text.set_placement(point, align=TextEntityAlignment.MIDDLE_CENTER)
    viewport_height = 227
    layout.add_viewport(
        center=(220, 168.5), size=(370, viewport_height),
        view_center_point=model_center, view_height=viewport_height * 2,
        status=2, dxfattribs={
            "layer": "A3_VIEWPORT", "flags": 16384,
            "view_direction_vector": (0, 0, 1), "view_target_point": (0, 0, 0),
            "view_twist_angle": 0,
        },
    )
    doc.layouts.set_active_layout("A3")
    doc.header["$TILEMODE"] = 0
    # Verify a temporary save before replacing the requested deliverable.
    candidate = ROOT / "part.a3_candidate.dxf"
    doc.saveas(candidate)
    report = verify(candidate, original, expected_bbox)
    candidate.replace(TARGET)
    # Independently reopen the actual final path as well.
    report = verify(TARGET, original, expected_bbox)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
