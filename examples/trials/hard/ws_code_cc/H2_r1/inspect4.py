import ezdxf, sys
from ezdxf import bbox
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
ps = doc.layouts.get('Base Plate')
# scale msp -> ps from matched circles
mc = {e.dxf.handle: e for e in msp if e.dxftype() == 'CIRCLE'}
pc = [e for e in ps if e.dxftype() == 'CIRCLE']
for h in ['177', '183', '185', '1EF']:
    m = mc[h]
    p = min(pc, key=lambda e: (e.dxf.center - m.dxf.center * 0.325).magnitude)
    print(h, p.dxf.handle, m.dxf.center * 0.325 - p.dxf.center, p.dxf.radius / m.dxf.radius)
cache = bbox.Cache()
print('ps total', bbox.extents((e for e in ps if e.dxftype() != 'VIEWPORT'), cache=cache))
for e in ps:
    if e.dxftype() in ('VIEWPORT',):
        continue
    b = bbox.extents([e], cache=cache)
    if b.has_data and (b.extmin.y < 60 or e.dxftype() != 'CIRCLE' and e.dxf.layer != 'Center Mark'):
        if e.dxf.layer in ('Center Mark',):
            continue
        print(e.dxftype(), e.dxf.layer, e.dxf.get('name') if e.dxftype() == 'INSERT' else '', [round(v, 1) for v in (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)])
print('Title block', bbox.extents(doc.blocks.get('Title')))
print('msp extents', bbox.extents(msp))
for e in msp:
    if e.dxftype() == 'INSERT':
        print('msp insert bbox', bbox.extents([e]))
