import ezdxf, sys
from ezdxf import bbox
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
psp = doc.paperspace('Base Plate')
print("psp limits", psp.dxf_layout.dxf.limmin, psp.dxf_layout.dxf.limmax, "paper", psp.dxf_layout.dxf.paper_width, psp.dxf_layout.dxf.paper_height, psp.dxf_layout.dxf.plot_paper_units)
for sp, nm in ((msp, 'msp'), (psp, 'psp')):
    ve = [e for e in sp.query('LINE ARC') if e.dxf.layer == 'Visible Edges']
    print(nm, "Visible Edges bbox", bbox.extents(ve))
    sk = [e for e in sp.query('LINE') if e.dxf.layer == 'Sketch Lines']
    for l in sk:
        print(nm, "sketch", l.dxf.start, l.dxf.end)
    print(nm, "all bbox", bbox.extents(sp))
    print(nm, "diam set", sorted(Counter(round(c.dxf.radius * 2, 4) for c in sp.query('CIRCLE')).items()))
    print(nm, "circle attrs sample", sp.query('CIRCLE').first.dxfattribs())
for e in psp.query('INSERT'):
    if e.dxf.name == 'Title' or e.dxf.layer == 'Leader Lines':
        print("ins", e.dxf.name, e.dxf.insert, e.dxf.layer, bbox.extents([e]))
dims = [e for e in psp.query('INSERT') if e.dxf.layer == 'Dimensions']
print("psp dim symbols bbox", bbox.extents(dims))
cms = [e for e in psp.query('INSERT') if e.dxf.layer == 'Center Mark']
print("cm sample", cms[0].dxf.name, cms[0].dxf.insert, cms[0].dxf.xscale, [ (l.dxf.start, l.dxf.end) for l in doc.blocks[cms[0].dxf.name]])
ds = doc.dimstyles.get('2dTranslator Dimension Style')
print("dimstyle", {k: v for k, v in ds.dxfattribs().items()})
