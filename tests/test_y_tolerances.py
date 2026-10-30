import ezdxf
import pytest

from agentcad.service import Runtime


@pytest.mark.parametrize("kind", ["linear", "diameter", "radius"])
@pytest.mark.parametrize("mode", ["deviations", "limits"])
def test_native_tolerance_survives_reopen_edit_and_delivery(rt, ws, blank, kind, mode):
    deviation = {"lower": -0.012, "upper": 0.025, "mode": mode, "precision": 3}
    dim = {"op": f"add_{kind}_dim", "tolerance": deviation, "tag": "toleranced"}
    if kind == "linear":
        geometry = {"op": "add_line", "start": [0, 0], "end": [50, 0]}
        dim.update(p1=[0, 0], p2=[50, 0])
    else:
        geometry = {"op": "add_circle", "center": [0, 0], "radius": 25}
        dim.update(target="$0")
    result = rt.apply_operations(blank, [geometry, dim])
    assert result["ok"], result
    actual = Runtime(rt.policy).inspect_entities(blank, {"tag": "toleranced"})["entities"][0]
    assert actual["tolerance"] == {**deviation, "units": "displayed drawing units"}
    doc = ezdxf.readfile(ws / blank)
    entity = doc.entitydb[actual["id"]]
    assert entity.override().get("dimtp") == 0.025
    assert entity.override().get("dimtm") == 0.012
    picture = doc.blocks.get(entity.dxf.geometry)
    text = " ".join(e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text for e in picture.query("TEXT MTEXT"))
    assert "025" in text and ("012" in text if mode == "deviations" else "988" in text), text
    changed = {"lower": 0, "upper": 0.05, "precision": 2}
    result = rt.apply_operations(blank, [{"op": "modify", "target": actual["id"], "set": {"tolerance": changed}}])
    assert result["ok"], result
    info = Runtime(rt.policy).inspect_entities(blank, {"tag": "toleranced"})["entities"][0]
    assert info["tolerance"]["upper"] == 0.05
    delivered = rt.deliver_drawing(blank, "bundle", formats=["dxf", "pdf", "json"])
    assert delivered["ok"], delivered
    assert rt.apply_operations(blank, [{"op": "modify", "target": actual["id"], "set": {"tolerance": None}}])["ok"]
    assert "tolerance" not in rt.inspect_entities(blank, {"tag": "toleranced"})["entities"][0]


@pytest.mark.parametrize("tolerance,code", [
    ({"lower": 0.1, "upper": -0.1}, "INVALID_TOLERANCE"),
    ({"lower": 0, "upper": 0.025, "precision": 2}, "TOLERANCE_PRECISION_LOSS"),
    ({"lower": 0, "upper": 0.1, "precision": True}, "INVALID_TOLERANCE"),
    ({"lower": 0, "upper": 0.1, "fit": "H7"}, "INVALID_TOLERANCE"),
    ({"upper": 0.1}, "INVALID_TOLERANCE"),
])
def test_bad_tolerances_leave_drawing_unchanged(rt, ws, blank, tolerance, code):
    before = (ws / blank).read_bytes()
    result = rt.apply_operations(blank, [{"op": "add_linear_dim", "p1": [0, 0], "p2": [10, 0], "tolerance": tolerance}])
    assert result["error"]["code"] == code, result
    assert (ws / blank).read_bytes() == before


def test_tolerance_cannot_hide_behind_fake_nominal_text(rt, blank):
    result = rt.apply_operations(blank, [{"op": "add_linear_dim", "p1": [0, 0], "p2": [10, 0],
                                        "text": "20", "tolerance": {"lower": -0.1, "upper": 0.1}}])
    assert result["error"]["code"] == "TOLERANCE_TEXT_OVERRIDE"


def test_limit_precision_cannot_round_away_nominal_digits(rt, blank):
    result = rt.apply_operations(blank, [{"op": "add_linear_dim", "p1": [0, 0], "p2": [1.234, 0],
                                        "tolerance": {"lower": -0.1, "upper": 0.1, "precision": 1, "mode": "limits"}}])
    assert result["error"]["code"] == "TOLERANCE_PRECISION_LOSS"


