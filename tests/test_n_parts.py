"""3D parts (.FCStd) through the same tools as drawings. Tests that build geometry need FreeCAD
(AGENTCAD_FREECAD=<FreeCAD 1.1 folder>); the rest run without it."""
from __future__ import annotations

import math
import zipfile

import pytest

from agentcad.backends import freecad
from agentcad.part.ops import PART_REGISTRY
from agentcad.store import sha256_file
from conftest import ok

needs_freecad = pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed (set AGENTCAD_FREECAD)")

PLATE = [
    {"op": "set_parameters", "params": {"width": 80, "depth": 50, "thickness": 6, "hole_d": 8}},
    {"op": "add_sketch", "plane": "XY", "tag": "base_sk",
     "shapes": [{"type": "rectangle", "corner": [0, 0], "width": "=Params.width", "height": "=Params.depth"}]},
    {"op": "pad", "sketch": "$1", "length": "=Params.thickness", "tag": "base"},
    {"op": "add_sketch", "on_face": "top", "shapes": [{"type": "circle", "center": [12, 12], "diameter": 8}]},
    {"op": "hole", "sketch": "$3", "diameter": "=Params.hole_d", "through_all": True, "tag": "h1"},
    {"op": "linear_pattern", "features": ["tag:h1"], "direction": "X", "length": 56, "occurrences": 3},
    {"op": "fillet", "edges": {"type": "line", "direction": "z"}, "radius": 3, "tag": "corners"},
]


def shape(r):
    return r["validation"]["shape"]


# --- without FreeCAD ------------------------------------------------------------------------------------------

def test_catalog_lists_part_operations(rt):
    idx = ok(rt.list_operations())
    names = {n for ops in idx["part_operations"].values() for n in ops}
    assert {"add_sketch", "pad", "pocket", "revolve", "hole", "fillet", "chamfer", "linear_pattern",
            "polar_pattern", "mirror", "set_parameters", "modify_feature"} <= names
    full = ok(rt.list_operations(category="part", ops=["fillet"]))
    assert full["operations"][0]["op"] == "fillet" and "layout" not in full["operations"][0]["params"]["properties"]
    # the 2D fillet is a different op with the same name: both come back, the part one marked
    both = ok(rt.list_operations(ops=["fillet"]))["operations"]
    assert "layout" in both[0]["params"]["properties"] and both[1]["kind"] == "part"


def test_part_ops_by_name_without_a_category(rt):
    """Agents ask for part schemas by name, often without category='part' and sometimes as one string: 37 of
    their list_operations calls failed with UNKNOWN_OPERATION in the BenchCAD runs before this."""
    for ops in (["add_sketch", "pad"], '["add_sketch","pad"]', "add_sketch, pad"):
        r = ok(rt.list_operations(ops=ops))
        assert [(o["op"], o.get("kind")) for o in r["operations"]] == [("add_sketch", "part"), ("pad", "part")]
        assert "edges" in r["conventions"]
    err = rt.list_operations(ops=["pad", "no_such_op"])["error"]
    assert err["code"] == "UNKNOWN_OPERATION" and "part operations" in err["hint"]
    err = rt.list_operations(ops=["pad"], category="draw")["error"]  # a part op under a 2D category
    assert err["code"] == "UNKNOWN_OPERATION" and "category='part'" in err["hint"]


def test_instructions_name_the_client_prefix():
    """Claude Code lists the tools as mcp__agentcad__<name>; at medium effort Opus called the bare names the
    instructions use in 90 of 100 BenchCAD tasks, and every such call failed ("No such tool available")."""
    from agentcad.mcp_server import INSTRUCTIONS
    assert "mcp__agentcad__list_operations" in INSTRUCTIONS


def test_part_schemas_share_their_conventions(rt):
    """Selector, feature-reference and dimension text is sent once in 'conventions', not in every schema."""
    import json
    from agentcad.part.ops import EDGES, FACES, PART_CONVENTIONS, REF
    r = ok(rt.list_operations(category="part"))
    ops = json.dumps(r["operations"])
    assert EDGES not in ops and FACES not in ops and REF not in ops and "a string with a unit such as" not in ops
    assert "see conventions.edges" in ops and r["conventions"] == PART_CONVENTIONS
    assert len(json.dumps(r)) < 19000  # ~22K before
    fillet = next(o for o in r["operations"] if o["op"] == "fillet")["params"]
    assert fillet["required"] == ["edges", "radius"] and "tag" in fillet["properties"]


