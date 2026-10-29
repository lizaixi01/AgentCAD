"""3D parts built by scripts (run_script on a .FCStd: CadQuery or FreeCAD Part code) and previews compared with a
reference image (export_drawing(..., "png", reference=...)). Tests that build geometry need FreeCAD
(AGENTCAD_FREECAD); CadQuery tests also need the optional extra agentcad-runtime[cadquery]. The image comparison
itself is tested on synthetic images without either."""
from __future__ import annotations

import importlib.util
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from agentcad.backends import freecad
from agentcad.errors import AgentCADError
from agentcad.part import compare
from agentcad.policy import Policy
from agentcad.service import Runtime
from agentcad.store import sha256_file
from conftest import ok

needs_freecad = pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed (set AGENTCAD_FREECAD)")
needs_cadquery = pytest.mark.skipif(importlib.util.find_spec("cadquery") is None,
                                    reason="CadQuery not installed (pip install agentcad-runtime[cadquery])")

BLOCK = """
import cadquery as cq
w = 40
result = cq.Workplane("XY").box(w, 20, 10).faces(">Z").workplane().hole(6)
"""
VERTICAL = {"type": "line", "direction": "z"}


@pytest.fixture
def srt(ws):
    return Runtime(Policy(root=ws, allow_scripts=True, script_timeout=120))


def shape(r):
    return r["validation"]["shape"]


def journal(ws):
    f = next((ws / ".agentcad").rglob("journal.jsonl"))
    return [json.loads(x) for x in f.read_text("utf-8").splitlines()]


# --- policy and static checks (no FreeCAD needed) ------------------------------------------------------------

def test_part_scripts_are_off_by_default(rt, ws):
    e = rt.run_script("p.FCStd", BLOCK)["error"]
    assert e["code"] == "SCRIPTS_DISABLED" and e["category"] == "policy"
    assert not (ws / "p.FCStd").exists()


@pytest.mark.parametrize("code, why", [
    ("import cadquery as cq\nr = cq.Workplane().box(1, 1, 1)\ncq.exporters.export(r, 'x.step')", "'export'"),
    ("import cadquery as cq\nr = cq.exporters", "'exporters'"),
    ("from cadquery import exporters", "exporters"),
    ("import cadquery.occ_impl.exporters", "exporters"),
    ("import cadquery as cq\nresult = cq.importers.importStep('x.step')", "'importStep'"),
    ("import cadquery as cq\ncq.Workplane().box(1, 1, 1).val().exportStep('x.step')", "'exportStep'"),
    ("import os\nresult = None", "import of 'os'"),
    ("result = open('x.txt')", "'open'"),
    ("import subprocess", "'subprocess'"),
])
def test_part_scripts_are_checked_before_running(srt, ws, code, why):
    e = srt.run_script("p.FCStd", code)["error"]
    assert e["code"] == "SCRIPT_REJECTED" and why in e["message"], e
    assert "result" in e["hint"] and not (ws / "p.FCStd").exists()


def test_script_languages(srt, ws):
    e = srt.run_script("p.FCStd", BLOCK, language="ezdxf")["error"]
    assert e["code"] == "BAD_LANGUAGE" and "cadquery" in e["hint"]
    ok(srt.create_drawing("d.dxf"))
    e = srt.run_script("d.dxf", BLOCK, language="cadquery")["error"]
    assert e["code"] == "BAD_LANGUAGE"
    e = srt.run_script("d.dxf", "x = 1", keep_features=True)["error"]
    assert e["code"] == "UNKNOWN_PARAM"
    e = srt.run_script("p.FCStd", "result = Part.read('x.brep')", language="freecad")["error"]
    assert e["code"] == "SCRIPT_REJECTED" and "'read'" in e["message"]


# --- CadQuery scripts ----------------------------------------------------------------------------------------

