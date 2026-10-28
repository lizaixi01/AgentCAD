"""Test M: industry libraries (P&ID, GD&T, ISO holes and parts) and the standard_library tool."""
from __future__ import annotations

import json
import math

import ezdxf

from conftest import ok, reread


def pipe(rt, path, **kw):
    return ok(rt.apply_operations(path, [{"op": "add_process_line", "points": [[0, 0], [120, 0], [120, 60], [200, 60]],
                                          "tag": "L1", **kw}]))


def by_tag(ws, path, tag):
    from agentcad.model import get_tag
    doc = reread(ws, path)
    return [e for e in doc.modelspace() if get_tag(e) == tag]


# --- P&ID ------------------------------------------------------------------------------------------------------
def test_inline_valves_cut_the_pipe_where_asked(rt, ws, blank):
    pipe(rt, blank, flow_arrows=False)
    r = ok(rt.apply_operations(blank, [
        {"op": "add_pid_symbol", "symbol": "gate_valve", "on": "tag:L1", "insert": [30, 1], "tag_no": "V-101"},
        {"op": "add_pid_symbol", "symbol": "check_valve", "on": "tag:L1", "insert": [80, 0], "tag_no": "V-102"},
        {"op": "add_pid_symbol", "symbol": "control_valve", "on": "tag:L1", "insert": [160, 60], "tag_no": "FV-1"}]))
    res = r["results"]
    assert res[0]["ports"] == [[25.0, 0.0], [35.0, 0.0]]  # 10 mm symbol centred on the projected point
    assert res[1]["ports"] == [[75.0, 0.0], [85.0, 0.0]] and res[2]["ports"] == [[155.0, 60.0], [165.0, 60.0]]
    # the pipe is now four pieces that all keep its tag, leaving exactly the three gaps
    pieces = by_tag(ws, blank, "L1")
    assert len(pieces) == 4
    length = sum(sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
                 for pts in ([tuple(q)[:2] for q in e.get_points("xy")] for e in pieces))
    assert math.isclose(length, 120 + 60 + 80 - 30)
    refs = {e.dxf.name: e for e in reread(ws, blank).modelspace().query("INSERT")}
    assert refs["PID_CHECK_VALVE"].get_attrib_text("TAG") == "V-102"
    assert refs["PID_GATE_VALVE"].dxf.rotation == 0 and refs["PID_CONTROL_VALVE"].dxf.xscale == 10


def test_symbol_on_vertical_pipe_turns_with_it_and_reverses_with_rotation(rt, ws, blank):
    pipe(rt, blank, flow_arrows=False)
    r = ok(rt.apply_operations(blank, [{"op": "add_pid_symbol", "symbol": "check_valve", "on": "tag:L1",
                                        "insert": [121, 30], "rotation": 180}]))
    assert r["results"][0]["rotation"] == 270  # pipe runs +y (90 deg), reversed flow


def test_symbol_errors(rt, ws, blank):
    pipe(rt, blank)
    for ops, code in (
            ([{"op": "add_pid_symbol", "symbol": "centrifugal_pump", "on": "tag:L1"}], "NOT_INLINE"),
            ([{"op": "add_pid_symbol", "symbol": "gate_valve", "on": "tag:L1", "insert": [60, 0], "size": 500}],
             "SYMBOL_DOES_NOT_FIT"),
            ([{"op": "add_pid_symbol", "symbol": "gate_valve"}], "MISSING_PARAM"),
            ([{"op": "add_circle", "center": [0, 0], "radius": 5, "tag": "c"},
              {"op": "add_pid_symbol", "symbol": "gate_valve", "on": "tag:c"}], "UNSUPPORTED_ENTITY"),
            ([{"op": "add_pid_symbol", "symbol": "teapot", "insert": [0, 0]}], "INVALID_ENUM")):
        assert rt.apply_operations(blank, ops)["error"]["code"] == code, ops


def test_flow_arrows_under_a_new_valve_are_removed(rt, ws, blank):
    pipe(rt, blank)
    arrows = lambda: [e for e in reread(ws, blank).modelspace().query("INSERT") if e.dxf.name == "PID_FLOW_ARROW"]
    assert len(arrows()) == 3  # one per segment
    r = ok(rt.apply_operations(blank, [{"op": "add_pid_symbol", "symbol": "gate_valve", "on": "tag:L1",
                                        "insert": [60, 0]}]))
    assert len(r["results"][0]["removed_flow_arrows"]) == 1 and len(arrows()) == 2