def test_part_ops_are_checked_before_freecad_starts(rt, ws):
    (ws / "p.FCStd").write_bytes(b"")
    from agentcad.part.ops import prevalidate
    from agentcad.policy import Policy
    from agentcad.errors import AgentCADError
    pol = Policy(root=ws)
    for ops, code in (([{"op": "add_line", "start": [0, 0], "end": [1, 1]}], "UNKNOWN_OP"),
                      ([{"op": "pad", "length": 5}], "MISSING_PARAM"),
                      ([{"op": "pad", "sketch": "S", "length": 5, "layer": "X"}], "UNKNOWN_PARAM"),
                      ([{"op": "pad", "sketch": "S", "length": True}], "INVALID_LENGTH")):
        with pytest.raises(AgentCADError) as e:
            prevalidate(ops, pol)
        assert e.value.code == code and e.value.op_index == 0


def test_2d_tools_refuse_parts_and_point_at_them(rt, ws, blank):
    r = rt.apply_constraints("x.FCStd", [], "check")
    assert not r["ok"] and r["error"]["code"] == "BAD_EXTENSION" and ".FCStd" in r["error"]["message"]
    r = rt.apply_operations(blank, [{"op": "pad", "sketch": "S", "length": 5}])
    assert not r["ok"] and r["error"]["code"] == "UNKNOWN_OP"


def test_corrupt_part_is_reported_not_parsed(rt, ws):
    (ws / "bad.FCStd").write_bytes(b"not a zip")
    st = ok(rt.list_checkpoints("bad.FCStd"))
    assert st["checkpoints"] == []
    from agentcad.part.service import read_fcstd
    from agentcad.policy import Policy
    from agentcad.errors import AgentCADError
    with pytest.raises(AgentCADError) as e:
        read_fcstd(ws / "bad.FCStd", Policy(root=ws))
    assert e.value.code == "FCSTD_PARSE_ERROR"


def test_missing_freecad_is_a_dependency_error(rt, monkeypatch):
    monkeypatch.setenv("AGENTCAD_FREECAD", "Z:/no/such/freecad")
    r = rt.create_drawing("p.FCStd")
    assert not r["ok"] and r["error"]["category"] == "dependency" and "AGENTCAD_FREECAD" in r["error"]["hint"]


# --- with FreeCAD ---------------------------------------------------------------------------------------------

@pytest.fixture
def plate(rt):
    ok(rt.create_drawing("plate.FCStd"))
    r = ok(rt.apply_operations("plate.FCStd", PLATE))
    return r


@needs_freecad
def test_build_a_parametric_plate(plate, ws):
    v = plate["validation"]
    assert v["passed"], v
    s = shape(plate)
    assert s["solids"] == 1 and s["valid"] and s["size"] == [80.0, 50.0, 6.0]
    assert s["holes"] == [{"diameter": 8.0, "count": 3}]
    # volume: plate minus three holes minus the material the four 3 mm corner fillets remove
    want = 80 * 50 * 6 - 3 * math.pi * 16 * 6 - 4 * (9 - math.pi * 9 / 4) * 6
    assert s["volume"] == pytest.approx(want, rel=1e-6)
    assert [x["op"] for x in plate["results"]] == [o["op"] for o in PLATE]
    with zipfile.ZipFile(ws / "plate.FCStd") as z:
        assert "Document.xml" in z.namelist()


@needs_freecad
def test_parameter_change_regenerates_and_selectors_follow(rt, plate):
    """FreeCAD's own edge names break when the sketch changes (fillet on '?Edge2'); AgentCAD re-resolves its
    selectors, and the on-face sketch moves with the top face."""
    r = ok(rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"width": 120, "thickness": 10}}],
                               requirements=[{"type": "bbox", "size": [120, 50, 10]},
                                             {"type": "hole", "diameter": 8, "count": 3},
                                             {"type": "parameter", "name": "width", "value": 120}]))
    assert r["validation"]["passed"], r["validation"]
    feats = ok(rt.inspect_entities("plate.FCStd", filter={"kind": "features", "feature": "tag:corners"}))
    assert feats["entities"][0]["op"]["radius"] == 3 and "error" not in feats["entities"][0]
    hole_sk = ok(rt.inspect_entities("plate.FCStd", filter={"kind": "features"}))["entities"]
    on_face = [f for f in hole_sk if f["type"] == "SketchObject" and f["name"] == "Sketch001"][0]
    assert on_face["plane"]["origin"][2] == pytest.approx(10)