@needs_freecad
@needs_cadquery
def test_cadquery_script_builds_a_part_that_ops_build_on(srt, ws):
    """The script's solid becomes the Body's base: one transaction with validation and journal (the full script),
    then ordinary part ops (fillet, hole) work on it, and re-running a changed script rebuilds them."""
    r = ok(srt.run_script("p.FCStd", BLOCK, label="block"))
    s = shape(r)
    assert r["created"] == {"units": "mm"} and r["script"]["language"] == "cadquery"
    assert s["solids"] == 1 and s["size"] == [40.0, 20.0, 10.0] and s["holes"] == [{"diameter": 6.0, "count": 1}]
    assert r["validation"]["passed"] and [i["code"] for i in r["validation"]["issues"]] == ["SCRIPT_BASE_SOLID"]
    rec = ok(srt.history("p.FCStd", seq=[r["journal_seq"]]))["records"][0]
    assert rec["tool"] == "run_script" and "box(w, 20, 10)" in rec["code"] and rec["code_sha256"]
    body = ok(srt.read_drawing("p.FCStd"))["bodies"][0]
    assert body["base"]["made_by"] == "run_script" and body["base"]["language"] == "cadquery"
    assert body["features"][0]["made_by"] == "run_script"

    r = ok(srt.apply_operations("p.FCStd", [
        {"op": "set_parameters", "params": {"r": 2}},
        {"op": "fillet", "edges": VERTICAL, "radius": "=Params.r", "tag": "round"},
        {"op": "add_sketch", "on_face": "top", "shapes": [{"type": "circle", "center": [12, 0], "diameter": 4}]},
        {"op": "hole", "sketch": "$2", "diameter": 4, "through_all": True}]))
    s2 = shape(r)
    assert s2["volume"] < s["volume"] and sorted(h["diameter"] for h in s2["holes"]) == [4.0, 6.0]
    r = ok(srt.apply_operations("p.FCStd", [{"op": "set_parameters", "params": {"r": 1}}]))
    assert s2["volume"] < shape(r)["volume"] < s["volume"]  # a smaller fillet removes less
    ok(srt.export_drawing("p.FCStd", "p.step", "step"))  # one valid solid: deliverable

    # a changed script, keeping the ops: they are rebuilt on the new, longer solid
    r = ok(srt.run_script("p.FCStd", BLOCK.replace("w = 40", "w = 60"), keep_features=True))
    assert shape(r)["size"] == [60.0, 20.0, 10.0] and len(shape(r)["holes"]) == 2
    assert "round" in json.dumps(ok(srt.read_drawing("p.FCStd"))["bodies"][0]["features"])
    assert r["changes"]["modified"] == ["ScriptSolid"] and len(r["features_kept"]) == 3
    # by default the part becomes the script's solid alone
    r = ok(srt.run_script("p.FCStd", BLOCK))
    assert shape(r)["volume"] == pytest.approx(s["volume"]) and "features_kept" not in r
    assert [f["type"] for f in ok(srt.read_drawing("p.FCStd"))["bodies"][0]["features"]] == ["FeatureBase"]
    # undo
    before = sha256_file(ws / "p.FCStd")
    ok(srt.rollback("p.FCStd"))
    assert sha256_file(ws / "p.FCStd") != before
    assert ok(srt.read_drawing("p.FCStd"))["bodies"][0]["shape"]["size"] == [60.0, 20.0, 10.0]


@needs_freecad
@needs_cadquery
@pytest.mark.parametrize("code, error, text", [
    ("import cadquery as cq\nr = cq.Workplane().box(1, 1, 1)\nresult = r.no_such_method()", "SCRIPT_FAILED",
     "AttributeError"),
    ("import cadquery as cq\nx = cq.Workplane().box(1, 1, 1)", "NO_RESULT", "result"),
    ("import cadquery as cq\nresult = cq.Workplane().rect(10, 5)", "NOT_A_SOLID", "no solid"),
    ("import cadquery as cq\nresult = cq.Workplane().box(5, 5, 5).union(cq.Workplane().box(5, 5, 5)"
     ".translate((20, 0, 0)))", "NOT_SINGLE_SOLID", "2 separate solids"),
])
def test_failed_cadquery_scripts_change_nothing(srt, ws, code, error, text):
    ok(srt.run_script("p.FCStd", BLOCK))
    before = sha256_file(ws / "p.FCStd")
    e = srt.run_script("p.FCStd", code)["error"]
    assert e["code"] == error and text in e["message"] and not e["partial_changes"], e
    if error == "SCRIPT_FAILED":  # where it failed: the script's line and the traceback's tail
        assert e["details"]["script_lines"] == ["line 3: result = r.no_such_method()"]
        assert "no_such_method" in e["details"]["traceback"]
    assert sha256_file(ws / "p.FCStd") == before
    last = journal(ws)[-1]
    assert last["tool"] == "run_script" and last["ok"] is False and last["error"]["code"] == error


@needs_cadquery
def test_cadquery_script_timeout(ws):
    rt = Runtime(Policy(root=ws, allow_scripts=True, script_timeout=2))
    e = rt.run_script("p.FCStd", "import cadquery as cq\nwhile True:\n    pass")["error"]
    assert e["code"] == "SCRIPT_TIMEOUT" and not (ws / "p.FCStd").exists()


# --- FreeCAD Part scripts --------------------------------------------------------------------------------------

