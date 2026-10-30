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
