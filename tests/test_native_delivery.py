"""Synthetic domain files through actual DWG conversion; no Autodesk samples."""
import pytest

from agentcad.backends.autocad import find_accoreconsole
from conftest import ok

pytestmark = pytest.mark.skipif(find_accoreconsole() is None, reason="AutoCAD accoreconsole not installed")


@pytest.mark.parametrize("domain", ["architecture", "mechanical", "pid", "tolerance"])
def test_domain_and_tolerance_dwg_readback(rt, blank, domain):
    if domain == "architecture":
        operations = [{"op": "draw_arch_plan", "spec": {
            "walls": [{"id": "outer", "axis": [[0, 0], [7000, 0], [7000, 5500], [0, 5500]],
                       "closed": True, "thickness": 240}],
            "rooms": [{"id": "room", "number": "02", "name": "Workshop", "at": [3000, 2000]}]}}]
    elif domain == "mechanical":
        operations = [{"op": "draw_mechanical_assembly", "spec": {
            "sheet": {"title": "Native roundtrip", "drawing_no": "NATIVE-03"},
            "fasteners": [{"part": "hex_bolt", "size": "M10", "length": 40, "insert": [60, 90]},
                          {"part": "hex_nut", "size": "M10", "insert": [100, 90]}]}}]
    elif domain == "pid":
        operations = [{"op": "draw_pid", "spec": {
            "equipment": [{"id": "A", "symbol": "centrifugal_pump", "x": 0, "y": 0},
                          {"id": "B", "symbol": "centrifugal_pump", "x": 80, "y": 30}],
            "lines": [{"from": "A.discharge", "to": "B.suction", "number": "DN80-WATER"}]}}]
    else:
        operations = [{"op": "add_circle", "center": [0, 0], "diameter": 25},
                      {"op": "add_diameter_dim", "target": "$0", "tag": "bore", "text": "<> H7",
                       "tolerance": {"lower": 0, "upper": 0.021}}]
    ok(rt.apply_operations(blank, operations))
    before = ok(rt.read_engineering(blank, domain)) if domain != "tolerance" else None
    ok(rt.export_drawing(blank, "native.dwg", "dwg"))
    ok(rt.import_drawing("native.dwg", "reopened.dxf"))
    audit = ok(rt.autocad_audit("reopened.dxf"))
    assert audit["passed"] and audit["audit_errors"] == 0
    if domain == "tolerance":
        dim = ok(rt.inspect_entities("reopened.dxf", {"tag": "bore"}))["entities"][0]
        assert dim["tolerance"]["upper"] == 0.021 and dim["tolerance"]["lower"] == 0
        assert dim["measurement"] == 25
    else:
        after = ok(rt.read_engineering("reopened.dxf", domain))
        assert before["critique"] == after["critique"] == []
        if domain == "architecture":
            assert after["rooms"][0]["detected_area"] == before["rooms"][0]["detected_area"]
        elif domain == "pid":
            assert after["line_list"][0]["line_number"] == "DN80-WATER"
        else:
            assert [r["quantity"] for r in after["bom"]] == [r["quantity"] for r in before["bom"]]
