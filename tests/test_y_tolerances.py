import ezdxf
import pytest

from agentcad.service import Runtime
from agentcad.tolerances import MARK


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


def _foreign_tolerances(path, dimtp=0.5):
    """Tolerances a drawing's author set in another program: in the dimension style, and on single
    dimensions, as AutoCAD's Properties palette does."""
    doc = ezdxf.new("R2010", setup=True, units=4)
    style = doc.dimstyles.duplicate_entry("EZDXF", "TOL")
    style.dxf.dimtol, style.dxf.dimtp, style.dxf.dimtm, style.dxf.dimtdec = 1, 0.5, 0.5, 1
    msp = doc.modelspace()
    x, slope, y = ((0, 0), (50, 0)), ((0, 0), (40, 30)), ((0, 0), (0, 40))
    for line in (x, slope, y):
        msp.add_line(*line)
    msp.add_angular_dim_2l(base=(30, 10), line1=x, line2=slope, dimstyle="TOL").render()
    msp.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(50, 0), text="REF", dimstyle="TOL").render()
    msp.add_angular_dim_2l(base=(10, 30), line1=slope, line2=y, dimstyle="EZDXF",
                           override={"dimtol": 1, "dimtp": dimtp, "dimtm": 0.5, "dimtdec": 1}).render()
    # Typed text, deviations finer than DIMTDEC, and limits on a length that is not round: AgentCAD
    # would not write these, but they are the author's to keep.
    for n, (length, text, own) in enumerate([(50, "50", {"dimtol": 1, "dimtp": 0.1, "dimtm": 0.1}),
                                             (50, "<>", {"dimtol": 1, "dimtp": 0.025, "dimtm": 0.025}),
                                             (49.9998, "<>", {"dimlim": 1, "dimtp": 0.1, "dimtm": 0.1})]):
        level = 60 + 20 * n
        msp.add_line((0, level), (length, level))
        msp.add_linear_dim(base=(0, level - 10), p1=(0, level), p2=(length, level), text=text, dimstyle="Standard",
                           override={**own, "dimtdec": 2, "dimdec": 2}).render()
    doc.saveas(path)


def test_tolerances_the_drawing_author_set_do_not_block_edits_or_delivery(rt, ws):
    _foreign_tolerances(ws / "foreign.dxf")
    issues = rt.validate_drawing("foreign.dxf")["validation"]["issues"]
    assert not [i for i in issues if "TOLERANCE" in i["code"]], issues
    dims = rt.inspect_entities("foreign.dxf", filter={"type": "DIMENSION"})["entities"]
    assert [d["tolerance"].get("from_style", False) for d in dims] == [True, True] + [False] * 4
    for d in dims:  # each move redraws the dimension; moving back keeps it attached to its geometry
        assert rt.apply_operations("foreign.dxf", [{"op": "move", "target": d["id"], "delta": delta}
                                                   for delta in ([5, 0], [-5, 0])])["ok"]
    assert rt.apply_operations("foreign.dxf", [{"op": "modify", "target": dims[1]["id"], "set": {"text_height": 3}},
                                               {"op": "add_line", "start": [0, 50], "end": [10, 50]}], strict=True)["ok"]
    # Text AgentCAD writes is still held to the rule, wherever the tolerance comes from.
    fake = rt.apply_operations("foreign.dxf", [{"op": "modify", "target": dims[0]["id"], "set": {"text": "40"}}])
    assert fake["error"]["code"] == "TOLERANCE_TEXT_OVERRIDE"
    assert rt.deliver_drawing("foreign.dxf", "bundle", formats=["dxf"])["ok"]


def test_corrupt_foreign_tolerance_values_are_still_refused(rt, ws):
    _foreign_tolerances(ws / "foreign.dxf", dimtp=float("nan"))
    issues = rt.validate_drawing("foreign.dxf")["validation"]["issues"]
    assert [i["code"] for i in issues if "TOLERANCE" in i["code"]] == ["INVALID_TOLERANCE"]