@needs_freecad
def test_modify_and_delete_features(rt, plate):
    r = ok(rt.apply_operations("plate.FCStd", [{"op": "modify_feature", "feature": "tag:h1", "set": {"diameter": 6}},
                                               {"op": "modify_feature", "feature": "tag:corners",
                                                "set": {"radius": 5}}]))
    assert shape(r)["holes"] == [{"diameter": 6.0, "count": 3}]
    assert r["changes"]["modified"] == ["Hole", "Fillet"]
    r = ok(rt.apply_operations("plate.FCStd", [{"op": "delete_feature", "feature": "tag:h1", "cascade": True}]))
    assert shape(r)["holes"] == [] and set(r["changes"]["deleted"]) >= {"Hole", "LinearPattern"}
    assert r["validation"]["passed"]


@needs_freecad
def test_failed_batch_leaves_the_part_untouched(rt, ws, plate):
    before = sha256_file(ws / "plate.FCStd")
    r = rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"depth": 40}},
                                            {"op": "fillet", "edges": "all", "radius": 30}])
    assert not r["ok"]
    e = r["error"]
    assert e["code"] == "FEATURE_FAILED" and e["category"] == "geometry" and e["op_index"] == 1
    assert e["hint"] and not e["partial_changes"]
    assert sha256_file(ws / "plate.FCStd") == before
    assert ok(rt.history("plate.FCStd"))["records"][-1]["ok"] is False


@needs_freecad
def test_selector_errors_are_structured(rt, plate):
    r = rt.apply_operations("plate.FCStd", [{"op": "chamfer", "edges": {"type": "circle", "radius": 99}, "size": 1}])
    assert not r["ok"] and r["error"]["code"] == "SELECTOR_EMPTY" and "inspect_entities" in r["error"]["hint"]
    r = rt.apply_operations("plate.FCStd", [{"op": "fillet", "edges": {"colour": "red"}, "radius": 1}])
    assert r["error"]["code"] == "BAD_SELECTOR"
    r = rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"t": 3}}])
    assert r["error"]["code"] == "BAD_PARAMETER_NAME" and "thickness" in r["error"]["hint"]


@needs_freecad
def test_inspect_previews_a_selector(rt, plate):
    r = ok(rt.inspect_entities("plate.FCStd", filter={"kind": "edges",
                                                      "selector": {"type": "circle", "radius": 4, "z": 6}}))
    assert r["total"] == 3 and all(e["center"][2] == 6 for e in r["entities"])
    r = ok(rt.inspect_entities("plate.FCStd", filter={"kind": "faces", "selector": "top"}))
    assert r["total"] == 1 and r["entities"][0]["normal"] == [0.0, 0.0, 1.0]


@needs_freecad
def test_revolved_shaft_with_groove_and_chamfer(rt):
    ok(rt.create_drawing("shaft.FCStd"))
    r = ok(rt.apply_operations("shaft.FCStd", [
        # half profile in the XZ plane (sketch x = X, y = Z), revolved about the sketch's vertical axis (global Z)
        {"op": "add_sketch", "plane": "XZ", "shapes": [{"type": "polygon", "points": [
            [0, 0], [10, 0], [10, 30], [6, 30], [6, 50], [0, 50]]}]},
        {"op": "revolve", "sketch": "$0", "axis": "V"},
        {"op": "add_sketch", "plane": "XZ", "shapes": [{"type": "rectangle", "corner": [9, 10], "width": 2,
                                                         "height": 2}]},
        {"op": "groove", "sketch": "$2", "axis": "V"},
        {"op": "chamfer", "edges": {"type": "circle", "radius": 6, "z": 50}, "size": 1},
    ], requirements=[{"type": "bbox", "size": [20, 20, 50]}]))
    assert r["validation"]["passed"], r["validation"]
    want = math.pi * (100 * 30 + 36 * 20) - math.pi * (100 - 81) * 2  # stepped shaft minus the groove ring
    assert shape(r)["volume"] == pytest.approx(want - _chamfer_ring(6, 1), rel=1e-6)


def _chamfer_ring(r, c):
    """Volume removed by a 45 degree chamfer of size c on the edge of a cylinder of radius r (Pappus)."""
    area = c * c / 2
    centroid = r - c / 3
    return area * 2 * math.pi * centroid


