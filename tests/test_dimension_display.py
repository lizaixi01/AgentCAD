import ezdxf
import pytest
from ezdxf.tools.text import MTextEditor


def example(ws, precision=1, text=None, diameter=6.4):
    doc=ezdxf.new('R2010', units=4, setup=True)
    doc.modelspace().add_circle((50,50),diameter/2)
    dim=doc.modelspace().add_diameter_dim(center=(50,50),radius=diameter/2,angle=45,
        dimstyle='Standard',override={'dimdec':precision,'dimrnd':.1,'dimlfac':1,'dimzin':8})
    if text:dim.dimension.dxf.text=text
    dim.render()
    doc.saveas(ws/'display.dxf')
    return dim.dimension.dxf.handle


@pytest.mark.parametrize('precision,accepted,displayed',[(0,False,6),(1,True,6.4)])
def test_generic_verification_reads_actual_initial_rendered_value(rt,ws,precision,accepted,displayed):
    handle=example(ws,precision)
    before=(ws/'display.dxf').read_bytes()
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert response['ok'] and response['accepted'] is accepted,response
    assert response['rows'][0]['displayed']==displayed
    checked=rt.validate_drawing('display.dxf',detail=True,requirements=[{'type':'dimension','kind':'diameter','value':6.4}])
    assert checked['validation']['requirements'][0]['status']==('pass' if accepted else 'fail')
    assert (ws/'display.dxf').read_bytes()==before


@pytest.mark.parametrize('damage',['cached_value','missing','hidden','ambiguous','multiple'])
def test_missing_or_altered_graphics_cannot_be_inferred_from_geometry(rt,ws,damage):
    handle=example(ws)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    block=doc.blocks[dim.dxf.geometry];text=block.query('MTEXT').first
    if damage=='cached_value':text.text='%%c99'
    elif damage=='missing':block.delete_entity(text)
    elif damage=='hidden':text.dxf.invisible=1
    elif damage=='ambiguous':text.text='%%c6.4 99'
    else:block.add_text('6.4',dxfattribs={'height':2.5})
    doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert response['ok'] and not response['accepted'],response
    checked=rt.validate_drawing('display.dxf',detail=True,requirements=[{'type':'dimension','kind':'diameter','value':6.4}])
    assert checked['validation']['requirements'][0]['status']=='fail'
    if damage=='cached_value':
        assert any(i['code']=='DIMENSION_RENDER_MISMATCH' for i in checked['validation']['issues'])
        assert rt.deliver_drawing('display.dxf','damaged',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


def test_literal_prefix_suffix_numbers_do_not_become_the_nominal_value(rt,ws):
    handle=example(ws,text='M14 <> H7')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert response['ok'] and response['accepted'],response
    assert response['rows'][0]['displayed']==6.4


@pytest.mark.parametrize('text,units', [('%%c6.5E+00',1),('%%c6 1/2',5),('%%c0\'-6 1/2"',4)])
def test_saved_scientific_and_fractional_display_is_read_instead_of_inferred(rt,ws,text,units):
    handle=example(ws,diameter=6.5)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    override=dim.override();override.update({'dimlunit':units,'dimdsep':ord('.')});override.commit()
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text=text
    doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.5}])
    assert response['ok'] and response['accepted'],response
    assert response['rows'][0]['displayed']==6.5


def test_stale_numeric_override_does_not_replace_actual_saved_display(rt,ws):
    handle=example(ws)
    doc=ezdxf.readfile(ws/'display.dxf');doc.entitydb[handle].dxf.text='99';doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert not response['accepted'] and response['rows'][0]['displayed']==6.4
    assert 'dimension_override_mismatch' in response['rows'][0]['findings']


@pytest.mark.parametrize('mode',['deviations','limits'])
def test_native_tolerance_rendering_retains_verifiable_nominal(rt,blank,mode):
    created=rt.apply_operations(blank,[{'op':'add_circle','center':[0,0],'diameter':35},
        {'op':'add_diameter_dim','target':'$0','tolerance':{'lower':-.012,'upper':.025,'precision':3,'mode':mode}}])
    assert created['ok'],created
    handle=rt.inspect_entities(blank,{'type':'DIMENSION'})['entities'][0]['id']
    response=rt.verify_dimensions(blank,[{'id':'bore','handle':handle,'value':35}])
    assert response['ok'] and response['accepted'],response


@pytest.mark.parametrize('diameter,accepted',[(6.4,True),(6.0,False)])
def test_numeric_suffix_is_removed_only_at_its_literal_boundary(rt,ws,diameter,accepted):
    handle=example(ws,diameter=diameter,text='<> 4')
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text='%%c6.4 4'
    doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':diameter}])
    assert response['accepted'] is accepted and response['rows'][0]['displayed']==6.4,response
    if not accepted:
        assert rt.deliver_drawing('display.dxf','suffix',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


@pytest.mark.parametrize('style',['/','#','^'])
@pytest.mark.parametrize('spacing',[' ',''])
@pytest.mark.parametrize('diameter,accepted',[(6.5,True),(6.0,False)])
def test_nominal_stack_is_distinct_from_a_trailing_tolerance_stack(rt,ws,style,spacing,diameter,accepted):
    handle=example(ws,diameter=diameter)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    override=dim.override()
    override.update({'dimlunit':5,'dimfrac':0,'dimtol':1,'dimtp':.1,'dimtm':.1,'dimtdec':1,
                     'dimdec':1,'dimrnd':0,'dimlfac':1,'dimdsep':46})
    override.commit()
    nominal_stack=str(MTextEditor().stack('1','2',style))
    deviation_stack=str(MTextEditor().stack('+0.1','-0.1','^'))
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text=(
        '%%c6'+spacing+'{\\H0.7x;'+nominal_stack+'} {\\H0.7x;'+deviation_stack+'}')
    doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':diameter}])
    assert response['accepted'] is accepted and response['rows'][0]['displayed']==6.5,response
    if not accepted:
        assert rt.deliver_drawing('display.dxf','fraction',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


def test_digit_suffix_without_a_delimiter_cannot_certify_an_ambiguous_primary_value(rt,ws):
    handle=example(ws,diameter=6,text='<>4')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6}])
    assert not response['accepted'] and response['rows'][0]['displayed'] is None


def test_zero_rounding_keeps_fractional_rendering_and_future_precision_changes(rt,blank,ws):
    result=rt.apply_operations(blank,[{'op':'add_line','start':[0,0],'end':[6.666666,0]},
        {'op':'add_linear_dim','p1':[0,0],'p2':[6.666666,0]}])
    assert result['ok'],result
    doc=ezdxf.readfile(ws/blank);dim=doc.modelspace().query('DIMENSION').first
    assert dim.override().get('dimrnd',0)==0
    assert any('6.67' in e.text for e in doc.blocks[dim.dxf.geometry].query('MTEXT'))
    override=dim.override();override.update({'dimdec':3});override.commit();doc.saveas(ws/blank)
    modified=rt.apply_operations(blank,[{'op':'modify','target':dim.dxf.handle,'set':{'text_height':3.5}}])
    assert modified['ok'],modified
    saved=ezdxf.readfile(ws/blank);updated=saved.entitydb[dim.dxf.handle]
    assert updated.override().get('dimrnd',0)==0
    assert any('6.667' in e.text for e in saved.blocks[updated.dxf.geometry].query('MTEXT'))