def test_instruments_and_parts_list(rt, ws, blank):
    pipe(rt, blank)
    ok(rt.apply_operations(blank, [
        {"op": "add_pid_symbol", "symbol": "instrument_dcs", "insert": [160, 90], "tag_no": "FIC-101"},
        {"op": "add_pid_symbol", "symbol": "instrument_field", "insert": [140, 90], "tag_no": "FT 101"},
        {"op": "add_pid_symbol", "symbol": "gate_valve", "on": "tag:L1", "insert": [60, 0], "tag_no": "V-1"},
        {"op": "add_pid_symbol", "symbol": "vessel_vertical", "insert": [230, 60], "size": 20, "tag_no": "V-201"}]))
    bom = ok(rt.standard_library(drawing=blank))
    assert bom["instruments"] == [{"symbol": "instrument_dcs", "tag": "FIC-101", "id": bom["instruments"][0]["id"]},
                                  {"symbol": "instrument_field", "tag": "FT-101", "id": bom["instruments"][1]["id"]}]
    assert [(s["symbol"], s["tag"]) for s in bom["pid_symbols"]] == [("gate_valve", "V-1"), ("vessel_vertical", "V-201")]
    vessel = [e for e in reread(ws, blank).modelspace().query("INSERT") if e.dxf.name == "PID_VESSEL_VERTICAL"][0]
    assert vessel.get_attrib("TAG").dxf.height == 2.5  # tag text stays 2.5 mm although the symbol is 20 mm


def test_process_line_kinds(rt, ws, blank):
    r = ok(rt.apply_operations(blank, [
        {"op": "add_process_line", "points": [[0, 0], [50, 0]], "kind": "signal_electric", "flow_arrows": False,
         "tag": "s1"},
        {"op": "add_process_line", "points": [[0, 20], [50, 20]], "kind": "signal_pneumatic", "flow_arrows": False,
         "tag": "s2"},
        {"op": "add_process_line", "points": [[0, 40], [80, 40]], "line_number": "3\"-P-2001", "tag": "p"}]))
    doc = reread(ws, blank)
    assert doc.layers.get("PID_SIGNAL").dxf.linetype.upper() == "DASHED"
    assert r["results"][0]["layer"] == "PID_SIGNAL" and r["results"][2]["layer"] == "PID_PROCESS"
    assert len(by_tag(ws, blank, "s2.deco")) >= 2  # the // marks
    deco = by_tag(ws, blank, "p.deco")
    assert {e.dxftype() for e in deco} == {"INSERT", "TEXT"}
    assert [e.dxf.text for e in deco if e.dxftype() == "TEXT"] == ['3"-P-2001']
    ok(rt.apply_operations(blank, [{"op": "delete", "target": ["tag:p", "tag:p.deco"]}]))
    assert not by_tag(ws, blank, "p") and not by_tag(ws, blank, "p.deco")


# --- GD&T ----------------------------------------------------------------------------------------------------------
def test_feature_control_frame(rt, ws, blank):
    r = ok(rt.apply_operations(blank, [
        {"op": "add_feature_control_frame", "insert": [10, 10], "characteristic": "position", "tolerance": "0.1",
         "diameter": True, "modifier": "M", "datums": ["A", "B", "C(M)"], "leader_to": [0, 0], "tag": "f"}]))
    res = r["results"][0]
    (x0, y0), (x1, y1) = res["frame"]
    assert (x0, y0) == (10, 10) and math.isclose(y1 - y0, 7.0) and x1 - x0 > 4 * 7
    ents = by_tag(ws, blank, "f")
    texts = sorted(e.dxf.text for e in ents if e.dxftype() == "TEXT")
    assert texts == ["%%c0.1", "A", "B", "C", "M", "M"]
    assert {"LEADER", "LWPOLYLINE"} <= {e.dxftype() for e in ents}
    v = ok(rt.validate_drawing(blank))["validation"]
    assert v["passed"], v["issues"]


