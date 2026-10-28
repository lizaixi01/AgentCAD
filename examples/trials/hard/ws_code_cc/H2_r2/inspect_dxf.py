import sys, ezdxf
from collections import Counter
from ezdxf import bbox

doc = ezdxf.readfile(sys.argv[1])
print(doc.dxfversion, doc.header.get('$INSUNITS'), doc.header.get('$DIMSTYLE'))
msp = doc.modelspace()
print(Counter(e.dxftype() for e in msp))
print(Counter((e.dxftype(), e.dxf.layer) for e in msp))
c = Counter()
for e in msp.query('CIRCLE'):
    c[round(2 * e.dxf.radius, 3)] += 1
print('circles by dia:', sorted(c.items()))
for e in msp.query('CIRCLE'):
    print('CIRCLE', tuple(round(v, 3) for v in e.dxf.center), round(2 * e.dxf.radius, 4), e.dxf.layer, e.dxf.get('color'))
for e in msp.query('ARC'):
    print('ARC', e.dxf.center, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle, e.dxf.layer)
print('extents', bbox.extents(msp))
print('raw radii', sorted({repr(e.dxf.radius) for e in msp.query('CIRCLE')}))
for e in msp.query('LINE'):
    print('LINE', e.dxf.layer, tuple(round(v, 3) for v in e.dxf.start), tuple(round(v, 3) for v in e.dxf.end))
for e in msp.query('TEXT MTEXT DIMENSION INSERT'):
    print(e.dxftype(), e.dxf.layer, e.dxf.all_existing_dxf_attribs())
    if e.dxftype() == 'INSERT':
        blk = doc.blocks[e.dxf.name]
        print('  block', Counter(x.dxftype() for x in blk), bbox.extents(e.virtual_entities()))
        for x in blk.query('TEXT MTEXT ATTDEF'):
            print('   ', x.dxftype(), x.dxf.all_existing_dxf_attribs(), getattr(x, 'text', None))
        for a in e.attribs:
            print('   ATTRIB', a.dxf.tag, a.dxf.text)
for e in msp.query('DIMENSION'):
    print('DIM', e.dxf.all_existing_dxf_attribs())
for b in doc.blocks:
    print('BLOCK', b.name, len(b))
print([b.name for b in doc.blocks])
print([s.dxf.name for s in doc.dimstyles], [(s.dxf.name, s.dxf.font, s.get_extended_font_data()) for s in doc.styles])
for ds in doc.dimstyles:
    print('DIMSTYLE', ds.dxf.all_existing_dxf_attribs())
for lay in doc.layouts:
    print('LAYOUT', lay.name, Counter(e.dxftype() for e in lay))
print('$DWGCODEPAGE', doc.header.get('$DWGCODEPAGE'), '$TEXTSTYLE', doc.header.get('$TEXTSTYLE'), '$CLAYER', doc.header.get('$CLAYER'))
print([(l.dxf.name, l.dxf.color) for l in doc.layers])
