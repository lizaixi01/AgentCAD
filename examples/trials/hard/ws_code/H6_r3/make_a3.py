"""Create and verify an A3 print layout without changing model entities."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import shutil

import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf.tagwriter import TagCollector


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "part.dxf"
BACKUP = ROOT / "part.original.dxf"
PENDING = ROOT / "part_A3.pending.dxf"
REPORT = ROOT / "verification.json"


def entity_signature(entity):
    return [(tag.code, str(tag.value)) for tag in TagCollector.dxftags(entity)]


def preserved_state(doc, block_names=None, table_names=None):
    if block_names is None:
        block_names = [b.name for b in doc.blocks
                       if not b.name.upper().startswith("*PAPER_SPACE")]
    if table_names is None:
        table_names = {name: [entry.dxf.name for entry in getattr(doc, name)]
                       for name in ("layers", "styles", "dimstyles", "linetypes")}
    return {
        "model": [entity_signature(e) for e in doc.modelspace()],
        "blocks": {name: [entity_signature(e) for e in doc.blocks[name]]
                   for name in block_names},
        "tables": {table: {name: entity_signature(getattr(doc, table).get(name))
                           for name in names}
                   for table, names in table_names.items()},
    }, block_names, table_names


def close(a, b):
    assert math.isclose(a, b, rel_tol=0, abs_tol=1e-8), (a, b)


doc = ezdxf.readfile(TARGET)
original, block_names, table_names = preserved_state(doc)
if not BACKUP.exists():
    shutil.copyfile(TARGET, BACKUP)
else:
    backup_state, _, _ = preserved_state(
        ezdxf.readfile(BACKUP), block_names, table_names)
    assert original == backup_state, "Existing backup differs from model resources."

model_bounds = bbox.extents(doc.modelspace(), fast=False)
model_center = ((model_bounds.extmin.x + model_bounds.extmax.x) / 2,
                (model_bounds.extmin.y + model_bounds.extmax.y) / 2)

if "A3" in doc.layout_names():
    doc.layouts.delete("A3")
paper = doc.layouts.new("A3")
paper.page_setup(size=(420, 297), margins=(0, 0, 0, 0),
                 units="mm", offset=(0, 0), rotation=0, scale=(1, 1),
                 name="ISO_full_bleed_A3", device="DWG To PDF.pc3")
paper.set_plot_type(5)
paper.print_lineweights(True)
paper.plot_viewport_borders(False)

for name, weight, plot in (("A3_OUTER", 18, True),
                           ("A3_FRAME", 50, True),
                           ("A3_TITLE", 25, True),
                           ("A3_TEXT", 25, True),
                           ("A3_VIEWPORT", 0, False)):
    if name not in doc.layers:
        doc.layers.new(name, dxfattribs={"color": 7, "lineweight": weight,
                                       "plot": int(plot)})
if "A3_CHINESE" not in doc.styles:
    doc.styles.new("A3_CHINESE", dxfattribs={"font": "simsun.ttc"})


def rectangle(x0, y0, x1, y1, layer):
    return paper.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                               close=True, dxfattribs={"layer": layer})


rectangle(0, 0, 420, 297, "A3_OUTER")
rectangle(25, 5, 415, 292, "A3_FRAME")
rectangle(235, 5, 415, 45, "A3_TITLE")
paper.add_line((235, 25), (415, 25), dxfattribs={"layer": "A3_TITLE"})
paper.add_line((325, 5), (325, 45), dxfattribs={"layer": "A3_TITLE"})

fields = [("图名：底板", (280, 35), 5),
          ("图号：BP-300", (370, 35), 4.5),
          ("比例：1:2", (280, 15), 4.5),
          ("材料：Q235", (370, 15), 4.5)]
for text, point, height in fields:
    paper.add_text(text, dxfattribs={"height": height, "style": "A3_CHINESE",
                                     "layer": "A3_TEXT"}).set_placement(
        point, align=TextEntityAlignment.MIDDLE_CENTER)

# Paper 1:1; model-to-paper scale is independently fixed at 0.5.
# Viewport rectangle: (45,55)-(395,282), above title block by 10 mm.
vp = paper.add_viewport(center=(220, 168.5), size=(350, 227),
                        view_center_point=model_center, view_height=454,
                        dxfattribs={"layer": "A3_VIEWPORT",
                                    "view_direction_vector": (0, 0, 1),
                                    "view_target_point": (0, 0, 0),
                                    "view_twist_angle": 0,
                                    "flags": 16384})  # DXF zoom-lock flag
doc.layouts.set_active_layout("A3")
doc.header["$TILEMODE"] = 0
doc.saveas(PENDING)


def verify(path):
    result = ezdxf.readfile(path)
    state, _, _ = preserved_state(result, block_names, table_names)
    assert state == original, "Model entities, blocks, or existing resources changed."
    assert result.units == 4
    layout = result.layouts.get("A3")
    settings = layout.dxf_layout.dxf
    close(settings.paper_width, 420)
    close(settings.paper_height, 297)
    close(settings.scale_numerator / settings.scale_denominator, 1)
    assert settings.plot_paper_units == 1 and settings.plot_rotation == 0
    assert settings.plot_type == 5
    assert result.layouts.active_layout().name == "A3"
    assert result.header["$TILEMODE"] == 0
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin",
                 "plot_origin_x_offset", "plot_origin_y_offset"):
        close(getattr(settings, attr), 0)

    def check_rectangle(layer, expected):
        entities = list(layout.query(f'LWPOLYLINE[layer=="{layer}"]'))
        assert len(entities) == 1 and entities[0].closed
        assert list(entities[0].get_points("xy")) == expected

    check_rectangle("A3_OUTER", [(0, 0), (420, 0), (420, 297), (0, 297)])
    check_rectangle("A3_FRAME", [(25, 5), (415, 5), (415, 292), (25, 292)])
    check_rectangle("A3_TITLE", [(235, 5), (415, 5), (415, 45), (235, 45)])
    assert {e.dxf.text for e in layout.query("TEXT")} == {f[0] for f in fields}
    for entity in layout.query("TEXT"):
        bounds = bbox.extents([entity])
        assert bounds.extmin.x >= 235 and bounds.extmax.x <= 415
        assert bounds.extmin.y >= 5 and bounds.extmax.y <= 45

    # ID 1 is the mandatory overall paperspace viewport, not a model window.
    windows = [e for e in layout.query("VIEWPORT") if e.dxf.id > 1]
    assert len(windows) == 1
    view = windows[0]
    assert view.dxf.status > 0 and view.dxf.flags & 16384
    assert result.layers.get(view.dxf.layer).dxf.plot == 0
    scale = view.dxf.height / view.dxf.view_height
    close(scale, 0.5)
    vx0 = view.dxf.center.x - view.dxf.width / 2
    vy0 = view.dxf.center.y - view.dxf.height / 2
    vx1 = vx0 + view.dxf.width
    vy1 = vy0 + view.dxf.height
    assert vx0 >= 25 and vx1 <= 415 and vy0 >= 5 and vy1 <= 292
    assert vx1 <= 235 or vx0 >= 415 or vy1 <= 5 or vy0 >= 45

    bounds = bbox.extents(result.modelspace(), fast=False)
    projected = [view.dxf.center.x + (bounds.extmin.x - view.dxf.view_center_point.x) * scale,
                 view.dxf.center.y + (bounds.extmin.y - view.dxf.view_center_point.y) * scale,
                 view.dxf.center.x + (bounds.extmax.x - view.dxf.view_center_point.x) * scale,
                 view.dxf.center.y + (bounds.extmax.y - view.dxf.view_center_point.y) * scale]
    assert vx0 < projected[0] < projected[2] < vx1
    assert vy0 < projected[1] < projected[3] < vy1
    audit = result.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return {
        "file": TARGET.name, "layout": "A3", "units": "mm",
        "paper_mm": [420, 297], "paper_plot_scale": "1:1",
        "inner_frame_mm": [25, 5, 415, 292],
        "title_block_mm": [235, 5, 415, 45],
        "title_fields": [f[0] for f in fields],
        "viewport_bounds_mm": [vx0, vy0, vx1, vy1],
        "viewport_scale": scale, "viewport_locked": True,
        "viewport_title_gap_mm": vy0 - 45,
        "model_bounds_mm": [bounds.extmin.x, bounds.extmin.y,
                            bounds.extmax.x, bounds.extmax.y],
        "projected_drawing_bounds_mm": projected,
        "model_entities": dict(Counter(e.dxftype() for e in result.modelspace())),
        "model_and_existing_resources_unchanged": state == original,
        "preserved_state_sha256": hashlib.sha256(
            json.dumps(state, sort_keys=True).encode()).hexdigest(),
        "audit_errors": len(audit.errors), "audit_fixes": len(audit.fixes),
    }


verify(PENDING)
PENDING.replace(TARGET)
report = verify(TARGET)
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=True, indent=2))