@pytest.mark.parametrize("damaged_mark", [False, True])
def test_agentcad_tolerances_keep_their_rules_after_a_foreign_edit(rt, ws, blank, damaged_mark):
    assert rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0]},
                                       {"op": "add_linear_dim", "p1": [0, 0], "p2": [10, 0], "tag": "fit",
                                        "tolerance": {"lower": -0.1, "upper": 0.1}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    dim = doc.modelspace().query("DIMENSION").first
    dim.dxf.text = "20"  # another program types a fake nominal
    if damaged_mark:  # a damaged mark still says AgentCAD wrote the tolerance
        dim.set_xdata(MARK, [(1000, "not json")])
    doc.saveas(ws / blank)
    issues = rt.validate_drawing(blank)["validation"]["issues"]
    assert [i["code"] for i in issues if "TOLERANCE" in i["code"]] == ["TOLERANCE_TEXT_OVERRIDE"]


def test_a_new_dimension_cannot_hide_its_value_beside_a_style_tolerance(rt, ws):
    doc = ezdxf.new("R2010")  # only the Standard style, which new dimensions then use
    style = doc.dimstyles.get("Standard")
    style.dxf.dimtol, style.dxf.dimtp, style.dxf.dimtm = 1, 0.5, 0.5
    doc.saveas(ws / "styled.dxf")
    line = {"op": "add_line", "start": [0, 0], "end": [10, 0]}
    dim = {"op": "add_linear_dim", "p1": [0, 0], "p2": [10, 0]}
    fixed = rt.apply_operations("styled.dxf", [line, {**dim, "text": "10"}])
    assert fixed["error"]["code"] == "TOLERANCE_TEXT_OVERRIDE"
    assert rt.apply_operations("styled.dxf", [line, {**dim, "text": "<> REF"}])["ok"]


def test_a_dimension_naming_a_missing_style_can_be_inspected(rt, ws):
    doc = ezdxf.new("R2010", setup=True)
    dim = doc.modelspace().add_linear_dim(base=(0, 10), p1=(0, 0), p2=(50, 0), dimstyle="EZDXF")
    dim.render()
    dim.dimension.dxf.dimstyle = "GONE"
    doc.saveas(ws / "foreign.dxf")
    found = rt.inspect_entities("foreign.dxf", filter={"type": "DIMENSION"})
    assert found["ok"] and "tolerance" not in found["entities"][0], found
    assert rt.export_drawing("foreign.dxf", "foreign.json", "json")["ok"]


LOOK = ("dimgap", "dimtolj", "dimtfac")


def test_clearing_a_tolerance_restores_the_dimension_look(rt, ws, blank):
    # a, d: never toleranced. b: cleared. c: text grows, then cleared. e: tolerance changed, then cleared.
    dims = [{"op": "add_linear_dim", "p1": [0, 0], "p2": [50, 0], "text_height": 3.5, "tag": tag} for tag in "abcde"]
    for d in (dims[1], dims[2], dims[4]):
        d["tolerance"] = {"lower": -0.1, "upper": 0.1}
    assert rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [50, 0]}, *dims])["ok"]
    assert rt.apply_operations(blank, [{"op": "modify", "target": f"tag:{t}", "set": {"text_height": 5}}
                                       for t in "cd"] + [{"op": "modify", "target": "tag:e", "set": {
                                           "tolerance": {"lower": -0.2, "upper": 0.3}}}])["ok"]
    assert rt.apply_operations(blank, [{"op": "modify", "target": f"tag:{t}", "set": {"tolerance": None}}
                                       for t in "bce"])["ok"]
    doc = ezdxf.readfile(ws / blank)
    dims = {t: doc.entitydb[Runtime(rt.policy).inspect_entities(blank, {"tag": t})["entities"][0]["id"]]
            for t in "abcde"}
    look = {t: {k: dim.override().get(k) for k in LOOK} for t, dim in dims.items()}
    assert look["b"] == look["a"] == look["e"] and look["c"] == look["d"]
    assert not any(dims[t].has_xdata(MARK) for t in "bce")


@pytest.mark.parametrize("saved", ['{"dimgap": NaN, "dimtolj": 7, "dimtfac": 0}', '{"dimgap": 1' + "0" * 400 + "}"])
def test_a_damaged_mark_never_writes_an_invalid_look(rt, ws, blank, saved):
    assert rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [50, 0]},
                                       *({"op": "add_linear_dim", "p1": [0, 0], "p2": [50, 0], "tag": tag}
                                         for tag in "ab")])["ok"]
    assert rt.apply_operations(blank, [{"op": "modify", "target": "tag:b",
                                        "set": {"tolerance": {"lower": -0.1, "upper": 0.1}}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    damaged = doc.entitydb[Runtime(rt.policy).inspect_entities(blank, {"tag": "b"})["entities"][0]["id"]]
    damaged.set_xdata(MARK, [(1000, saved)])
    doc.saveas(ws / blank)
    assert rt.apply_operations(blank, [{"op": "modify", "target": "tag:b", "set": {"tolerance": None}}])["ok"]
    doc = ezdxf.readfile(ws / blank)
    plain, cleared = (doc.entitydb[Runtime(rt.policy).inspect_entities(blank, {"tag": t})["entities"][0]["id"]]
                      .override() for t in "ab")
    assert {k: cleared.get(k) for k in LOOK} == {k: plain.get(k) for k in LOOK}


@pytest.mark.parametrize("gap", [1.25, -1.0])  # half its text height; AutoCAD's boxed text
def test_clearing_a_tolerance_keeps_the_dimensions_own_gap(rt, ws, gap):
    doc = ezdxf.new("R2010", setup=True, units=4)
    doc.modelspace().add_linear_dim(base=(0, -10), p1=(0, 0), p2=(50, 0), dimstyle="Standard",
                                    override={"dimgap": gap}).render()
    doc.saveas(ws / "own.dxf")
    handle = rt.inspect_entities("own.dxf", filter={"type": "DIMENSION"})["entities"][0]["id"]
    for tolerance in ({"lower": -0.1, "upper": 0.1}, None):
        assert rt.apply_operations("own.dxf", [{"op": "modify", "target": handle,
                                                "set": {"tolerance": tolerance}}])["ok"]
    assert ezdxf.readfile(ws / "own.dxf").entitydb[handle].override().dimstyle_attribs.get("dimgap") == gap


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
