"""Test K: PDF plotting without external software (plot.py): pages, sheet sizes, scale, text, safety."""
from __future__ import annotations

import pypdf
import pytest

from conftest import ok

MM = 72 / 25.4


def pages(path):
    r = pypdf.PdfReader(str(path))
    return [(round(float(p.mediabox.width) / MM, 1), round(float(p.mediabox.height) / MM, 1),
             p.get_contents().get_data().decode("latin-1")) for p in r.pages]


def test_model_space_fits_a_standard_scale(rt, ws, plate):
    r = ok(rt.export_drawing(plate, "plate.pdf", "pdf"))
    assert [p["layout"] for p in r["pages"]] == ["Model"]
    pg = r["pages"][0]
    assert pg["placement"] == "fit" and pg["scale_text"] in ("1:1", "2:1", "5:1")  # never an odd 1.37:1
    (w, h, content), = pages(ws / "plate.pdf")
    assert (w, h) == tuple(pg["paper_mm"]) and w > h  # landscape for a wide part
    assert content.count(" S") > 20 and " f*" in content  # strokes and filled text/arrowheads


def test_explicit_scale_picks_the_smallest_sheet(rt, ws, plate):
    pg = ok(rt.export_drawing(plate, "p1.pdf", "pdf", scale=1))["pages"][0]
    assert pg["paper_mm"] == [297, 210] and pg["scale_text"] == "1:1"  # 100x60 part + dims fits A4
    e = rt.export_drawing(plate, "p2.pdf", "pdf", scale=20)["error"]
    assert e["code"] == "PLOT_TOO_LARGE" and not (ws / "p2.pdf").exists()
    pg = ok(rt.export_drawing(plate, "p3.pdf", "pdf", scale=5, paper="A4"))["pages"][0]
    assert pg.get("clipped") is True  # forced sheet too small: cropped, and said so


def test_paper_layouts_print_one_to_one_one_page_each(rt, ws, plate):
    ok(rt.apply_operations(plate, [
        {"op": "create_layout", "name": "A3 sheet", "paper": "A3"},
        {"op": "add_viewport", "layout": "A3 sheet", "center": [210, 148], "scale": 2, "width": 300, "height": 200},
        {"op": "add_rectangle", "layout": "A3 sheet", "corner": [10, 10], "width": 400, "height": 277},
        {"op": "create_layout", "name": "A4 sheet", "paper": "A4", "orientation": "portrait"},
        {"op": "add_text", "layout": "A4 sheet", "text": "NOTES", "insert": [20, 270], "height": 5}]))
    r = ok(rt.export_drawing(plate, "sheets.pdf", "pdf"))  # default: paper layouts with content
    assert [p["layout"] for p in r["pages"]] == ["A3 sheet", "A4 sheet"]
    assert all(p["scale"] == 1 and p["placement"] == "layout page setup" for p in r["pages"])
    assert [(w, h) for w, h, _ in pages(ws / "sheets.pdf")] == [(420, 297), (210, 297)]
    one = ok(rt.export_drawing(plate, "model.pdf", "pdf", layout="Model"))
    assert [p["layout"] for p in one["pages"]] == ["Model"]
    assert rt.export_drawing(plate, "x.pdf", "pdf", layout="Nope")["error"]["code"] == "LAYOUT_NOT_FOUND"


def test_monochrome_and_small_printed_text(rt, ws, blank):
    ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 2000, "color": 1},
                                   {"op": "add_text", "text": "tiny", "insert": [0, 0], "height": 3}]))
    r = ok(rt.export_drawing(blank, "m.pdf", "pdf", paper="A4", monochrome=True))
    assert r["pages"][0]["scale"] < 0.1
    assert any(w["code"] == "PRINTED_TEXT_TOO_SMALL" for w in r["warnings"])
    content = pages(ws / "m.pdf")[0][2]
    assert "1 0 0 RG" not in content and "0 0 0 RG" in content


def test_chinese_text_gets_a_cjk_font(rt, ws, blank):
    from ezdxf.fonts import fonts
    from agentcad.plot import CJK_FONTS
    if not any(fonts.font_manager.has_font(f) for f in CJK_FONTS):
        pytest.skip("no CJK font installed")
    ok(rt.apply_operations(blank, [{"op": "add_text", "text": "安装板 Ø8", "insert": [0, 0], "height": 5}]))
    r = ok(rt.export_drawing(blank, "zh.pdf", "pdf"))
    assert "font_substitution" in r
    # the source drawing is untouched: styles still use the SHX fonts
    import ezdxf
    assert ezdxf.readfile(ws / blank).styles.get("Standard").dxf.font.lower().endswith(".shx")


def test_pdf_respects_sandbox_and_overwrite(rt, ws, plate):
    assert rt.export_drawing(plate, "../out.pdf", "pdf")["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    ok(rt.export_drawing(plate, "a.pdf", "pdf"))
    assert rt.export_drawing(plate, "a.pdf", "pdf")["error"]["code"] == "FILE_EXISTS"
    assert rt.export_drawing(plate, "a.dxf", "pdf")["error"]["code"] == "BAD_EXTENSION"
