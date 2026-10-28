import ezdxf, sys
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
ps = doc.layouts.get('Base Plate')
print('limits/extents', ps.dxf.get('limmin'), ps.dxf.get('limmax'))
print(Counter((e.dxftype(), e.dxf.layer) for e in ps))
c = Counter(round(e.dxf.radius * 2, 3) for e in ps if e.dxftype() == 'CIRCLE')
print('ps circles', sorted(c.items()))
circ = [e for e in ps if e.dxftype() == 'CIRCLE']
for e in circ[:6]:
    print('  ', e.dxf.handle, e.dxf.center, e.dxf.radius)
for e in ps:
    if e.dxftype() == 'VIEWPORT':
        print('VP', e.dxf.center, e.dxf.width, e.dxf.height, e.dxf.view_center_point, e.dxf.view_height, e.dxf.get('status'))
    if e.dxftype() == 'MTEXT':
        print('MTEXT', e.dxf.layer, e.dxf.insert, repr(e.text))
names = Counter()
for e in ps:
    if e.dxftype() == 'INSERT':
        names[e.dxf.name.rstrip('0123456789')] += 1
print(names)
seen = 0
for e in ps:
    if e.dxftype() == 'INSERT' and e.dxf.name.startswith('2dTransSymbol'):
        blk = doc.blocks.get(e.dxf.name)
        txt = []
        for x in blk:
            if x.dxftype() == 'MTEXT':
                txt.append(x.text)
            elif x.dxftype() == 'TEXT':
                txt.append(x.dxf.text)
        print(e.dxf.name, e.dxf.layer, tuple(round(v, 2) for v in e.dxf.insert), dict(Counter(x.dxftype() for x in blk)), txt)
for e in ps:
    if e.dxftype() == 'INSERT' and not e.dxf.name.startswith(('2dTransSymbol', '2dCenterMark')):
        print('other insert', e.dxf.name, e.dxf.layer, e.dxf.insert, e.dxf.get('xscale'))
print('ps bbox', ezdxf.bbox.extents(e for e in ps if e.dxftype() != 'VIEWPORT'))