def test_feature_control_frame_rules(rt, blank):
    def code(**kw):
        return rt.apply_operations(blank, [{"op": "add_feature_control_frame", "insert": [0, 0], "tolerance": "0.1",
                                            **kw}])["error"]["code"]
    assert code(characteristic="perpendicularity") == "MISSING_DATUM"
    assert code(characteristic="flatness", datums=["A"]) == "DATUM_NOT_ALLOWED"
    assert code(characteristic="position", datums=["a"]) == "INVALID_DATUM"
    assert code(characteristic="position", datums=["A", "B", "C", "D"]) == "TOO_MANY_DATUMS"
    assert code(characteristic="position", modifier="X") == "INVALID_ENUM"


def test_gdt_follows_the_annotation_scale(rt, ws):
    ok(rt.create_drawing("big.dxf", annotation_scale=2))
    r = ok(rt.apply_operations("big.dxf", [{"op": "add_feature_control_frame", "insert": [0, 0],
                                            "characteristic": "flatness", "tolerance": "0.02"}]))
    assert r["results"][0]["text_height"] == 7.0


def test_datum_feature_and_surface_finish(rt, ws, blank):
    ok(rt.apply_operations(blank, [
        {"op": "add_datum_feature", "letter": "A", "on": [50, 0], "insert": [50, -15], "tag": "dA"},
        {"op": "add_surface_finish", "insert": [20, 0], "ra": "3.2", "process": "removal_required", "tag": "sf"},
        {"op": "add_surface_finish", "insert": [40, 0], "process": "removal_prohibited", "tag": "sf2"}]))
    d = by_tag(ws, blank, "dA")
    assert {e.dxftype() for e in d} == {"HATCH", "LWPOLYLINE", "LINE", "TEXT"}
    assert [e.dxf.text for e in by_tag(ws, blank, "sf") if e.dxftype() == "TEXT"] == ["Ra 3.2"]
    assert any(e.dxftype() == "CIRCLE" for e in by_tag(ws, blank, "sf2"))
    e = rt.apply_operations(blank, [{"op": "add_datum_feature", "letter": "B", "on": [0, 0], "insert": [0, 3]}])
    assert e["error"]["code"] == "TOO_CLOSE"


# --- holes and parts ---------------------------------------------------------------------------------------------------
def test_standard_holes_are_real_holes(rt, ws, blank):
    centers = [[15, 15], [105, 15], [105, 65], [15, 65]]
    r = ok(rt.apply_operations(blank, [
        {"op": "add_rectangle", "corner": [0, 0], "width": 120, "height": 80, "layer": "OUTLINE"},
        {"op": "add_standard_hole", "centers": centers, "size": "M8", "tag": "cl"},
        {"op": "add_standard_hole", "centers": [[60, 40]], "size": "M8", "kind": "tapped", "tag": "th"},
        {"op": "add_standard_hole", "centers": [[60, 20]], "size": "M6", "kind": "counterbore", "fit": "fine"}]))
    cl, th, cb = (x for x in r["results"][1:])
    assert cl["dims"]["diameter"] == 9.0 and cl["count"] == 4  # ISO 273 medium
    assert th["dims"]["tap_drill"] == 6.8 and th["dims"]["callout"] == "M8-6H"  # ISO 2306
    assert cb["dims"]["counterbore_diameter"] == 11.0
    reqs = [{"type": "hole", "center": c, "diameter": 9} for c in centers] + \
           [{"type": "hole", "center": [60, 40], "diameter": 6.8}]
    v = ok(rt.validate_drawing(blank, requirements=reqs))["validation"]
    assert v["passed"] and len(v["requirements_passed"]) == 5
    arc = [e for e in reread(ws, blank).modelspace() if e.dxftype() == "ARC" and e.dxf.layer == "THREAD"][0]
    assert arc.dxf.radius == 4 and (arc.dxf.start_angle, arc.dxf.end_angle) == (90, 0)  # ISO 6410 3/4 circle
    assert by_tag(ws, blank, "cl.0") and by_tag(ws, blank, "cl.cm.0.h")


