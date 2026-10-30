from copy import deepcopy

import ezdxf
import pytest

from agentcad.engineering.records import get, put
from agentcad.service import Runtime


def ok(result):
    assert result['ok'], result
    return result


SPEC = {
    'parts': [
        {'name': 'shaft', 'at': [135,195], 'views': ['front','section'],
         'segments': [{'length':17,'d_outer':42,'d_inner':19},
                      {'length':23,'d_outer':60,'d_inner':19},
                      {'length':11,'d_outer':34,'d_inner':19}]},
        {'name': 'flange', 'at': [350,190], 'views': ['front','side'],
         'segments': [{'length':14,'d_outer':86,'d_inner':18}],
         'features': [{'kind':'hole_circle','pcd':64,'count':8,'diameter':8.4,'start_angle':22.5}]},
    ],
}


def generated(rt, blank):
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':deepcopy(SPEC)}]))
    return ok(Runtime(rt.policy).read_engineering(blank,'mechanical'))


def test_complete_supplied_dimensions_survive_saved_readback_and_delivery(rt, blank, ws):
    report=generated(rt,blank)
    assert report['critique']==[]
    by_part={r['part']:{a['kind']:a['measurement'] for a in r['annotations']} for r in report['manufacturing']}
    assert by_part['shaft']=={'length.0':17,'outer_diameter.0':42,'bore_diameter.0':19,
        'length.1':23,'outer_diameter.1':60,'length.2':11,'outer_diameter.2':34,'overall_length':51}
    assert by_part['flange']==pytest.approx({'length.0':14,'outer_diameter.0':86,'bore_diameter.0':18,
        'hole_diameter.0':8.4,'pitch_diameter.0':64,'pattern_orientation.0':None})
    doc=ezdxf.readfile(ws/blank)
    for part in report['manufacturing']:
        assert part['passed'] and part['enabled']
        for row in part['annotations']:
            entity=doc.entitydb[row['handle']]
            if entity.dxftype()=='DIMENSION':
                assert entity.get_measurement()==pytest.approx(row['measurement'])
                assert '<>' in entity.dxf.text
    texts=[e.text for e in doc.modelspace().query('MTEXT')]
    assert any('45 deg' in t and '22.5 deg' in t for t in texts)
    assert any(e.dxf.text=='8X <>' for e in doc.modelspace().query('DIMENSION'))
    hole = next(a for p in report['manufacturing'] for a in p['annotations'] if a['kind']=='hole_diameter.0')
    block = doc.blocks[doc.entitydb[hole['handle']].dxf.geometry]
    assert any('8.4' in (e.text if e.dxftype()=='MTEXT' else e.dxf.text)
               for e in block if e.dxftype() in {'TEXT','MTEXT'})
    delivery=ok(rt.deliver_drawing(blank,'delivery',formats=['dxf','json']))
    assert delivery['ok']


