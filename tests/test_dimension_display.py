import ezdxf
import pytest
from ezdxf.colors import TRANSPARENCY_BYBLOCK
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


@pytest.mark.parametrize('mode', ['text', 'layer', 'parent_layer', 'parent_block'])
@pytest.mark.parametrize('transparency', [0.0, 0.5, 1.0])
def test_saved_effective_transparency_controls_dimension_visibility(rt, ws, mode, transparency):
    from ezdxf.addons.drawing.properties import RenderContext
    handle=example(ws)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    text=doc.blocks[dim.dxf.geometry].query('MTEXT').first
    if mode=='text':text.transparency=transparency
    elif mode=='parent_block':
        dim.transparency=transparency;text.dxf.transparency=TRANSPARENCY_BYBLOCK
    else:
        layer=doc.layers.new('text_opacity');layer.transparency=transparency
        text.dxf.discard('transparency')
        if mode=='parent_layer':dim.dxf.layer=layer.dxf.name;text.dxf.layer='0'
        else:text.dxf.layer=layer.dxf.name
    context=RenderContext(doc);context.push_state(context.resolve_all(dim))
    assert context.resolve_all(text).color.endswith('00') is (transparency==1.0)
    doc.saveas(ws/'display.dxf');before=(ws/'display.dxf').read_bytes()
    verified=rt.verify_dimensions('display.dxf',[{'id':'bore','handle':handle,'value':6.4}])
    assert verified['accepted'] is (transparency<1),verified
    checked=rt.validate_drawing('display.dxf',detail=True)['validation']
    assert checked['passed'] is (transparency<1),checked
    delivered=rt.deliver_drawing('display.dxf','opacity',formats=['dxf','svg'])
    assert delivered['ok'] is (transparency<1),delivered
    assert (ws/'display.dxf').read_bytes()==before


@pytest.mark.parametrize('source', ['layer', 'parent'])
def test_explicit_opaque_text_overrides_transparent_layer_or_parent(rt, ws, source):
    handle=example(ws);doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    text=doc.blocks[dim.dxf.geometry].query('MTEXT').first
    if source=='parent':dim.transparency=1
    else:
        layer=doc.layers.new('transparent');layer.transparency=1;text.dxf.layer=layer.dxf.name
    text.transparency=0
    doc.saveas(ws/'display.dxf')
    assert rt.verify_dimensions('display.dxf',[{'id':'bore','handle':handle,'value':6.4}])['accepted']


@pytest.mark.parametrize('diameter,text,rounding,passed', [
    (.0065,'6.50E-03',0,True),(.0065,'9.90E-03',0,False),(.0065,'0.00E+00',0,False),
    (.00065,'6.50E-04',0,True),(.00065,'0.00E+00',0,False),(.00065,'9.90E-04',0,False),
    (6500,'6.50E+03',0,True),(6500,'9.90E+03',0,False),(.0065,'7.00E-03',.001,True),
    (.0065,'1.00E+03',0,False),
])
def test_scientific_precision_has_no_absolute_decimal_floor(rt, ws, diameter, text, rounding, passed):
    from agentcad.dimension_display import read_display
    handle=example(ws,precision=2,diameter=diameter)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    override=dim.override();override.update({'dimlunit':1,'dimdec':2,'dimrnd':rounding});override.commit()
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text='%%c'+text
    doc.saveas(ws/'display.dxf');before=(ws/'display.dxf').read_bytes()
    if diameter==.0065 and not rounding:assert read_display(dim)['resolution']==pytest.approx(.00001)
    checked=rt.validate_drawing('display.dxf',detail=True)['validation']
    assert checked['passed'] is passed,checked
    delivered=rt.deliver_drawing('display.dxf','scientific',formats=['dxf'])
    assert delivered['ok'] is passed,delivered
    assert (ws/'display.dxf').read_bytes()==before


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
    assert response['findings'][0]['kind']=='dimension_override_mismatch'


def test_a_wrong_display_and_override_have_one_primary_mismatch(rt,ws):
    handle=example(ws,diameter=6.4,text='9.9')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert not response['accepted'] and response['rows'][0]['displayed']==9.9
    assert response['rows'][0]['findings']==['dimension_mismatch','dimension_override_mismatch']
    assert response['findings']==[{'requirement':'hole','kind':'dimension_mismatch','handle':handle}]


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


