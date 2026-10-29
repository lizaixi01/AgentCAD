"""3D parts built by scripts (run_script on a .FCStd: CadQuery or FreeCAD Part code) and previews compared with a
reference image (export_drawing(..., "png", reference=...)). Tests that build geometry need FreeCAD
(AGENTCAD_FREECAD); CadQuery tests also need the optional extra agentcad-runtime[cadquery]. The image comparison
itself is tested on synthetic images without either."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

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

@pytest.mark.parametrize("language", [None, "cadquery", "freecad"])
def test_part_scripts_are_off_by_default(rt, ws, language):
    e = rt.run_script("p.FCStd", "result = Part.makeBox(1, 1, 1)", language=language)["error"]
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
    ("import numpy as np\nnp.savez('x.npz', a=1)", "'savez'"),
    ("import numpy as np\nm = np.memmap('x.bin', mode='w+', shape=(4,))", "'memmap'"),
    ("from cadquery.vis import show", "cadquery.vis"),
])
def test_part_scripts_are_checked_before_running(srt, ws, code, why):
    e = srt.run_script("p.FCStd", code)["error"]
    assert e["code"] == "SCRIPT_REJECTED" and why in e["message"], e
    assert "result" in e["hint"] and not (ws / "p.FCStd").exists()


@pytest.mark.parametrize("code, why", [
    ("doc = App.activeDocument()", "'activeDocument'"),
    ("doc = FreeCAD.ActiveDocument", "'ActiveDocument'"),
    ("App.setActiveDocument('Part')", "'setActiveDocument'"),
    ("App.ParamGet('User parameter:BaseApp')", "'ParamGet'"),
    ("result = Part.read('x.brep')", "'read'"),
    ("Part.makeBox(1, 1, 1).exportStep('x.step')", "'exportStep'"),
])
def test_freecad_scripts_are_checked_before_running(srt, ws, code, why):
    e = srt.run_script("p.FCStd", code, language="freecad")["error"]
    assert e["code"] == "SCRIPT_REJECTED" and why in e["message"], e
    assert not (ws / "p.FCStd").exists()


def test_script_languages(srt, ws):
    e = srt.run_script("p.FCStd", BLOCK, language="ezdxf")["error"]
    assert e["code"] == "BAD_LANGUAGE" and "cadquery" in e["hint"]
    ok(srt.create_drawing("d.dxf"))
    e = srt.run_script("d.dxf", BLOCK, language="cadquery")["error"]
    assert e["code"] == "BAD_LANGUAGE"
    e = srt.run_script("d.dxf", "x = 1", keep_features=True)["error"]
    assert e["code"] == "UNKNOWN_PARAM"


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
    """language='freecad': Part code run by a FreeCAD process of its own; numbers are in the part's unit, like
    ops, and the result reports the solid in mm, like validation."""
    ok(srt.create_drawing("in.FCStd", units="in"))
    r = ok(srt.run_script("in.FCStd", "result = Part.makeBox(1, 2, 3)", language="freecad"))
    assert shape(r)["size"] == [25.4, 50.8, 76.2] and r["script"]["language"] == "freecad"
    assert r["script"]["solid"]["size"] == [25.4, 50.8, 76.2] and r["script"]["solid"]["unit"] == "mm"
    assert not list((ws / ".agentcad" / "freecad").glob("script-*"))  # its working folder is removed
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


@needs_freecad
def test_freecad_script_cannot_reach_the_part(srt, ws):
    """The script runs where no document is open: Part.show adds its shape to a document of that process only."""
    r = ok(srt.run_script("s.FCStd", "result = Part.makeBox(10, 20, 30)\nPart.show(result)", language="freecad"))
    assert r["validation"]["passed"] and [i["code"] for i in r["validation"]["issues"]] == ["SCRIPT_BASE_SOLID"]
    read = ok(srt.read_drawing("s.FCStd"))
    assert "outside_bodies" not in read and read["bodies"][0]["shape"]["size"] == [10.0, 20.0, 30.0]


SPRING = """
helix = Part.makeHelix(8, 40, 10)
e = helix.Edges[0]
ring = Part.Wire(Part.makeCircle(1.5, e.valueAt(e.FirstParameter), e.tangentAt(e.FirstParameter)))
result = Part.Wire(helix.Edges).makePipeShell([ring], True, True)
"""


@needs_freecad
def test_swept_parts_report_their_true_size(srt, ws):
    """A coil of 1.5 mm wire on radius 10 is 23 mm across. FreeCAD's quick bounding box follows the sweep's B-spline
    control points (29.2 mm here, 57% too wide on a BenchCAD spring), and sizes, bbox requirements, previews and
    the export check all used it."""
    height = 40 + 3 * math.cos(math.atan(8 / (20 * math.pi)))  # the end circles are normal to the helix
    want = [23, 23, height]
    r = ok(srt.run_script("spring.FCStd", SPRING, language="freecad",
                          requirements=[{"type": "bbox", "size": want, "tolerance": 0.01}]))
    assert r["validation"]["passed"], r["validation"]
    assert shape(r)["size"] == pytest.approx(want, abs=1e-3)
    assert r["script"]["solid"]["size"] == pytest.approx(want, abs=1e-3)
    e = ok(srt.export_drawing("spring.FCStd", "spring.step", "step"))
    assert e["readback"]["matches"] and e["readback"]["size"] == pytest.approx(want, abs=1e-3)


@needs_freecad
def test_cross_drilled_pin_exports_to_step(srt, ws):
    """A pin with two cross holes reads back from its STEP with a volume 2.6e-6 off (OCC integrates the volume
    numerically) and a quick bounding box 0.0005 mm wider. The export check refused that as EXPORT_MISMATCH, as it
    did with parts in BenchCAD runs."""
    pin = ("pin = Part.makeCylinder(5.5, 50)\nfor z in (4, 46):\n"
           "    pin = pin.cut(Part.makeCylinder(1, 20, Vector(0, 10, z), Vector(0, -1, 0)))\nresult = pin")
    ok(srt.run_script("pin.FCStd", pin, language="freecad"))
    e = ok(srt.export_drawing("pin.FCStd", "pin.step", "step"))
    assert e["readback"]["matches"] and e["readback"]["size"] == [11.0, 11.0, 50.0]
    assert e["readback"]["faces"] == e["shape"]["faces"]


@needs_freecad
def test_a_reported_face_box_selects_that_face(srt, ws):
    """The SELECTOR_EMPTY hint sends agents to inspect_entities for face boxes, so each face's reported bbox, used as
    a "box" selector, must select that face: also a fillet's torus and a sweep's B-spline tube, whose exact boxes
    are smaller than the box selectors test."""
    ok(srt.run_script("spring.FCStd", SPRING, language="freecad"))
    ok(srt.apply_operations("fil.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [{"type": "circle", "center": [0, 0], "diameter": 20}]},
        {"op": "pad", "sketch": "$0", "length": 30},
        {"op": "fillet", "edges": {"type": "circle", "z": 30}, "radius": 3}], create={"units": "mm"}))
    for path in ("spring.FCStd", "fil.FCStd"):
        for f in ok(srt.inspect_entities(path, filter={"kind": "faces"}))["entities"]:
            hits = ok(srt.inspect_entities(path, filter={"kind": "faces", "selector": {"box": f["bbox"]}}))
            assert f["name"] in [h["name"] for h in hits["entities"]], (path, f)


def add_stray_shape(part):
    """Add a Part::Feature outside the Body with FreeCAD itself, as a hand edit in FreeCAD would."""
    cmd, extra = freecad.require()
    with tempfile.TemporaryDirectory() as td:  # FreeCAD saves in a short folder (Windows path limit)
        work = Path(td) / "p.FCStd"
        shutil.copy2(part, work)
        script = Path(td) / "stray.py"
        script.write_text(
            "import os, sys\n"
            "for lib in filter(None, os.environ.get('AGENTCAD_FREECAD_LIB', '').split(os.pathsep)):\n"
            "    sys.path.insert(0, lib)\n"
            "import FreeCAD as App, Part\n"
            "doc = App.openDocument(os.environ['STRAY_PART'])\n"
            "doc.addObject('Part::Feature', 'Stray').Shape = Part.makeBox(1, 1, 1)\n"
            "doc.recompute()\n"
            "doc.save()\n", "utf-8")
        subprocess.run(cmd + [str(script)], env={**os.environ, **extra, "STRAY_PART": str(work)}, check=True,
                       timeout=180, capture_output=True)
        shutil.copy2(work, part)


@needs_freecad
def test_validation_flags_geometry_outside_the_body(rt, ws):
    ok(rt.apply_operations("p.FCStd", [{"op": "primitive", "kind": "box",
                                        "dims": {"length": 10, "width": 10, "height": 10}}], create={"units": "mm"}))
    add_stray_shape(ws / "p.FCStd")
    v = ok(rt.validate_drawing("p.FCStd"))["validation"]
    stray = [i for i in v["issues"] if i["code"] == "GEOMETRY_OUTSIDE_BODY"]
    assert not v["passed"] and stray and stray[0]["severity"] == "error" and stray[0]["entities"] == ["Stray"]


@needs_freecad
def test_failed_or_unsaved_part_scripts_change_nothing(srt, ws):
    """dry_run on a missing part writes nothing; strict with a failing requirement, and kept features that no
    longer fit the new solid, leave the part as it was; the script's base is not an editable feature."""
    box = "result = Part.makeBox(40, 20, 10)"
    r = ok(srt.run_script("p.FCStd", box, language="freecad", dry_run=True))
    assert r["dry_run"] and shape(r)["size"] == [40.0, 20.0, 10.0] and not (ws / "p.FCStd").exists()
    ok(srt.run_script("p.FCStd", box, language="freecad"))
    ok(srt.apply_operations("p.FCStd", [{"op": "fillet", "edges": VERTICAL, "radius": 4}]))
    before = sha256_file(ws / "p.FCStd")
    e = srt.run_script("p.FCStd", box.replace("40, 20", "40, 21"), language="freecad", strict=True,
                       requirements=[{"type": "bbox", "size": [40, 20, 10]}])["error"]
    assert e["code"] == "VALIDATION_FAILED"
    e = srt.run_script("p.FCStd", "result = Part.makeBox(5, 5, 10)", language="freecad", keep_features=True)["error"]
    assert e["code"] == "FEATURE_FAILED" and "Fillet" in e["entities"]
    for op, code in (({"op": "modify_feature", "feature": "ScriptSolid", "set": {"length": 5}}, "NOT_EDITABLE"),
                     ({"op": "modify_feature", "feature": "BaseFeature", "set": {"length": 5}}, "NOT_EDITABLE"),
                     ({"op": "delete_feature", "feature": "ScriptSolid"}, "NOT_A_FEATURE"),
                     ({"op": "delete_feature", "feature": "BaseFeature"}, "NOT_A_FEATURE")):
        e = srt.apply_operations("p.FCStd", [op])["error"]
        assert e["code"] == code and "run_script" in e["message"], (op, e)
    assert sha256_file(ws / "p.FCStd") == before


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


