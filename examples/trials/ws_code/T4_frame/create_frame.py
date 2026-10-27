"""Generate and independently re-read an A3 landscape DXF, using ezdxf only."""

from pathlib import Path
import json
import sys
from xml.sax.saxutils import escape

import ezdxf
from ezdxf.enums import TextEntityAlignment


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "frame_a3.dxf"
CELLS = []
LINES = []


def line(msp, start, end, layer="TABLE"):
    msp.add_line(start, end, dxfattribs={"layer": layer})
    LINES.append((start, end, layer))


def cell(msp, value, bounds, height=3.5):
    x0, y0, x1, y1 = bounds
    center = ((x0 + x1) / 2, (y0 + y1) / 2)
    entity = msp.add_text(
        value,
        dxfattribs={
            "layer": "TEXT",
            "style": "CHINESE",
            "height": height,
            "width": 0.85,
        },
    )
    entity.set_placement(center, align=TextEntityAlignment.MIDDLE_CENTER)
    CELLS.append({"text": value, "bounds": bounds, "center": center, "height": height})


def create():
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 2
    doc.header["$LWDISPLAY"] = True
    doc.header["$LIMMIN"] = (0, 0)
    doc.header["$LIMMAX"] = (420, 297)
    for name, weight in (("OUTER", 25), ("FRAME", 70), ("TABLE", 35), ("TEXT", 25)):
        doc.layers.new(name, dxfattribs={"color": 7, "lineweight": weight})
    doc.layers.new("VIEWPORTS", dxfattribs={"plot": 0})
    doc.styles.new("CHINESE", dxfattribs={"font": "simhei.ttf"})
    msp = doc.modelspace()

    # Closed outer boundary, 420 x 297 mm, lower left exactly at the origin.
    msp.add_lwpolyline(
        [(0, 0), (420, 0), (420, 297), (0, 297)],
        close=True,
        dxfattribs={"layer": "OUTER"},
    )
    # Closed inner boundary: left 25 mm; right/top/bottom 10 mm.
    msp.add_lwpolyline(
        [(25, 10), (410, 10), (410, 287), (25, 287)],
        close=True,
        dxfattribs={"layer": "FRAME"},
    )

    # Title block: x=230..410, y=10..42. Its bottom and right edges
    # reuse the inner frame, avoiding coincident duplicate entities.
    line(msp, (230, 10), (230, 78))
    line(msp, (230, 26), (410, 26))
    line(msp, (230, 42), (410, 42))
    for x in (250, 330, 350):
        line(msp, (x, 26), (x, 42))
    for x in (250, 290, 310, 350, 370):
        line(msp, (x, 10), (x, 26))
    title_cells = [
        ("名称", (230, 26, 250, 42)),
        ("法兰盘", (250, 26, 330, 42)),
        ("图号", (330, 26, 350, 42)),
        ("FL-001", (350, 26, 410, 42)),
        ("材料", (230, 10, 250, 26)),
        ("Q235", (250, 10, 290, 26)),
        ("比例", (290, 10, 310, 26)),
        ("1:1", (310, 10, 350, 26)),
        ("单位", (350, 10, 370, 26)),
        ("mm", (370, 10, 410, 26)),
    ]
    for value, bounds in title_cells:
        cell(msp, value, bounds, 4.0)

    # BOM directly above the title: 180 x 36 mm, three 12-mm rows.
    for y in (54, 66, 78):
        line(msp, (230, y), (410, y))
    for x in (248, 340, 362):
        line(msp, (x, 42), (x, 78))
    columns = (230, 248, 340, 362, 410)
    rows = [
        (66, ("序号", "名称", "数量", "材料")),
        (54, ("1", "法兰盘", "1", "Q235")),
        (42, ("2", "螺栓 M10×40", "6", "8.8级")),
    ]
    for bottom, values in rows:
        for i, value in enumerate(values):
            cell(msp, value, (columns[i], bottom, columns[i + 1], bottom + 12))

    # A3 landscape paper setup and a true 1:1 viewport.
    paper = doc.layouts.get("Layout1")
    paper.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm", scale=(1, 1))
    paper.add_viewport(
        center=(210, 148.5),
        size=(420, 297),
        view_center_point=(210, 148.5),
        view_height=297,
        dxfattribs={"layer": "VIEWPORTS"},
    )
    doc.set_modelspace_vport(height=327, center=(210, 148.5))
    doc.saveas(OUTPUT)