@needs_freecad
def test_rollback_diff_export(rt, ws, plate):
    ok(rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"thickness": 8}}]))
    d = ok(rt.get_diff("plate.FCStd"))
    assert d["parameters"] == {"thickness": {"old": 6.0, "new": 8.0}}
    assert d["shape"]["size"]["new"][2] == 8.0
    e = ok(rt.export_drawing("plate.FCStd", "out/plate.step", "step"))
    assert (ws / "out/plate.step").read_text("utf-8", errors="replace").startswith("ISO-10303-21")
    assert e["shape"]["size"][2] == 8.0 and e["readback"]["matches"]
    ok(rt.export_drawing("plate.FCStd", "out/plate.stl", "stl"))
    assert (ws / "out/plate.stl").stat().st_size > 1000
    ok(rt.rollback("plate.FCStd"))
    assert ok(rt.read_drawing("plate.FCStd"))["parameters"]["thickness"]["value"] == 6.0


@needs_freecad
def test_validator_enforces_the_cadbench_part_contract(rt):
    """One Body, one solid, editable PartDesign features only (the grader's gates)."""
    ok(rt.create_drawing("two.FCStd"))
    r = ok(rt.validate_drawing("two.FCStd"))
    assert not r["validation"]["passed"] and r["validation"]["issues"][0]["code"] == "NO_BODY"
    # FreeCAD 1.1 accepts a pad that makes two solids; the validator does not
    r = ok(rt.apply_operations("two.FCStd", [
        {"op": "add_sketch", "shapes": [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10},
                                         {"type": "rectangle", "corner": [20, 0], "width": 10, "height": 10}]},
        {"op": "pad", "sketch": "$0", "length": 5}]))
    v = r["validation"]
    assert not v["passed"] and [i["code"] for i in v["issues"]] == ["NOT_SINGLE_SOLID"]
    r = rt.apply_operations("two.FCStd", [{"op": "pad", "sketch": "Sketch", "length": 5}], strict=True)
    assert r["error"]["code"] == "VALIDATION_FAILED"


@needs_freecad
def test_strict_and_dry_run(rt, ws, plate):
    before = sha256_file(ws / "plate.FCStd")
    r = ok(rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"width": 90}}], dry_run=True))
    assert r["dry_run"] and r["validation"]["shape"]["size"][0] == 90
    r = rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"width": 90}}], strict=True,
                            requirements=[{"type": "bbox", "size": [80, 50, 6]}])
    assert not r["ok"] and r["error"]["code"] == "VALIDATION_FAILED", r["error"]
    assert sha256_file(ws / "plate.FCStd") == before


@needs_freecad
def test_primitives_mirror_and_shell(rt):
    ok(rt.create_drawing("box.FCStd"))
    r = ok(rt.apply_operations("box.FCStd", [
        {"op": "primitive", "kind": "box", "dims": {"length": 40, "width": 30, "height": 20}},
        {"op": "primitive", "kind": "cylinder", "subtractive": True, "dims": {"radius": 3, "height": 20},
         "position": [10, 15, 0], "tag": "pin"},
        {"op": "mirror", "features": ["tag:pin"], "plane": "YZ"},
    ]))
    # the mirror lands at x = -10, outside the box: it cuts nothing, so one hole
    assert shape(r)["holes"] == [{"diameter": 6.0, "count": 1}]
    r = ok(rt.apply_operations("box.FCStd", [{"op": "thickness", "faces": "top", "thickness": 2}]))
    assert shape(r)["volume"] < 40 * 30 * 20 / 2 and r["validation"]["passed"]


def test_part_registry_ops_are_part_only():
    assert all(not d.common_all for d in PART_REGISTRY.values())


