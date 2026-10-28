import ezdxf, sys
from ezdxf import bbox
doc = ezdxf.readfile(sys.argv[1])
ps = doc.layouts.get('Base Plate')
t = [e for e in ps if e.dxftype() == 'INSERT' and e.dxf.name == 'Title'][0]
print('Title insert', t.dxf.insert, t.dxf.xscale, t.dxf.yscale, t.dxf.rotation)
for v in t.virtual_entities():
    b = bbox.extents([v])
    if not b.has_data:
        continue
    txt = ''
    if v.dxftype() == 'MTEXT':
        txt = v.text
    elif v.dxftype() in ('TEXT', 'ATTRIB', 'ATTDEF'):
        txt = v.dxf.text
    if b.extmin.y < 50 or txt:
        print(v.dxftype(), v.dxf.layer, [round(x, 1) for x in (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)], repr(txt)[:60])
for v in t.virtual_entities():
    if v.dxftype() == 'INSERT':
        print('nested', v.dxf.name)