def test_large_references_are_scaled_down_and_fast(tmp_path):
    """A 3072 px sheet (reviewed: 79 s for one view before) is scaled to 1024 px cells first; the silhouettes of all
    four cells then take well under a second."""
    big = Image.new("RGB", (3072, 3072), (255, 255, 255))
    for c in range(2):
        for r in range(2):
            big.paste(draw(L_SHAPE, (1536, 1536), 18.0, (200, 200), (90, 100, 120)), (c * 1536, r * 1536))
    big.save(tmp_path / "big.png")
    t0 = time.perf_counter()
    cells = compare.load_reference(tmp_path / "big.png", 4)
    masks = [compare.silhouette(rgb, a)[0] for rgb, a in cells]
    assert time.perf_counter() - t0 < 10
    assert [c[0].shape for c in cells] == [(1024, 1024, 3)] * 4
    truth = np.asarray(draw(L_SHAPE, (1024, 1024), 12.0, (133, 133), (0, 0, 0))).max(axis=2) < 128
    assert all(compare.iou(m, truth) > 0.97 for m in masks)


@pytest.mark.parametrize("size, n, why", [
    ((6000, 5000), 1, "megapixels"),     # 30 MP: refused from the header, before decoding
    ((40000, 16), 1, "8:1"),             # a 2 KB file whose sheet would have needed gigabytes
    ((16, 4000), 4, "too small"),
])
def test_reference_limits(tmp_path, size, n, why):
    Image.new("1", size, 1).save(tmp_path / "ref.png")
    t0 = time.perf_counter()
    with pytest.raises(AgentCADError) as exc:
        compare.load_reference(tmp_path / "ref.png", n)
    assert exc.value.code == "BAD_REFERENCE" and why in exc.value.message and time.perf_counter() - t0 < 2


