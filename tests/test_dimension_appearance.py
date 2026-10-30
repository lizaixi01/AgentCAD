"""Check actual saved preview output, not a simulated property resolver."""
import re
import xml.etree.ElementTree as ET

import ezdxf
import pypdf
import pytest
from ezdxf.colors import TRANSPARENCY_BYBLOCK

from agentcad.viewer import Workspace


def text_alpha(svg):
    root=ET.fromstring(svg);ns='{http://www.w3.org/2000/svg}'
    classes={}
    for style in root.iter(ns+'style'):
        match=re.search(r'\.(\w+)\s*\{(.*?)\}',style.text or '')
        if match and 'fill: #ff00ff;' in match[2]:
            classes[match[1]]=float(re.search(r'fill-opacity:\s*([\d.]+)',match[2])[1])
    return [classes[e.get('class')] for e in root.iter(ns+'path') if e.get('class') in classes]


@pytest.mark.parametrize('case,alpha', [
    ('layer_zero_ignored',1),('parent_layer',0),('byblock',0),('opaque_override',1),
    ('partial_byblock',127/255),('own_layer',0),
])
def test_dimension_text_agrees_across_verification_svg_pdf_and_viewer(rt,ws,case,alpha):
    doc=ezdxf.new('R2010',setup=True,units=4)
    doc.layers.new('DIM');doc.layers.new('GEO');doc.layers.new('TEXT')
    doc.modelspace().add_line((0,0),(17,0),dxfattribs={'layer':'GEO'})
    o=doc.modelspace().add_linear_dim(base=(0,5),p1=(0,0),p2=(17,0),dimstyle='EZDXF',
        dxfattribs={'layer':'DIM'},override={'dimdec':2,'dimrnd':0,'dimlfac':1})
    o.render();dim=o.dimension;text=doc.blocks[dim.dxf.geometry].query('MTEXT').first
    text.rgb=(255,0,255);text.dxf.layer='0';text.dxf.discard('transparency')
    if case=='layer_zero_ignored':doc.layers.get('0').transparency=1
    elif case=='parent_layer':doc.layers.get('DIM').transparency=1
    elif case=='own_layer':text.dxf.layer='TEXT';doc.layers.get('TEXT').transparency=1
    else:
        dim.transparency=.5 if case=='partial_byblock' else 1
        text.dxf.transparency=TRANSPARENCY_BYBLOCK
        if case=='opaque_override':text.transparency=0
    doc.saveas(ws/'appearance.dxf')
    expected=alpha>0
    verified=rt.verify_dimensions('appearance.dxf',[{'id':'length','handle':dim.dxf.handle,'value':17}])
    assert verified['accepted'] is expected,verified
    assert rt.export_drawing('appearance.dxf','appearance.svg','svg')['ok']
    assert rt.export_drawing('appearance.dxf','appearance.pdf','pdf')['ok']
    workspace=Workspace(rt.policy,ws/'viewer-cache')
    for svg in ((ws/'appearance.svg').read_text('utf-8'),workspace.svg('appearance.dxf',None)):
        values=text_alpha(svg)
        assert values or not expected
        assert all(v==pytest.approx(alpha,abs=.001) for v in values),values
    content=pypdf.PdfReader(ws/'appearance.pdf').pages[0].get_contents().get_data().decode('latin-1')
    assert ('1 0 1 rg' in content) is expected


@pytest.mark.parametrize('text,passed',[('0.00E+00',True),('4.00E-03',False)])
def test_zero_scientific_geometry_does_not_gain_a_decimal_allowance(rt,ws,text,passed):
    from agentcad.dimension_display import read_display
    doc=ezdxf.new('R2010',setup=True,units=4)
    doc.modelspace().add_line((0,0),(6.5,0))
    o=doc.modelspace().add_linear_dim(base=(0,5),p1=(0,0),p2=(6.5,0),dimstyle='EZDXF',
        override={'dimlunit':1,'dimdec':2,'dimrnd':0,'dimlfac':1})
    o.render();dim=o.dimension;dim.dxf.defpoint3=dim.dxf.defpoint2
    doc.blocks[dim.dxf.geometry].query('MTEXT').first.text=text
    doc.saveas(ws/'zero.dxf')
    assert read_display(dim)['resolution']==0
    assert rt.validate_drawing('zero.dxf',detail=True)['validation']['passed'] is passed
    assert rt.deliver_drawing('zero.dxf','zero-delivery',formats=['dxf'])['ok'] is passed
