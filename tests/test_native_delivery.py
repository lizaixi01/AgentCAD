"""Synthetic domain files through actual DWG conversion; no Autodesk samples."""
import pytest
import ezdxf

from agentcad.backends.autocad import find_accoreconsole
from conftest import ok

pytestmark = pytest.mark.skipif(find_accoreconsole() is None, reason="AutoCAD accoreconsole not installed")


@pytest.mark.parametrize("domain", ["architecture", "mechanical", "pid", "tolerance"])
def test_domain_and_tolerance_dwg_readback(rt, blank, domain, ws):
    if domain == "architecture":
        operations = [{"op": "draw_arch_plan", "spec": {
            "walls": [{"id": "outer", "axis": [[0, 0], [7000, 0], [7000, 5500], [0, 5500]],
                       "closed": True, "thickness": 240}],
            "rooms": [{"id": "room", "number": "02", "name": "Workshop", "at": [3000, 2000]}]}}]
    elif domain == "mechanical":
        operations = [{"op": "draw_mechanical_assembly", "spec": {
            "sheet": {"title": "Native roundtrip", "drawing_no": "NATIVE-03"},
            "parts": [
                {"name":"bush", "at":[135,195], "views":["front","section"],
                 "segments":[{"length":17.5,"d_outer":42,"d_inner":19},
                             {"length":23,"d_outer":60,"d_inner":19}]},
                {"name":"flange", "at":[350,190], "views":["front","side"],
                 "segments":[{"length":14,"d_outer":86,"d_inner":18}],
                 "features":[{"kind":"hole_circle","pcd":64,"count":8,"diameter":8.4,"start_angle":22.5}]}],
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
            assert len(after['manufacturing'])==2
            annotations=[a for p in after['manufacturing'] for a in p['annotations']]
            assert all(a['passed'] for a in annotations)
            doc=ezdxf.readfile(ws/'reopened.dxf')
            hole=next(a for a in annotations if a['kind']=='hole_diameter.0')
            entity=doc.entitydb[hole['handle']]
            assert entity.get_measurement()==pytest.approx(8.4)
            assert any('8.4' in e.text for e in doc.blocks[entity.dxf.geometry] if e.dxftype()=='MTEXT')
            doc.modelspace().delete_entity(entity);doc.saveas(ws/'damaged.dxf')
            assert rt.deliver_drawing('damaged.dxf','damaged',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


def test_large_manufacturing_record_survives_native_dwg(rt,blank):
    spec={'parts':[{'name':'index ring','at':[220,190],'views':['front','side'],
        'segments':[{'length':10,'d_outer':80,'d_inner':20}],
        'features':[{'kind':'hole_circle','pcd':60,'diameter':.5,'count':100}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    ok(rt.export_drawing(blank,'ring.dwg','dwg'))
    ok(rt.import_drawing('ring.dwg','ring.dxf'))
    read=ok(rt.read_engineering('ring.dxf','mechanical'))
    assert read['critique']==[] and len(read['parts'])==1
    assert len([c for c in read['circles'] if c['kind']=='bolt_hole'])==100
    assert all(p['passed'] for p in read['manufacturing'])
    audit=ok(rt.autocad_audit('ring.dxf'))
    assert audit['passed'] and audit['audit_errors']==0
