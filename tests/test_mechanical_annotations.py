from copy import deepcopy
import math

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


@pytest.mark.parametrize('damage', ['delete','fake_text','scale','definition','cached_text','hidden','unplotted','bore',
                                  'dimension_block','dimension_paper','note_block','geometry_block','precision','postfix','units','partial_record'])
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
    elif damage in {'dimension_block','dimension_paper','note_block','geometry_block'}:
        if damage=='note_block':
            note=next(a for p in report['manufacturing'] for a in p['annotations'] if a['kind']=='pattern_orientation.0')
            dim=doc.entitydb[note['handle']]
        elif damage=='geometry_block':
            dim=doc.modelspace().query('LWPOLYLINE[layer=="HIDDEN"]')[0]
        target=doc.layouts.new('unused sheet') if damage=='dimension_paper' else doc.blocks.new('UNINSERTED')
        doc.modelspace().move_to_layout(dim,target)
    elif damage in {'precision','postfix','units'}:
        hole=next(a for p in report['manufacturing'] for a in p['annotations'] if a['kind']=='hole_diameter.0')
        dim=doc.entitydb[hole['handle']];override=dim.override()
        override.update({'precision':{'dimdec':0},'postfix':{'dimpost':'<> inches'},'units':{'dimlunit':4}}[damage])
        override.commit()  # Keep the old graphical cache: future regeneration must still be safe.
    else:
        part=next(p for p in report['manufacturing'] if row in p['annotations'])
        body=doc.entitydb[part['handle']];record=get(body,'mech')
        record['manufacturing']['annotations']=[a for a in record['manufacturing']['annotations'] if a['handle']!=dim.dxf.handle]
        doc.modelspace().delete_entity(dim);put(doc,body,'mech',record)
    doc.saveas(ws/blank); before=(ws/blank).read_bytes()
    checked=ok(Runtime(rt.policy).read_engineering(blank,'mechanical'))
    assert any(i['code'] in {'MANUFACTURING_ANNOTATION_MISMATCH','MANUFACTURING_GEOMETRY_CHANGED',
                            'MANUFACTURING_RECORD_INVALID'} for i in checked['critique'])
    assert rt.deliver_drawing(blank,'bad',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'
    assert (ws/blank).read_bytes()==before


@pytest.mark.parametrize('rounding',[0,1e-6])
def test_submicron_rounding_increment_cannot_use_geometry_tolerance(rt,blank,ws,rounding):
    spec={'parts':[{'name':'fine length','at':[130,190],
        'segments':[{'length':17.12345678,'d_outer':40}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'))
    row=next(a for a in report['manufacturing'][0]['annotations'] if a['kind']=='length.0')
    doc=ezdxf.readfile(ws/blank);dim=doc.entitydb[row['handle']]
    assert dim.override().get('dimrnd')==1e-8
    override=dim.override();override.update({'dimrnd':rounding});override.commit();doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code']=='MANUFACTURING_ANNOTATION_MISMATCH' for i in checked['critique'])
    assert rt.deliver_drawing(blank,'rounded',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


@pytest.mark.parametrize('damage',['definition','profile'])
def test_fine_nominal_changes_cannot_hide_behind_coarse_geometry_tolerance(rt,blank,ws,damage):
    spec={'parts':[{'name':'fine length','at':[130,190],
        'segments':[{'length':17.12345678,'d_outer':40}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));doc=ezdxf.readfile(ws/blank)
    if damage=='definition':
        row=next(a for a in report['manufacturing'][0]['annotations'] if a['kind']=='length.0')
        dim=doc.entitydb[row['handle']];dim.dxf.defpoint3=dim.dxf.defpoint3+(5e-7,0,0)
    else:
        body=doc.entitydb[report['parts'][0]['handle']]
        points=list(body.get_points('xy'));points[1]=(points[1][0]+5e-7,points[1][1]);body.set_points(points)
    doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code'] in {'MANUFACTURING_ANNOTATION_MISMATCH','MANUFACTURING_GEOMETRY_CHANGED'} for i in checked['critique'])
    assert rt.deliver_drawing(blank,'fine-error',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


@pytest.mark.parametrize('origin,length',[(1e7,17.12345678),(1e8,6.6),(1e8,17.12345678),(1e8,17.12345682)])
def test_large_coordinates_preserve_correct_nominal_display(rt,blank,origin,length):
    spec={'parts':[{'name':'offset part','at':[origin,190],'segments':[{'length':length,'d_outer':40}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'))
    assert report['critique']==[] and report['manufacturing'][0]['passed']
    row=next(a for a in report['manufacturing'][0]['annotations'] if a['kind']=='length.0')
    precision=1 if length==6.6 else 8
    assert f"{row['source_measurements'][0]:.{precision}f}"==f'{length:.{precision}f}'
    ok(rt.deliver_drawing(blank,'offset',formats=['dxf']))


@pytest.mark.parametrize('origin,length,ulps',[(1e7,17.12345678,4),(1e8,17.12345682,1)])
@pytest.mark.parametrize('edge',['both','bottom'])
def test_coordinate_ulp_allowance_cannot_change_source_nominal(rt,blank,ws,origin,length,ulps,edge):
    spec={'parts':[{'name':'offset part','at':[origin,190],'segments':[{'length':length,'d_outer':40}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    doc=ezdxf.readfile(ws/blank);body=doc.entitydb[report['parts'][0]['handle']]
    points=list(body.get_points('xy'));right=max(p[0] for p in points);changed=right
    for _ in range(ulps):changed=math.nextafter(changed,math.inf)
    body.set_points([(changed if x==right and (edge=='both' or y<190) else x,y) for x,y in points]);doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code']=='MANUFACTURING_ANNOTATION_MISMATCH' for i in checked['critique'])
    assert rt.deliver_drawing(blank,'offset-changed',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


@pytest.mark.parametrize('diameter',['outer','bore'])
def test_every_occurrence_and_end_of_a_repeated_diameter_is_checked(rt,blank,ws,diameter):
    fine=17.12345678
    spec={'parts':[{'name':'offset diameters','at':[135,1e7], 'segments':[
        {'length':17,'d_outer':fine if diameter=='outer' else 40,'d_inner':fine if diameter=='bore' else 0},
        {'length':23,'d_outer':60,'d_inner':0},
        {'length':11,'d_outer':fine if diameter=='outer' else 40,'d_inner':fine if diameter=='bore' else 0}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    doc=ezdxf.readfile(ws/blank)
    entity=(doc.entitydb[report['parts'][0]['handle']] if diameter=='outer' else
            doc.modelspace().query('LWPOLYLINE[layer=="HIDDEN"]')[0])
    points=list(entity.get_points('xy'));right=max(x for x,y in points)
    y=next(y for x,y in points if x==right and y>1e7);changed=y
    for _ in range(4):changed=math.nextafter(changed,math.inf)
    entity.set_points([(x,changed if x==right and v==y else v) for x,v in points]);doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code']=='MANUFACTURING_ANNOTATION_MISMATCH' for i in checked['critique'])
    assert rt.deliver_drawing(blank,'diameter-changed',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


@pytest.mark.parametrize('length',[17.123456789,1e-9])
def test_unrepresentable_annotation_precision_is_refused_atomically(rt,blank,ws,length):
    before=(ws/blank).read_bytes()
    result=rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':{'parts':[
        {'name':'too precise','at':[130,190],'segments':[{'length':length,'d_outer':40}]}]}}])
    assert result['error']['code'] in {'ANNOTATION_PRECISION','DEGENERATE_GEOMETRY'}
    assert (ws/blank).read_bytes()==before


@pytest.mark.parametrize('step,total',[(.58,29),(1.1,55),(.1,5)])
def test_many_decimal_segments_keep_their_nominal_overall_length(rt,blank,step,total):
    spec={'parts':[{'name':'many steps','at':[130,190],
        'segments':[{'length':step,'d_outer':40} for _ in range(50)]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    row=next(a for a in report['manufacturing'][0]['annotations'] if a['kind']=='overall_length')
    assert round(row['measurement'])==total
    ok(rt.deliver_drawing(blank,'many',formats=['dxf']))


@pytest.mark.parametrize('feature',['section_bore','section_outer','section_length','hidden_length'])
def test_each_drawn_view_is_bound_to_nominal_dimensions(rt,blank,ws,feature):
    fine=17.12345678
    vertical=feature in {'section_bore','section_outer'}
    spec={'parts':[{'name':'views','at':[135,1e7] if vertical else [1e7,190],
        'views':['front','section','side'],'segments':[{'length':20 if vertical else fine,
        'd_outer':fine if feature=='section_outer' else 40,
        'd_inner':fine if feature=='section_bore' else 10}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    doc=ezdxf.readfile(ws/blank)
    if feature=='hidden_length':
        entity=doc.modelspace().query('LWPOLYLINE[layer=="HIDDEN"]')[0]
    else:
        entity=next(e for e in doc.modelspace().query('LWPOLYLINE') if (get(e,'mech') or {}).get('role')=='section')
    points=list(entity.get_points('xy'));right=max(x for x,y in points)
    ys=[y for x,y in points if x==right]
    y=min(ys) if feature in {'section_bore','section_length'} else max(ys)
    value=y if vertical else right
    changed=value
    for _ in range(4):changed=math.nextafter(changed,math.inf)
    entity.set_points([(x,changed) if vertical and x==right and v==y else
                       (changed,v) if not vertical and x==right and v==y else (x,v) for x,v in points])
    doc.saveas(ws/blank)
    checked=ok(rt.read_engineering(blank,'mechanical'))
    assert any(i['code']=='MANUFACTURING_ANNOTATION_MISMATCH' for i in checked['critique'])
    assert rt.deliver_drawing(blank,'view-changed',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


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


def test_large_manufacturing_record_uses_owned_storage_and_missing_record_is_refused(rt,blank,ws,monkeypatch):
    spec={'parts':[{'name':'index ring','at':[220,190],'views':['front','side'],
        'segments':[{'length':10,'d_outer':80,'d_inner':20}],
        'features':[{'kind':'hole_circle','pcd':60,'diameter':.5,'count':100}]}]}
    ok(rt.apply_operations(blank,[{'op':'draw_mechanical_assembly','spec':spec}]))
    report=ok(rt.read_engineering(blank,'mechanical'));assert report['critique']==[]
    doc=ezdxf.readfile(ws/blank);body=doc.entitydb[report['parts'][0]['handle']]
    assert len(str(body.get_xdata('AGENTCAD_MECH')))<500
    assert body.has_extension_dict and len(get(body,'mech')['manufacturing']['geometry'])>300
    ok(rt.deliver_drawing(blank,'good-large',formats=['dxf']))
    export=rt.export_drawing
    def corrupt(path,output,format):
        result=export(path,output,format);saved=ezdxf.readfile(ws/output)
        saved.entitydb[body.dxf.handle].get_extension_dict()['AGENTCAD_MECH'].reset([(1,'INVALID JSON')])
        saved.saveas(ws/output);return result
    monkeypatch.setattr(rt,'export_drawing',corrupt)
    assert rt.deliver_drawing(blank,'corrupted-large',formats=['dxf'])['error']['code']=='DELIVERY_PARITY_FAILED'
    assert not (ws/'corrupted-large'/'manifest.json').exists()
    del body.get_extension_dict()['AGENTCAD_MECH'];doc.saveas(ws/blank)
    assert rt.read_engineering(blank,'mechanical')['error']['code']=='INVALID_DOMAIN_RECORD'
    assert not rt.deliver_drawing(blank,'missing-record',formats=['dxf'])['ok']