@pytest.mark.parametrize('damage', ['delete','fake_text','scale','definition','cached_text','hidden','unplotted','bore'])
def test_wrong_or_missing_manufacturing_annotation_blocks_delivery(rt,blank,ws,damage):
    report=generated(rt,blank)
    row=next(a for p in report['manufacturing'] for a in p['annotations'] if a['kind']=='bore_diameter.0')
    doc=ezdxf.readfile(ws/blank); dim=doc.entitydb[row['handle']]
    if damage=='delete': doc.modelspace().delete_entity(dim)
    elif damage=='fake_text': dim.dxf.text='99'
    elif damage=='scale':
        override=dim.override();override.update({'dimlfac':2});override.commit()
    elif damage=='definition': dim.dxf.defpoint3=dim.dxf.defpoint3+(0,3,0)
    elif damage=='cached_text':
        text=next(e for e in doc.blocks[dim.dxf.geometry] if e.dxftype() in {'TEXT','MTEXT'})
        if text.dxftype()=='MTEXT': text.text='99'
        else: text.dxf.text='99'
    elif damage=='hidden': doc.layers.get('DIM').off()
    elif damage=='unplotted': doc.layers.get('DIM').dxf.plot=0
    elif damage=='bore':
        line=doc.modelspace().query('LWPOLYLINE[layer=="HIDDEN"]')[0]
        line.translate(0,1,0)
    doc.saveas(ws/blank); before=(ws/blank).read_bytes()
    checked=ok(Runtime(rt.policy).read_engineering(blank,'mechanical'))
    assert any(i['code'] in {'MANUFACTURING_ANNOTATION_MISMATCH','MANUFACTURING_GEOMETRY_CHANGED'} for i in checked['critique'])
    assert rt.deliver_drawing(blank,'bad',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'
    assert (ws/blank).read_bytes()==before


def test_pattern_note_is_geometry_bound_and_legacy_coverage_is_explicit(rt,blank,ws):
    report=generated(rt,blank);doc=ezdxf.readfile(ws/blank)
    note=next(a for p in report['manufacturing'] for a in p['annotations'] if a['kind']=='pattern_orientation.0')
    doc.entitydb[note['handle']].text='EQ SP 90 deg; FIRST 0 deg CCW FROM +X'
    doc.saveas(ws/blank)
    assert any(i['code']=='MANUFACTURING_ANNOTATION_MISMATCH' for i in ok(rt.read_engineering(blank,'mechanical'))['critique'])
    body=doc.entitydb[report['parts'][0]['handle']];record=get(body,'mech');record.pop('manufacturing');put(doc,body,'mech',record)
    doc.saveas(ws/blank)
    assert any(i['code']=='MANUFACTURING_COVERAGE_UNRECORDED' for i in ok(rt.read_engineering(blank,'mechanical'))['critique'])


def test_all_three_views_do_not_overlay_and_dimensions_can_be_explicitly_disabled(rt,blank,ws):
    spec={'parts':[{'name':'bush','at':[145,230],'views':['front','side','section'],'dimension':False,
        'segments':[{'length':20,'d_outer':40,'d_inner':15}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'))
    assert report['critique']==[] and not report['manufacturing'][0]['enabled']
    assert not report['manufacturing'][0]['annotations']
    assert all(c['center'][1]==155 for c in report['circles'])
    assert len(ezdxf.readfile(ws/blank).modelspace().query('DIMENSION'))==0


def test_feature_without_end_view_cannot_be_silently_ignored(rt,blank,ws):
    spec=deepcopy(SPEC);spec['parts'][1]['views']=['front']
    before=(ws/blank).read_bytes()
    assert rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}])['error']['code']=='INVALID_VIEW'
    assert (ws/blank).read_bytes()==before


@pytest.mark.parametrize('damage', ['missing_geometry','empty','bad_row','bad_value','hidden_leader'])
def test_malformed_coverage_and_invisible_leader_are_not_certified(rt,blank,ws,damage):
    report=generated(rt,blank);doc=ezdxf.readfile(ws/blank)
    body=doc.entitydb[report['parts'][1]['handle']];record=get(body,'mech')
    contract=record['manufacturing']
    if damage=='missing_geometry': contract.pop('geometry')
    elif damage=='empty': contract['annotations']=[]
    elif damage=='bad_row': contract['annotations'][0]=None
    elif damage=='bad_value': contract['annotations'][0]['value']='fourteen'
    else:
        note=next(a for a in contract['annotations'] if a['type']=='MTEXT')
        doc.entitydb[note['leader']].dxf.invisible=1
    put(doc,body,'mech',record);doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code'] in {'MANUFACTURING_RECORD_INVALID','MANUFACTURING_ANNOTATION_MISMATCH'} for i in checked['critique'])
    assert rt.deliver_drawing(blank,'invalid',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


def test_large_manufacturing_record_uses_owned_storage_and_missing_record_is_refused(rt,blank,ws):
    spec={'parts':[{'name':'index ring','at':[220,190],'views':['front','side'],
        'segments':[{'length':10,'d_outer':80,'d_inner':20}],
        'features':[{'kind':'hole_circle','pcd':60,'diameter':.5,'count':100}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    doc=ezdxf.readfile(ws/blank);body=doc.entitydb[report['parts'][0]['handle']]
    assert len(str(body.get_xdata('AGENTCAD_MECH')))<500
    assert body.has_extension_dict and len(get(body,'mech')['manufacturing']['geometry'])>300
    del body.get_extension_dict()['AGENTCAD_MECH'];doc.saveas(ws/blank)
    assert rt.read_engineering(blank,'mechanical')['error']['code']=='INVALID_DOMAIN_RECORD'
    assert not rt.deliver_drawing(blank,'missing-record',formats=['dxf'])['ok']