@pytest.mark.parametrize("edit", [
    {"op": "modify", "target": "tag:limit", "set": {"length_factor": 1.234}},
    {"op": "stretch", "window": [[0.9, -0.1], [1.1, 0.1]], "delta": [0.234, 0]},
])
def test_existing_limits_cannot_lose_precision_during_edits(rt, ws, blank, edit):
    assert rt.apply_operations(blank, [
        {"op": "add_line", "start": [0, 0], "end": [1, 0]},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [1, 0], "tag": "limit",
         "tolerance": {"lower": -0.1, "upper": 0.1, "precision": 1, "mode": "limits"}}])["ok"]
    before = (ws / blank).read_bytes()
    result = rt.apply_operations(blank, [edit])
    assert result["error"]["code"] == "TOLERANCE_PRECISION_LOSS", result
    assert (ws / blank).read_bytes() == before


def test_external_limit_precision_corruption_blocks_delivery(rt, ws, blank):
    assert rt.apply_operations(blank, [
        {"op": "add_line", "start": [0, 0], "end": [1, 0]},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [1, 0], "tag": "limit",
         "tolerance": {"lower": -0.1, "upper": 0.1, "precision": 1, "mode": "limits"}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    dim = doc.modelspace().query("DIMENSION").first
    override = dim.override()
    override["dimlfac"] = 1.234
    override.render()
    doc.saveas(ws / blank)
    report = rt.validate_drawing(blank)
    assert any(i["code"] == "TOLERANCE_PRECISION_LOSS" for i in report["validation"]["issues"])
    assert rt.deliver_drawing(blank, "bad-limit", formats=["dxf"])["error"]["code"] == "DELIVERY_REJECTED"


@pytest.mark.parametrize("placement", ["model_block", "nested_block", "paper_block", "unused_block"])
def test_nested_and_unused_block_tolerances_are_checked(rt, ws, blank, placement):
    assert rt.apply_operations(blank, [
        {"op": "add_line", "start": [0, 0], "end": [1, 0]},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [1, 0],
         "tolerance": {"lower": -0.1, "upper": 0.1, "precision": 1, "mode": "limits"}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    block = doc.blocks.new("ASSEMBLY")
    for entity in list(doc.modelspace()):
        doc.modelspace().move_to_layout(entity, block)
    dim = block.query("DIMENSION").first
    name = block.name
    if placement == "nested_block":
        parent = doc.blocks.new("NESTED")
        parent.add_blockref(name, (10, 0))
        name = parent.name
    if placement != "unused_block":
        space = doc.layouts.new("Sheet") if placement == "paper_block" else doc.modelspace()
        space.add_blockref(name, (0, 0))
        space.add_blockref(name, (20, 0))  # no duplicated report per instance
    doc.saveas(ws / blank)
    assert rt.deliver_drawing(blank, "valid-block", formats=["dxf"])["ok"]
    override = dim.override()
    override["dimlfac"] = 1.234
    override.render()
    doc.saveas(ws / blank)
    before = (ws / blank).read_bytes()
    report = rt.validate_drawing(blank)["validation"]
    assert sum(i["code"] == "TOLERANCE_PRECISION_LOSS" for i in report["issues"]) == 1
    result = rt.deliver_drawing(blank, "bad-block", formats=["dxf"], min_score=0)
    assert result["error"]["code"] == "DELIVERY_REJECTED", result
    assert (ws / blank).read_bytes() == before


@pytest.mark.parametrize("mode", ["deviations", "limits"])
@pytest.mark.parametrize("factor", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_saved_length_factor_never_passes_tolerance_delivery(rt, ws, blank, mode, factor):
    assert rt.apply_operations(blank, [
        {"op":"add_line", "start":[0,0], "end":[10,0]},
        {"op":"add_linear_dim", "p1":[0,0], "p2":[10,0],
         "tolerance":{"lower":-.1, "upper":.1, "mode":mode}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    block = doc.blocks.new("BAD_FACTOR")
    for entity in list(doc.modelspace()):
        doc.modelspace().move_to_layout(entity, block)
    doc.modelspace().add_blockref(block.name, (0,0))
    dim = block.query("DIMENSION").first
    override = dim.override()
    override["dimlfac"] = factor
    override.commit()  # simulate a foreign editor corrupting metadata, not our renderer
    doc.saveas(ws / blank)
    result = rt.deliver_drawing(blank, "bad-factor", formats=["dxf"])
    assert result["error"]["code"] == "DELIVERY_REJECTED", result
    assert any(i["code"] == "INVALID_TOLERANCE" for i in result["error"]["details"]["validation"]["issues"])


@pytest.mark.parametrize("mode", ["deviations", "limits"])
def test_stacked_tolerance_glyphs_clear_the_radial_dimension_line(rt, ws, blank, mode):
    from ezdxf.addons.drawing import Frontend, RenderContext, recorder

    assert rt.apply_operations(blank, [
        {"op":"add_circle", "center":[0,0], "diameter":35},
        {"op":"add_diameter_dim", "target":"$0", "angle":0, "text_height":2.5,
         "tolerance":{"lower":0, "upper":.025, "precision":3, "mode":mode}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    dim = doc.modelspace().query("DIMENSION").first
    text = list(doc.blocks[dim.dxf.geometry].query("MTEXT"))
    recording = recorder.Recorder()
    # Actual font outlines, not MTEXT's conservative multi-line bounding box.
    Frontend(RenderContext(doc), recording).draw_entities(text)
    assert recording.player().bbox().extmin.y > 0.1


def test_sourced_fit_lookup_drives_saved_dimension(rt, blank):
    fit = rt.standard_library(item="iso_fit", size="25 H7/g6")
    assert fit["ok"] and fit["source_page"] == 74
    assert fit["hole"]["minimum"] == 25 and fit["hole"]["maximum"] == 25.021
    assert fit["shaft"]["minimum"] == 24.980 and fit["shaft"]["maximum"] == 24.993
    assert fit["clearance"] == {"minimum": 0.007, "maximum": 0.041}
    result = rt.apply_operations(blank, [
        {"op": "add_circle", "center": [0, 0], "diameter": 25},
        {"op": "add_diameter_dim", "target": "$0", "text": "<> H7", "tag": "fit",
         "tolerance": {k: fit["hole"][k] for k in ("lower", "upper")}}])
    assert result["ok"], result
    saved = Runtime(rt.policy).inspect_entities(blank, {"tag": "fit"})["entities"][0]
    assert saved["tolerance"]["upper"] == 0.021 and saved["measurement"] == 25


@pytest.mark.parametrize("bound,hole,shaft,g_top,next_hole", [
    (18, 18, 11, -6, 21), (30, 21, 13, -7, 25), (50, 25, 16, -9, 30),
    (80, 30, 19, -10, 35), (120, 35, 22, -12, 40), (180, 40, 25, -14, 46),
    (250, 46, 29, -15, 52), (315, 52, 32, -17, 57), (400, 57, 36, -18, 63), (500, 63, 40, -20, None),
])
def test_fit_table_rows_and_inclusive_boundaries(rt, bound, hole, shaft, g_top, next_hole):
    # Independently transcribed expected values from SKF tables 3/4, printed p74.
    h7 = rt.standard_library("iso_fit", f"{bound} H7")
    assert h7["lower"] == 0 and h7["upper"] == hole / 1000
    h6 = rt.standard_library("iso_fit", f"{bound} h6")
    assert h6["lower"] == -shaft / 1000 and h6["upper"] == 0
    g6 = rt.standard_library("iso_fit", f"{bound} g6")
    assert g6["lower"] == (g_top - shaft) / 1000 and g6["upper"] == g_top / 1000
    if next_hole:
        assert rt.standard_library("iso_fit", f"{bound + 0.001} H7")["upper"] == next_hole / 1000
    else:
        assert rt.standard_library("iso_fit", "500.001 H7")["error"]["code"] == "UNVERIFIED_FIT_RANGE"


@pytest.mark.parametrize("size", ["10 H7", "0 H7", "501 h6", "25 H8", "25 k6", "nan H7", "25", "25 H7 extra"])
def test_unverified_fits_are_refused(rt, size):
    assert not rt.standard_library("iso_fit", size)["ok"]
