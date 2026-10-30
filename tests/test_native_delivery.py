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


@pytest.mark.parametrize('origin,length',[(130,17.12345678),(1e8,6.6),(1e8,17.12345678)])
def test_eight_decimal_nominal_dimension_survives_native_dwg(rt,blank,ws,origin,length):
    spec={'parts':[{'name':'fine length','at':[origin,190],
        'segments':[{'length':length,'d_outer':40}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    ok(rt.export_drawing(blank,'fine.dwg','dwg'))
    ok(rt.import_drawing('fine.dwg','fine.dxf'))
    assert not (ws/'fine.dxf').read_bytes().startswith(b'AutoCAD Binary DXF')
    report=ok(rt.read_engineering('fine.dxf','mechanical'))
    assert report['critique']==[]
    row=next(a for a in report['manufacturing'][0]['annotations'] if a['kind']=='length.0')
    doc=ezdxf.readfile(ws/'fine.dxf');dim=doc.entitydb[row['handle']]
    precision=1 if length==6.6 else 8
    assert f'{dim.get_measurement():.{precision}f}'==f'{length:.{precision}f}'
    assert dim.override().get('dimlunit')==2 and dim.override().get('dimrnd')==10**-precision
    assert any(str(length) in e.text for e in doc.blocks[dim.dxf.geometry] if e.dxftype()=='MTEXT')


def test_many_decimal_segments_and_fine_section_survive_native_dwg(rt,blank):
    spec={'parts':[{'name':'many fine sections','at':[135,1e7], 'views':['front','section','side'],
        'segments':[{'length':.58,'d_outer':40,'d_inner':17.12345678} for _ in range(50)]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    assert ok(rt.read_engineering(blank,'mechanical'))['critique']==[]
    ok(rt.export_drawing(blank,'segments.dwg','dwg'))
    ok(rt.import_drawing('segments.dwg','segments.dxf'))
    report=ok(rt.read_engineering('segments.dxf','mechanical'))
    assert report['critique']==[] and all(p['passed'] for p in report['manufacturing'])
    audit=ok(rt.autocad_audit('segments.dxf'))
    assert audit['passed'] and audit['audit_errors']==0


def test_generic_precision_and_angular_sectors_match_native_regeneration(rt,ws):
    from agentcad.backends.autocad import _run
    from agentcad.dimension_display import read_display
    from agentcad.model import measure_dimension
    doc=ezdxf.new('R2010',setup=True,units=4)
    msp=doc.modelspace()
    line1=((0,0),(50,0));line2=((0,0),(40,30))
    for line in (line1,line2):msp.add_line(*line)
    expected=[]
    for base,value in [((30,10),36.86989765),((0,30),143.13010235),
                       ((-30,-10),36.86989765),((0,-30),143.13010235)]:
        override=msp.add_angular_dim_2l(base=base,line1=line1,line2=line2,
            dimstyle='EZDXF',override={'dimlfac':100,'dimadec':2})
        override.render();expected.append((override.dimension.dxf.handle,value))
    doc.saveas(ws/'angles.dxf')
    for handle,_ in expected:
        ok(rt.apply_operations('angles.dxf',[{'op':'modify','target':handle,'set':{'text_height':2.5}}]))
    before=ezdxf.readfile(ws/'angles.dxf')
    for handle,value in expected:
        assert read_display(before.entitydb[handle])['value']==pytest.approx(round(value,2))
        # Force AutoCAD to construct its own graphics and measurement. Merely
        # re-exporting the cached block cannot independently verify our rendering.
        before.entitydb[handle].dxf.discard('geometry')
        before.entitydb[handle].dxf.discard('actual_measurement')
    before.saveas(ws/'definitions.dxf')
    job,_log=_run(ws/'native-jobs',{'in.dxf':ws/'definitions.dxf'},[
        '(command "_.DXFIN" "__JOBDIR__/in.dxf")',
        '(command "_.REGENALL")',
        '(command "_.DXFOUT" "__JOBDIR__/out.dxf" "_V" "2018" "_Binary")'])
    native=ezdxf.readfile(job/'out.dxf')
    import math
    for handle,value in expected:
        dim=native.entitydb[handle]
        assert math.degrees(dim.dxf.actual_measurement)==pytest.approx(value)
        assert measure_dimension(dim)==pytest.approx(value)
        assert read_display(dim)['value']==pytest.approx(round(value,2))