def verify():
    # Read the saved bytes; verify actual persisted entities, not the source doc.
    doc = ezdxf.readfile(OUTPUT)
    msp = doc.modelspace()
    assert doc.units == 4, "Drawing units must be millimeters"
    for layer, expected in (
        ("OUTER", [(0, 0), (420, 0), (420, 297), (0, 297)]),
        ("FRAME", [(25, 10), (410, 10), (410, 287), (25, 287)]),
    ):
        polylines = list(msp.query(f'LWPOLYLINE[layer=="{layer}"]'))
        assert len(polylines) == 1
        polyline = polylines[0]
        assert polyline.closed
        assert list(polyline.get_points("xy")) == expected

    expected_lines = {(a, b, layer) for a, b, layer in LINES}
    actual_lines = {
        (tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2], e.dxf.layer)
        for e in msp.query("LINE")
    }
    assert len(actual_lines) == len(list(msp.query("LINE"))) == 17
    assert actual_lines == expected_lines
    texts = list(msp.query("TEXT"))
    assert len(texts) == len(CELLS) == 22
    for entity, expected in zip(texts, CELLS):
        assert entity.dxf.text == expected["text"]
        assert tuple(entity.dxf.align_point)[:2] == expected["center"]
        assert entity.dxf.height == expected["height"]
        assert entity.dxf.halign == 1 and entity.dxf.valign == 2
        assert entity.dxf.style == "CHINESE"
        x0, y0, x1, y1 = expected["bounds"]
        # Conservative full-em width estimate: Chinese 1 em, ASCII 0.65 em.
        units = sum(0.65 if ord(c) < 128 else 1.0 for c in entity.dxf.text)
        assert units * entity.dxf.height * entity.dxf.width < x1 - x0 - 2
        assert entity.dxf.height * 1.5 < y1 - y0 - 2
    assert doc.styles.get("CHINESE").dxf.font == "simhei.ttf"
    paper = doc.layouts.get("Layout1")
    assert paper.dxf.paper_width == 420 and paper.dxf.paper_height == 297
    viewport = [v for v in paper.query("VIEWPORT") if v.dxf.id > 1]
    assert len(viewport) == 1
    assert viewport[0].dxf.height / viewport[0].dxf.view_height == 1
    audit = doc.audit()
    assert not audit.errors and not audit.fixes, "DXF audit must be clean"
    report = {
        "file": OUTPUT.name,
        "units": "mm",
        "outer_frame": {"lower_left": [0, 0], "width": 420, "height": 297},
        "inner_frame": {"lower_left": [25, 10], "upper_right": [410, 287],
                        "width": 385, "height": 277},
        "margins": {"left": 25, "right": 10, "top": 10, "bottom": 10},
        "title_block": {"lower_left": [230, 10], "width": 180, "height": 32},
        "bom": {"lower_left": [230, 42], "width": 180, "height": 36,
                "row_height": 12, "column_widths": [18, 92, 22, 48]},
        "text_count": len(texts),
        "bom_rows": [["序号", "名称", "数量", "材料"],
                     ["1", "法兰盘", "1", "Q235"],
                     ["2", "螺栓 M10×40", "6", "8.8级"]],
        "paper": {"width": 420, "height": 297, "viewport_scale": "1:1"},
        "audit_errors": len(audit.errors),
        "audit_fixes": len(audit.fixes),
        "verified": True,
    }
    (ROOT / "frame_a3_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def preview():
    # A lightweight, browser-readable preview, with no extra dependencies.
    doc = ezdxf.readfile(OUTPUT)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1260" height="891" '
             'viewBox="-2 -2 424 301">', '<rect x="-2" y="-2" width="424" '
             'height="301" fill="white"/>']
    for entity in doc.modelspace():
        if entity.dxftype() == "LWPOLYLINE":
            points = list(entity.get_points("xy"))
            parts.append('<polygon points="' + ' '.join(f'{x},{297-y}' for x, y in points)
                         + f'" fill="none" stroke="black" stroke-width="'
                         + ('0.7' if entity.dxf.layer == 'FRAME' else '0.25') + '"/>')
        elif entity.dxftype() == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            parts.append(f'<line x1="{a.x}" y1="{297-a.y}" x2="{b.x}" '
                         f'y2="{297-b.y}" stroke="black" stroke-width="0.35"/>')
        elif entity.dxftype() == "TEXT":
            p = entity.dxf.align_point
            parts.append(f'<text x="{p.x}" y="{297-p.y}" text-anchor="middle" '
                         f'dominant-baseline="central" font-family="SimHei,Microsoft YaHei,sans-serif" '
                         f'font-size="{entity.dxf.height}" fill="black">'
                         f'{escape(entity.dxf.text)}</text>')
    parts.append('</svg>')
    (ROOT / "frame_a3_preview.svg").write_text('\n'.join(parts), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    create()
    verify()
    preview()