@needs_freecad
def test_pocket_polar_pattern_loft_sweep_helix(rt):
    ok(rt.create_drawing("disc.FCStd"))
    r = ok(rt.apply_operations("disc.FCStd", [
        {"op": "add_sketch", "shapes": [{"type": "circle", "center": [0, 0], "diameter": 100}]},
        {"op": "pad", "sketch": "$0", "length": 10},
        {"op": "add_sketch", "on_face": "top", "shapes": [{"type": "rectangle", "center": [0, 0], "width": 20,
                                                           "height": 20}]},
        {"op": "pocket", "sketch": "$2", "depth": 4},
        {"op": "add_sketch", "on_face": "top", "shapes": [{"type": "circle", "center": [40, 0], "diameter": 6}]},
        {"op": "pocket", "sketch": "$4", "through_all": True, "tag": "bolt"},
        {"op": "polar_pattern", "features": ["tag:bolt"], "axis": "Z", "occurrences": 8},
    ]))
    assert shape(r)["holes"] == [{"diameter": 6.0, "count": 8}]
    assert shape(r)["volume"] == pytest.approx(math.pi * 2500 * 10 - 400 * 4 - 8 * math.pi * 9 * 10, rel=1e-6)

    ok(rt.create_drawing("loft.FCStd"))
    r = ok(rt.apply_operations("loft.FCStd", [
        {"op": "add_sketch", "shapes": [{"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}]},
        {"op": "add_sketch", "offset": 30, "shapes": [{"type": "rectangle", "center": [0, 0], "width": 10,
                                                       "height": 10}]},
        {"op": "loft", "sections": ["$0", "$1"], "ruled": True},
    ]))
    # ruled loft between squares = frustum of a pyramid: h/3 (A1 + A2 + sqrt(A1 A2))
    assert shape(r)["volume"] == pytest.approx(30 / 3 * (400 + 100 + 200), rel=1e-6)

    ok(rt.create_drawing("rod.FCStd"))
    r = ok(rt.apply_operations("rod.FCStd", [
        {"op": "add_sketch", "shapes": [{"type": "circle", "center": [0, 0], "radius": 2}]},
        {"op": "add_sketch", "plane": "XZ", "shapes": [{"type": "line", "start": [0, 0], "end": [0, 30]}]},
        {"op": "sweep", "sketch": "$0", "path": "$1"},
    ]))
    assert shape(r)["volume"] == pytest.approx(math.pi * 4 * 30, rel=1e-6)

    ok(rt.create_drawing("spring.FCStd"))
    r = ok(rt.apply_operations("spring.FCStd", [
        {"op": "add_sketch", "plane": "XZ", "shapes": [{"type": "circle", "center": [10, 0], "radius": 1}]},
        {"op": "helix", "sketch": "$0", "axis": "V", "pitch": 5, "height": 20},
    ]))
    # Pappus along the helix: profile area x path length of its centre (4 turns of radius 10, pitch 5)
    want = math.pi * 1 * 4 * math.hypot(2 * math.pi * 10, 5)
    assert shape(r)["solids"] == 1 and shape(r)["volume"] == pytest.approx(want, rel=0.02)


@needs_freecad
def test_create_in_one_call_and_batch(rt):
    r = ok(rt.apply_operations("one.FCStd", PLATE[:3], create={"units": "mm"}))
    assert shape(r)["size"] == [80.0, 50.0, 6.0]
    r = ok(rt.apply_batch([{"path": "one.FCStd", "operations": [{"op": "set_parameters", "params": {"width": 60}}]},
                           {"path": "two.dxf", "create": {"units": "mm"},
                            "operations": [{"op": "add_line", "start": [0, 0], "end": [10, 0]}]}]))
    assert r["succeeded"] == 2, r


def _plate_volume(t):
    return 80 * 50 * t - 3 * math.pi * 16 * t - 4 * (9 - math.pi * 9 / 4) * t


@needs_freecad
def test_step_export_reads_back_as_the_part(rt, ws, plate):
    """BenchCAD scores the STEP by voxel IoU, so the file itself must hold the part: read it back in a separate
    FreeCAD job (Part.read, no FCStd involved) and compare with the known plate."""
    ok(rt.export_drawing("plate.FCStd", "plate.step", "step"))
    got = freecad.run({"action": "read_shape"}, inputs={"input": ws / "plate.step"})
    assert got["ok"], got
    s = got["shape"]
    assert s["valid"] and s["solids"] == 1
    assert s["volume"] == pytest.approx(_plate_volume(6), rel=1e-6)
    assert s["bbox"] == [[0.0, 0.0, 0.0], [80.0, 50.0, 6.0]]
    # BREP keeps the solid; IGES holds faces only, so its readback compares volume and size
    e = ok(rt.export_drawing("plate.FCStd", "plate.brep", "brep"))
    assert e["readback"]["solids"] == 1 and e["readback"]["matches"]
    e = ok(rt.export_drawing("plate.FCStd", "plate.igs", "iges"))
    assert e["readback"]["matches"] and e["readback"]["solids"] == 0 and "IGES" in e["readback"]["note"]
    assert e["readback"]["volume"] == pytest.approx(_plate_volume(6), rel=1e-6)


@needs_freecad
def test_export_refuses_a_part_that_is_not_one_solid(rt, ws):
    ok(rt.apply_operations("two.FCStd", [
        {"op": "add_sketch", "shapes": [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10},
                                         {"type": "rectangle", "corner": [20, 0], "width": 10, "height": 10}]},
        {"op": "pad", "sketch": "$0", "length": 5}], create={"units": "mm"}))
    r = rt.export_drawing("two.FCStd", "two.step", "step")
    assert not r["ok"] and r["error"]["code"] == "NOT_EXPORTABLE" and r["error"]["category"] == "geometry"
    assert not (ws / "two.step").exists()
    # the preview still renders, to show what went wrong
    r = ok(rt.export_drawing("two.FCStd", "two.png", "png", views=["top"], image_size=64))
    assert r["shape"]["solids"] == 2 and (ws / "two.png").stat().st_size > 0


@needs_freecad
def test_requirement_fields_are_checked(rt, plate):
    r = ok(rt.validate_drawing("plate.FCStd", requirements=[
        {"type": "bbox", "size": [6, 80, 50], "any_orientation": True},
        {"type": "bbox", "size": [6, 80, 50]},
        {"type": "feature_count", "feature_type": "Pad"},
        {"type": "volume"},
        {"type": "feature_count", "feature_type": "Fillet", "count": 1},
    ], detail=True))["validation"]
    res = r["requirements"]
    assert [x["passed"] for x in res] == [True, False, False, False, True]
    assert "count or min" in res[2]["message"] and "value" in res[3]["message"]
    assert not any("any_orientation" in w for w in r["warnings"])


@needs_freecad
def test_inch_part_reports_parameters_in_inches(rt):
    r = ok(rt.apply_operations("in.FCStd", [
        {"op": "set_parameters", "params": {"w": 2, "height": "1in"}},
        {"op": "add_sketch", "shapes": [{"type": "rectangle", "corner": [0, 0], "width": "=Params.w",
                                         "height": "=Params.height"}]},
        {"op": "pad", "sketch": "$1", "length": 0.5}],
        create={"units": "in"}, requirements=[{"type": "parameter", "name": "w", "value": 2}]))
    assert r["validation"]["passed"], r["validation"]
    assert shape(r)["size"] == [50.8, 25.4, 12.7]  # geometry is reported in mm
    assert ok(rt.read_drawing("in.FCStd"))["parameters"]["height"]["value"] == pytest.approx(1)


@needs_freecad
def test_create_is_part_of_the_batch(rt, ws):
    r = ok(rt.apply_operations("new.FCStd", PLATE[:3], create={"units": "mm"}, dry_run=True))
    assert r["dry_run"] and r["validation"]["shape"]["size"] == [80.0, 50.0, 6.0]
    assert not (ws / "new.FCStd").exists()
    r = rt.apply_operations("new.FCStd", PLATE[:3] + [{"op": "fillet", "edges": "all", "radius": 40}],
                            create={"units": "mm"})
    assert not r["ok"] and r["error"]["op_index"] == 3
    assert not (ws / "new.FCStd").exists()  # a failed batch leaves no empty part behind
    r = ok(rt.apply_operations("new.FCStd", PLATE[:3], create={"units": "mm"}))
    assert r["created"] == {"units": "mm"} and ok(rt.history("new.FCStd"))["records"][-1]["ok"]


@needs_freecad
def test_png_preview(rt, ws, plate):
    """Shaded parallel projection, part centred and filling the frame: in the top view of the 80 x 50 plate a
    hole centre is background and solid material is shaded."""
    from PIL import Image
    r = ok(rt.export_drawing("plate.FCStd", "top.png", "png", views=["top"], image_size=256))
    assert r["views"] == ["top"] and r["grid"] == [1, 1]
    im = Image.open(ws / "top.png").convert("RGB")
    assert im.size == (256, 256)
    k = 256 * 0.9 / 80  # the longer side spans 90 % of the frame

    def px(x, y):
        return im.getpixel((int((x - 40) * k + 128), int(128 - (y - 25) * k)))

    assert px(12, 12) == (255, 255, 255)  # through hole
    assert max(px(30, 30)) < 250  # material
    assert px(40, 25 + 26) == (255, 255, 255) and px(40 + 41, 25) == (255, 255, 255)  # just outside the part
    r = ok(rt.export_drawing("plate.FCStd", "four.png", "png", views=["iso", "front", [1, 1, 1], "right"],
                             image_size=128, fit="uniform"))
    assert r["grid"] == [2, 2] and Image.open(ws / "four.png").size == (256, 256)
    assert r["views"][2] == "[1,1,1]"
    bad = rt.export_drawing("plate.FCStd", "x.png", "png", views=["sideways"])
    assert bad["error"]["code"] == "BAD_VIEW" and "iso" in bad["error"]["hint"]
    bad = rt.export_drawing("plate.FCStd", "x.step", "step", views=["iso"])
    assert bad["error"]["code"] == "UNKNOWN_PARAM"


@needs_freecad
@pytest.mark.parametrize("extra", [
    {"op": "primitive", "kind": "sphere", "dims": {"radius": 10}, "position": [0, 0, 40]},
    {"op": "primitive", "kind": "cone", "dims": {"radius1": 6, "radius2": 0, "height": 12}, "position": [0, 0, 40]},
    {"op": "primitive", "kind": "torus", "dims": {"radius1": 4, "radius2": 2}, "position": [0, 0, 20]},
])
def test_preview_and_edge_selection_skip_degenerate_edges(rt, ws, extra):
    """A sphere's or cone's pole is an edge without a curve (FreeCAD raises "undefined curve type" on e.Curve):
    previews and edge selectors skip it instead of failing."""
    ok(rt.create_drawing("knob.FCStd"))
    ok(rt.apply_operations("knob.FCStd", [
        {"op": "primitive", "kind": "cylinder", "dims": {"radius": 3, "height": 40}}, extra]))
    r = ok(rt.export_drawing("knob.FCStd", "knob.png", "png", views=["iso", [-1, -1, -1]], image_size=96))
    assert r["grid"] == [1, 2] and (ws / "knob.png").stat().st_size > 0
    if extra["kind"] == "sphere":  # default sizes: 512 for one view, 256 per view in a grid
        from PIL import Image
        assert ok(rt.export_drawing("knob.FCStd", "one.png", "png"))["cell_size"] == 512
        r = ok(rt.export_drawing("knob.FCStd", "four.png", "png", views=[[-1, -1, -1], [1, 1, 1], [1, -1, 1],
                                                                          [-1, 1, -1]]))
        assert r["cell_size"] == 256 and Image.open(ws / "four.png").size == (512, 512)
    ok(rt.export_drawing("knob.FCStd", "knob.step", "step"))
    r = rt.apply_operations("knob.FCStd", [{"op": "fillet", "edges": {"type": "circle", "radius": 3}, "radius": 1}],
                            dry_run=True)
    assert r["ok"] or r["error"]["code"] != "FREECAD_ERROR", r


@needs_freecad
def test_mcp_returns_png_inline(ws):
    """export_drawing(png) over MCP: the JSON envelope first, then the image, so an agent sees its part without a
    file viewer. inline_image=false returns the JSON alone."""
    import asyncio
    import json
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        env = {**os.environ, "AGENTCAD_ROOT": str(ws)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await s.call_tool("apply_operations", {"path": "p.FCStd", "create": {"units": "mm"}, "operations": [
                    {"op": "primitive", "kind": "box", "dims": {"length": 20, "width": 10, "height": 5}}]})
                a = await s.call_tool("export_drawing", {"path": "p.FCStd", "output": "p.png", "format": "png",
                                                         "image_size": 64})
                b = await s.call_tool("export_drawing", {"path": "p.FCStd", "output": "q.png", "format": "png",
                                                         "image_size": 64, "inline_image": False})
                return a.content, b.content

    a, b = asyncio.run(run())
    assert [c.type for c in a] == ["text", "image"] and a[1].mimeType == "image/png"
    assert json.loads(a[0].text)["ok"] and json.loads(a[0].text)["output"] == "p.png"
    assert [c.type for c in b] == ["text"] and json.loads(b[0].text)["ok"]


@needs_freecad
@pytest.mark.parametrize("shapes, axis, volume", [
    # half disk on the axis, as a bulge polygon and as arc + line: a sphere of radius 10
    ([{"type": "polygon", "points": [[10, 0, 1], [-10, 0]]}], "H", 4 / 3 * math.pi * 1000),
    ([{"type": "arc", "center": [0, 0], "radius": 10, "start_angle": 0, "end_angle": 180},
      {"type": "line", "start": [-10, 0], "end": [10, 0]}], "H", 4 / 3 * math.pi * 1000),
    # half disk 5 off the axis (Pappus: area x 2 pi x centroid distance)
    ([{"type": "polygon", "points": [[5, 0, 1], [5, 20]]}], "V",
     math.pi * 100 / 2 * 2 * math.pi * (5 + 40 / (3 * math.pi))),
])
def test_half_circle_profiles(rt, shapes, axis, volume):
    """A 180 degree arc's end points already fix its radius, so the sketch locks the centre instead: before,
    every half circle failed with SKETCH_OVERCONSTRAINED (the usual profile for a knob, a dome or a sphere)."""
    ok(rt.create_drawing("half.FCStd"))
    r = ok(rt.apply_operations("half.FCStd", [{"op": "add_sketch", "plane": "XZ", "shapes": shapes},
                                              {"op": "revolve", "sketch": "$0", "axis": axis}]))
    s = shape(r)
    assert s["solids"] == 1 and s["valid"] and s["volume"] == pytest.approx(volume, rel=1e-6)


@needs_freecad
@pytest.mark.parametrize("deg", [179.9, 180, 180.01, 270])
def test_arcs_around_half_a_turn(rt, deg):
    """Arcs either side of 180 degrees keep their radius constraint and build the exact circular segment."""
    a = math.radians(deg)
    ok(rt.create_drawing("seg.FCStd"))
    r = ok(rt.apply_operations("seg.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [
            {"type": "arc", "center": [0, 0], "radius": 10, "start_angle": 0, "end_angle": deg},
            {"type": "line", "start": [10 * math.cos(a), 10 * math.sin(a)], "end": [10, 0]}]},
        {"op": "pad", "sketch": "$0", "length": 1}]))
    assert shape(r)["volume"] == pytest.approx(50 * (a - math.sin(a)), rel=1e-6)


