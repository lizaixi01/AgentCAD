import sys, ezdxf
from collections import Counter
from ezdxf import bbox

doc = ezdxf.readfile(sys.argv[1])
ps = doc.layouts.get('Base Plate')
print(Counter((e.dxftype(), e.dxf.layer) for e in ps))
c = Counter(round(2 * e.dxf.radius, 4) for e in ps.query('CIRCLE'))
print('ps circles', sorted(c.items()))
print('ps raw radii', sorted({repr(e.dxf.radius) for e in ps.query('CIRCLE')}))
print('ps extents', bbox.extents(ps))
for e in ps.query('CIRCLE'):
    print('PSCIRCLE', tuple(round(v, 3) for v in e.dxf.center), round(2 * e.dxf.radius, 4), e.dxf.layer)
for e in ps.query('LINE'):
    print('PSLINE', e.dxf.layer, tuple(round(v, 3) for v in e.dxf.start), tuple(round(v, 3) for v in e.dxf.end))
for e in ps.query('VIEWPORT'):
    print('VP', e.dxf.all_existing_dxf_attribs())
for e in ps.query('MTEXT'):
    print('MTEXT', e.dxf.layer, e.dxf.insert, e.dxf.char_height, repr(e.text))
ins = Counter()
for e in ps.query('INSERT'):
    ins[(e.dxf.name.rstrip('0123456789'), e.dxf.layer)] += 1
print(ins)
# texts inside the 2dTransSymbol / Title / Border blocks
for e in ps.query('INSERT'):
    blk = doc.blocks[e.dxf.name]
    txt = []
    for x in blk:
        if x.dxftype() == 'MTEXT':
            txt.append(x.text)
        elif x.dxftype() in ('TEXT', 'ATTDEF'):
            txt.append(x.dxf.text)
    if not e.dxf.name.startswith('2dCenterMark'):
        print('INS', e.dxf.name, e.dxf.layer, tuple(round(v, 2) for v in e.dxf.insert), e.dxf.get('xscale'), Counter(x.dxftype() for x in blk), txt)