@needs_freecad
def test_freecad_part_script(srt, ws):
    """language='freecad': Part code run by the FreeCAD runner; numbers are in the part's unit, like ops."""
    ok(srt.create_drawing("in.FCStd", units="in"))
    r = ok(srt.run_script("in.FCStd", "result = Part.makeBox(1, 2, 3)", language="freecad"))
    assert shape(r)["size"] == [25.4, 50.8, 76.2] and r["script"]["language"] == "freecad"
    before = sha256_file(ws / "in.FCStd")
    e = srt.run_script("in.FCStd", "x = 1\nresult = Part.makeBox(1, 1, -1)", language="freecad")["error"]
    assert e["code"] == "SCRIPT_FAILED" and e["details"]["script_lines"][-1].startswith("line 2:")
    e = srt.run_script("in.FCStd", "x = Part.makeBox(1, 1, 1)", language="freecad")["error"]
    assert e["code"] == "NO_RESULT"
    e = srt.run_script("in.FCStd", "result = Part.makeCircle(5)", language="freecad")["error"]
    assert e["code"] == "NOT_A_SOLID"
    assert sha256_file(ws / "in.FCStd") == before
    r = ok(srt.apply_operations("in.FCStd", [{"op": "chamfer", "edges": "all", "size": 0.1}]))
    assert shape(r)["volume"] < 25.4 ** 3 * 6


# --- reference images: silhouettes, alignment, IoU (no FreeCAD) ------------------------------------------------

L_SHAPE = [(0, 0), (60, 0), (60, 20), (20, 20), (20, 50), (0, 50)]


def draw(points, size, scale, offset, fill, bg=(255, 255, 255), outline=None):
    im = Image.new("RGB", size, bg)
    ImageDraw.Draw(im).polygon([(offset[0] + x * scale, offset[1] + y * scale) for x, y in points], fill=fill,
                               outline=outline)
    return im


def render_of(points, scale=3.0, offset=(30, 40), size=(300, 300)):
    """What the FreeCAD runner hands back for one view: a shaded image and the silhouette."""
    img = np.asarray(draw(points, size, scale, offset, (150, 160, 175)))
    return img, np.asarray(draw(points, size, scale, offset, (0, 0, 0))).max(axis=2) < 128


def test_silhouette_ignores_background_colour_and_thin_lines():
    im = draw(L_SHAPE, (256, 256), 2.5, (60, 50), (90, 120, 110), bg=(30, 30, 40))
    d = ImageDraw.Draw(im)
    d.line([(0, 200), (255, 200)], fill=(200, 200, 200), width=1)   # a grid line
    d.text((4, 4), "front", fill=(255, 255, 255))                   # a label
    mask, mode = compare.silhouette(np.asarray(im))
    truth = np.asarray(draw(L_SHAPE, (256, 256), 2.5, (60, 50), (0, 0, 0))).max(axis=2) < 128
    assert mode == "filled" and compare.iou(mask, truth) > 0.97
    # transparency instead of a background colour
    rgba = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).polygon([(60 + x * 2.5, 50 + y * 2.5) for x, y in L_SHAPE], fill=(250, 250, 250, 255))
    mask, _ = compare.silhouette(np.asarray(rgba.convert("RGB")), np.asarray(rgba)[:, :, 3])
    assert compare.iou(mask, truth) > 0.97
    # a line drawing: its outline is filled
    lines = draw(L_SHAPE, (256, 256), 2.5, (60, 50), None, outline=(0, 0, 0))
    mask, mode = compare.silhouette(np.asarray(lines))
    assert mode == "lines" and compare.iou(mask, truth) > 0.9


def test_alignment_ignores_framing_but_not_proportions():
    ref = draw(L_SHAPE, (256, 256), 2.0, (90, 70), (120, 130, 140), bg=(245, 245, 245))
    cells = [(np.asarray(ref), None)]
    same = compare.compare_views(cells, ["front"], [render_of(L_SHAPE, scale=4.0, offset=(20, 30))])[0][0]
    assert same["iou"] > 0.95 and same["scale"] == pytest.approx(0.5, abs=0.02)
    stretched = [(x * 1.6, y) for x, y in L_SHAPE]  # wrong proportions: one scale for both axes, so they show
    wrong = compare.compare_views(cells, ["front"], [render_of(stretched, scale=2.0)])[0][0]
    box = compare.compare_views(cells, ["front"], [render_of([(0, 0), (60, 0), (60, 50), (0, 50)])])[0][0]
    assert wrong["iou"] < 0.8 and box["iou"] < 0.8
    # a reference that crops the part on the left: scaled by the uncut axis, aligned to the uncut side
    cropped = draw(L_SHAPE, (256, 256), 3.0, (-40, 40), (120, 130, 140))
    r = compare.compare_views([(np.asarray(cropped), None)], ["front"], [render_of(L_SHAPE)])[0][0]
    assert r["reference_cropped"] == ["left"] and r["iou"] > 0.95 and r["scale"] == pytest.approx(1.0, abs=0.03)


