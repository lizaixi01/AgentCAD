import ezdxf, sys
from ezdxf import bbox
doc = ezdxf.readfile(sys.argv[1])
psp = doc.paperspace('Base Plate')
try:
    import matplotlib
    print("matplotlib", matplotlib.__version__)
except ImportError:
    print("no matplotlib")
# everything in psp whose bbox reaches below y=50
for e in psp:
    if e.dxftype() == 'VIEWPORT':
        continue
    b = bbox.extents([e])
    if b.has_data and b.extmin.y < 50:
        print(e.dxftype(), e.dxf.layer, (e.dxf.name if e.dxftype()=='INSERT' else ''), [round(v, 1) for v in (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)])
for e in psp.query('MTEXT'):
    print("MTEXT attach", e.dxf.attachment_point, e.dxf.get('width'), e.dxf.insert)
title = doc.blocks['Title']
for e in title:
    b = bbox.extents([e])
    print("Title", e.dxftype(), [round(v, 1) for v in (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)], (e.dxf.name if e.dxftype()=='INSERT' else ''))
for e in doc.blocks['Default Border']:
    b = bbox.extents([e])
    print("Border", e.dxftype(), [round(v, 1) for v in (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)])