def test_standard_holes_in_an_inch_drawing(rt, ws):
    ok(rt.create_drawing("in.dxf", units="in"))
    r = ok(rt.apply_operations("in.dxf", [{"op": "add_standard_hole", "centers": [[1, 1]], "size": "M8",
                                           "center_marks": False}]))
    assert math.isclose(r["results"][0]["dims"]["diameter"], 9 / 25.4, rel_tol=1e-6)
    c = [e for e in reread(ws, "in.dxf").modelspace() if e.dxftype() == "CIRCLE"][0]
    assert math.isclose(c.dxf.radius, 4.5 / 25.4, rel_tol=1e-6)


def test_standard_parts_and_parts_list(rt, ws, blank):
    r = ok(rt.apply_operations(blank, [
        {"op": "add_standard_part", "part": "hex_bolt", "size": "M10", "length": 40, "insert": [0, 0]},
        {"op": "add_standard_part", "part": "hex_bolt", "size": "M10", "length": 20, "insert": [30, 0]},
        {"op": "add_standard_part", "part": "hex_bolt", "size": "M10", "view": "top", "insert": [30, 0],
         "count_in_bom": False},
        {"op": "add_standard_part", "part": "hex_nut", "size": "M10", "view": "top", "insert": [60, 0]},
        {"op": "add_standard_part", "part": "hex_nut", "size": "M10", "view": "top", "insert": [90, 0]},
        {"op": "add_standard_part", "part": "ball_bearing", "size": "6204", "view": "side", "insert": [120, 0]}]))
    res = r["results"]
    assert res[0]["standard"] == "ISO 4014" and res[0]["dims_mm"]["thread_length"] == 26  # b = 2d + 6
    assert res[1]["standard"] == "ISO 4017"  # 20 mm is threaded over its full length
    assert res[3]["dims_mm"]["s"] == 16 and res[5]["dims_mm"] == {"d": 20, "D": 47, "B": 14}
    blocks = reread(ws, blank).blocks
    nut = blocks.get(res[3]["block"])
    hexagon = [e for e in nut if e.dxftype() == "LWPOLYLINE"][0]
    flats = [abs(p[1]) for p in hexagon.get_points("xy")]
    assert math.isclose(max(flats) * 2, 16, rel_tol=1e-3)  # across flats
    bom = ok(rt.standard_library(drawing=blank))["parts"]
    assert {(b["part"], b["size"], b["quantity"]) for b in bom} == {
        ("hex_bolt", "M10x40", 1), ("hex_bolt", "M10x20", 1), ("hex_nut", "M10", 2), ("ball_bearing", "6204", 1)}


def test_standard_part_errors(rt, blank):
    def code(**kw):
        return rt.apply_operations(blank, [{"op": "add_standard_part", "insert": [0, 0], **kw}])["error"]["code"]
    assert code(part="hex_bolt", size="M7", length=20) == "INVALID_SIZE"
    assert code(part="hex_bolt", size="M10") == "MISSING_PARAM"  # side view needs a length
    assert code(part="ball_bearing", size="M10") == "INVALID_SIZE"


def test_standard_library_lookup(rt):
    idx = ok(rt.standard_library())
    assert "gate_valve" in idx["pid_symbols"] and "position" in idx["gdt_characteristics"]
    assert idx["standard_parts"]["hex_nut"]["standard"] == "ISO 4032" and len(idx["ops"]) == 7
    assert len(json.dumps(idx)) < 4000  # compact by default
    assert ok(rt.standard_library("clearance", "M8"))["rows"]["M8"]["coarse"]["diameter"] == 10.0
    assert ok(rt.standard_library("socket_head_cap_screw", "M6"))["rows"]["M6"]["dk"] == 10.0
    assert ok(rt.standard_library("perpendicularity"))["datums"] == "required"
    assert rt.standard_library("teapot")["error"]["code"] == "UNKNOWN_ITEM"
    assert rt.standard_library("hex_nut", "M7")["error"]["code"] == "INVALID_SIZE"


def test_library_ops_in_the_compact_catalog(rt):
    cat = ok(rt.list_operations())
    lib = [o["op"] for o in cat["operations"] if o["category"] == "library"]
    assert len(lib) == 7 and len(json.dumps(cat)) < 16000
    assert ok(rt.list_operations(category="library"))["count"] == 7