@pytest.mark.parametrize('base,expected', [((30,10),36.86989765), ((0,30),143.13010235),
                                         ((-30,-10),36.86989765), ((0,-30),143.13010235)])
@pytest.mark.parametrize('reverse', [False, True])
def test_foreign_two_line_angle_uses_arc_sector_and_ignores_length_scale(rt,ws,base,expected,reverse):
    from agentcad.dimension_display import read_display
    from agentcad.model import measure_dimension
    from agentcad.validate.features import extract
    doc=ezdxf.new('R2010',setup=True,units=4)
    line1=((0,0),(50,0));line2=((0,0),(40,30))
    if reverse:line1,line2=tuple(reversed(line1)),tuple(reversed(line2))
    for line in (line1,line2):doc.modelspace().add_line(*line)
    dim=doc.modelspace().add_angular_dim_2l(base=base,line1=line1,line2=line2,
        dimstyle='EZDXF',override={'dimlfac':100,'dimadec':2})
    dim.render();handle=dim.dimension.dxf.handle;doc.saveas(ws/'angle.dxf')
    moved=rt.apply_operations('angle.dxf',[{'op':'move','target':handle,'delta':[5,0]},
        {'op':'move','target':handle,'delta':[-5,0]}],strict=True)
    assert moved['ok'],moved
    doc=ezdxf.readfile(ws/'angle.dxf');dim=doc.entitydb[handle]
    assert measure_dimension(dim)==pytest.approx(expected)
    assert read_display(dim)['value']==pytest.approx(round(expected,2))
    assert extract(doc).dimensions[0]['scaled_measurement']==pytest.approx(expected)


def test_foreign_rounded_deviation_retains_actual_nominal(rt,ws):
    handle=example(ws,diameter=6.4)
    doc=ezdxf.readfile(ws/'display.dxf');dim=doc.entitydb[handle]
    override=dim.override();override.update({'dimtol':1,'dimtp':.025,'dimtm':.025,'dimtdec':2});override.commit()
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text='%%c6.4{\\H0.7x;±0.03}'
    doc.saveas(ws/'display.dxf')
    response=rt.verify_dimensions('display.dxf',[{'id':'hole','handle':handle,'value':6.4}])
    assert response['accepted'] and response['rows'][0]['displayed']==6.4,response


@pytest.mark.parametrize('linear_units',[2,4,5])
def test_angular_precision_never_uses_the_linear_fraction_format(rt,blank,ws,linear_units):
    from agentcad.dimension_display import read_display
    result=rt.apply_operations(blank,[{'op':'add_line','start':[0,0],'end':[10,0]},
        {'op':'add_line','start':[0,0],'end':[5,8.660254037844386]},
        {'op':'add_angular_dim','center':[0,0],'p1':[10,0],'p2':[5,8.660254037844386]}])
    assert result['ok'],result
    doc=ezdxf.readfile(ws/blank);dim=doc.modelspace().query('DIMENSION').first
    override=dim.override();override.update({'dimlunit':linear_units,'dimadec':4});override.commit()
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text='60.0100°';doc.saveas(ws/blank)
    assert read_display(dim)['resolution']==.0001
    validation=rt.validate_drawing(blank)['validation']
    assert any(i['code']=='DIMENSION_RENDER_MISMATCH' for i in validation['issues'])
    assert rt.deliver_drawing(blank,'angle-damaged',formats=['dxf'])['error']['code']=='DELIVERY_REJECTED'


def test_non_decimal_angular_units_cannot_be_misread_as_decimal_degrees(rt,blank,ws):
    from agentcad.dimension_display import read_display
    assert rt.apply_operations(blank,[{'op':'add_angular_dim','center':[0,0],'p1':[10,0],'p2':[0,10]}])['ok']
    doc=ezdxf.readfile(ws/blank);dim=doc.modelspace().query('DIMENSION').first
    override=dim.override();override.update({'dimaunit':2});override.commit()
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text='90'
    assert read_display(dim)['value'] is None