@needs_freecad
@pytest.mark.parametrize("b", [-2, -1, -0.5, 0.5, 1, 2])
@pytest.mark.parametrize("ang", [0, 45, 210])
def test_bulge_arcs_any_sign_and_size(rt, b, ang):
    """A bulge polygon edge is the DXF arc: + counter-clockwise, - clockwise, |b| > 1 more than half a turn. A
    clockwise arc used to come out as the other arc of its circle and a major arc on the wrong side of its chord,
    with no error: the segment's area shows which arc was built."""
    a = math.radians(ang)
    p1, p2 = [7, -3], [7 + 20 * math.cos(a), -3 + 20 * math.sin(a)]
    ok(rt.create_drawing("seg.FCStd"))
    r = ok(rt.apply_operations("seg.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [{"type": "polygon", "points": [p1 + [b], p2]}]},
        {"op": "pad", "sketch": "$0", "length": 1}]))
    th = 4 * math.atan(abs(b))
    rad = 20 / (2 * math.sin(th / 2))
    assert shape(r)["volume"] == pytest.approx(rad * rad / 2 * (th - math.sin(th)), rel=1e-6)
    # the arc bulges to the right of p1 -> p2 when counter-clockwise, to the left when clockwise
    side = -1 if b > 0 else 1
    bb = shape(r)["bbox"]
    mid = [(p1[0] + p2[0]) / 2 + side * math.sin(-a) * 0.5, (p1[1] + p2[1]) / 2 + side * math.cos(a) * 0.5]
    assert bb[0][0] - 1e-6 <= mid[0] <= bb[1][0] + 1e-6 and bb[0][1] - 1e-6 <= mid[1] <= bb[1][1] + 1e-6