def test_compare_sheet_stays_bounded(tmp_path):
    rows = [[np.full((128, 1024, 3), 255, np.uint8)] * 3 for _ in range(9)]  # nine 8:1 cells
    grid, cell = compare.save_sheet(rows, [["a", "b", "c"]] * 9, tmp_path / "s.png", 1024)
    w, h = Image.open(tmp_path / "s.png").size
    assert grid == [9, 3] and cell < 1024 and w <= compare.SHEET_MAX_SIDE and h <= compare.SHEET_MAX_SIDE
    assert w * h <= compare.SHEET_MAX_PIXELS


def fake_part(path):
    """Enough of a .FCStd for the checks made before FreeCAD starts."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Document.xml", "<Document/>")


@pytest.mark.parametrize("kw, code", [
    ({"image_size": 5000}, "OUT_OF_RANGE"),
    ({"image_size": 10}, "OUT_OF_RANGE"),
    ({"image_size": True}, "OUT_OF_RANGE"),
    ({"reference": "../outside.png"}, "PATH_OUTSIDE_WORKSPACE"),
    ({"reference": "big.png"}, "BAD_REFERENCE"),
    ({"fit": "uniform"}, "UNKNOWN_PARAM"),
])
def test_compare_arguments_are_checked_before_rendering(rt, ws, kw, code):
    """Checked by the runtime itself (the MCP schema is not the only caller), before FreeCAD is started."""
    fake_part(ws / "p.FCStd")
    Image.new("RGB", (256, 256), (255, 255, 255)).save(ws / "ref.png")
    if kw.get("reference") == "big.png":
        Image.new("1", (8000, 8000), 1).save(ws / "big.png")
    args = {"views": ["top"], "reference": "ref.png", **kw}
    e = rt.export_drawing("p.FCStd", "cmp.png", "png", **args)["error"]
    assert e["code"] == code, e
    assert not (ws / "cmp.png").exists()


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


@needs_freecad
def test_freecad_script_timeout_leaves_no_folder(ws):
    """A FreeCAD script that runs too long is killed and waited for, so its working folder (console.log
    included) is removed like after any other script."""
    rt = Runtime(Policy(root=ws, allow_scripts=True, script_timeout=3))
    e = rt.run_script("p.FCStd", "while True:\n    pass", language="freecad")["error"]
    assert e["code"] == "SCRIPT_TIMEOUT" and not (ws / "p.FCStd").exists()
    assert not list((ws / ".agentcad" / "freecad").glob("script-*"))