def test_reference_grid_layout(tmp_path):
    assert [compare.grid_of(n) for n in (1, 2, 3, 4, 5, 9)] == [(1, 1), (1, 2), (2, 2), (2, 2), (2, 3), (3, 3)]
    sheet = Image.new("RGB", (200, 100), (255, 255, 255))
    sheet.paste(draw(L_SHAPE, (100, 100), 1.0, (20, 20), (0, 0, 0)), (100, 0))
    sheet.save(tmp_path / "two.png")
    cells = compare.load_reference(tmp_path / "two.png", 2)
    assert [c[0].shape for c in cells] == [(100, 100, 3), (100, 100, 3)]
    assert not compare.silhouette(*cells[0])[0].any() and compare.silhouette(*cells[1])[0].any()
    (tmp_path / "bad.png").write_bytes(b"not an image")
    with pytest.raises(AgentCADError) as exc:
        compare.load_reference(tmp_path / "bad.png", 1)
    assert exc.value.code == "BAD_REFERENCE"


# --- reference images with a real part -------------------------------------------------------------------------

PLATE = [
    {"op": "add_sketch", "plane": "XY", "shapes": [{"type": "rectangle", "center": [0, 0], "width": 80, "height": 40}]},
    {"op": "pad", "sketch": "$0", "length": 10},
    {"op": "add_sketch", "on_face": "top", "shapes": [{"type": "circle", "center": [20, 0], "diameter": 12}]},
    {"op": "pocket", "sketch": "$2", "through_all": True},
]
VIEWS = ["iso", "front", "top", "right"]


@needs_freecad
def test_preview_compared_with_a_reference(rt, ws):
    """A render of the part itself as the reference scores near 1 in every view; another part scores lower. The
    sheet holds, per view, the reference, our aligned render and the diff."""
    ok(rt.apply_operations("a.FCStd", PLATE, create={"units": "mm"}))
    ok(rt.export_drawing("a.FCStd", "ref.png", "png", views=VIEWS))
    r = ok(rt.export_drawing("a.FCStd", "self.png", "png", views=VIEWS, reference="ref.png"))
    c = r["compare"]
    assert [v["view"] for v in c["views"]] == VIEWS and all(v["iou"] > 0.95 for v in c["views"])
    assert c["mean_iou"] > 0.97 and c["reference"] == "ref.png" and "red" in c["legend"]
    assert r["grid"] == [4, 3] and Image.open(ws / "self.png").size == (3 * 256, 4 * 256)

    ok(rt.apply_operations("b.FCStd", [{"op": "primitive", "kind": "cylinder", "dims": {"radius": 20, "height": 30}}],
                           create={"units": "mm"}))
    other = ok(rt.export_drawing("b.FCStd", "other.png", "png", views=VIEWS, reference="ref.png"))["compare"]
    assert other["mean_iou"] < c["mean_iou"] - 0.3

    # one view, and the same shape twice the size is aligned onto it: only proportions count
    ok(rt.export_drawing("a.FCStd", "top.png", "png", views=["top"], image_size=300))
    ok(rt.apply_operations("big.FCStd", [dict(PLATE[0], shapes=[{"type": "rectangle", "center": [0, 0],
                                                                  "width": 160, "height": 80}]),
                                         dict(PLATE[1], length=20),
                                         dict(PLATE[2], shapes=[{"type": "circle", "center": [40, 0],
                                                                 "diameter": 24}]), PLATE[3]], create={"units": "mm"}))
    one = ok(rt.export_drawing("big.FCStd", "one.png", "png", views=["top"], reference="top.png", image_size=128))
    assert one["grid"] == [1, 3] and one["compare"]["views"][0]["iou"] > 0.97
    assert Image.open(ws / "one.png").size == (3 * 128, 128)

    plain = ok(rt.export_drawing("a.FCStd", "plain.png", "png", views=["top"]))
    assert "compare" not in plain and plain["grid"] == [1, 1]  # without a reference: the usual preview
    for kw, code in (({"reference": "missing.png"}, "FILE_NOT_FOUND"),
                     ({"reference": "ref.png", "fit": "uniform"}, "UNKNOWN_PARAM")):
        assert rt.export_drawing("a.FCStd", "x.png", "png", views=VIEWS, **kw)["error"]["code"] == code
    assert rt.export_drawing("a.FCStd", "x.step", "step", reference="ref.png")["error"]["code"] == "UNKNOWN_PARAM"


def test_mcp_tools_document_scripts_and_references(ws):
    import anyio

    from agentcad.mcp_server import INSTRUCTIONS, build_server
    tools = {t.name: t for t in anyio.run(build_server(Policy(root=ws)).list_tools)}
    assert {"language", "keep_features"} <= set(tools["run_script"].inputSchema["properties"])
    assert "reference" in tools["export_drawing"].inputSchema["properties"]
    para = INSTRUCTIONS.split("3D scripts and reference images")[1]
    assert "run_script" in para and "reference=" in para and "iou" in para