@needs_freecad
def test_concave_bulge_profile(rt):
    """A 40 x 20 rectangle whose top edge bows inwards (bulge -0.5 going right to left is clockwise, into the
    rectangle): the area is the rectangle minus the segment."""
    ok(rt.create_drawing("c.FCStd"))
    r = ok(rt.apply_operations("c.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [
            {"type": "polygon", "points": [[0, 0], [40, 0], [40, 20, -0.5], [0, 20]]}]},
        {"op": "pad", "sketch": "$0", "length": 1}]))
    th = 4 * math.atan(0.5)
    rad = 40 / (2 * math.sin(th / 2))
    assert shape(r)["volume"] == pytest.approx(800 - rad * rad / 2 * (th - math.sin(th)), rel=1e-6)


@needs_freecad
@pytest.mark.parametrize("end", [[30, 0], [21.2132034, 21.2132034]])
def test_slot(rt, end):
    """A slot is two half circles and two lines (it failed as over-constrained before half circles were fixed):
    length 30 between centres, width 8, along X and at 45 degrees."""
    ok(rt.create_drawing("s.FCStd"))
    r = ok(rt.apply_operations("s.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [{"type": "slot", "start": [0, 0], "end": end, "width": 8}]},
        {"op": "pad", "sketch": "$0", "length": 2}]))
    assert shape(r)["volume"] == pytest.approx((30 * 8 + math.pi * 16) * 2, rel=1e-6)
