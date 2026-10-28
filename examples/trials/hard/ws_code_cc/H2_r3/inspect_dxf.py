import ezdxf, sys
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
print("version", doc.dxfversion, "units", doc.header.get('$INSUNITS'), "measurement", doc.header.get('$MEASUREMENT'))
msp = doc.modelspace()
print("msp types", Counter(e.dxftype() for e in msp))
print("layers", [l.dxf.name for l in doc.layers])
print("dimstyles", [d.dxf.name for d in doc.dimstyles], "cur", doc.header.get('$DIMSTYLE'))
print("textstyles", [(s.dxf.name, s.dxf.font) for s in doc.styles])
print("extmin/max", doc.header.get('$EXTMIN'), doc.header.get('$EXTMAX'))
c = Counter()
for e in msp.query('CIRCLE'):
    c[(round(e.dxf.radius * 2, 4), e.dxf.layer)] += 1
print("circles", sorted(c.items()))
for e in msp.query('ARC'):
    print("arc", round(e.dxf.radius * 2, 3), e.dxf.layer, e.dxf.center)
for b in doc.blocks:
    print("block", b.name, Counter(x.dxftype() for x in b))
for e in msp:
    t = e.dxftype()
    if t in ('INSERT', 'DIMENSION', 'TEXT', 'MTEXT', 'LWPOLYLINE', 'POLYLINE', 'HATCH', 'ELLIPSE', 'SPLINE'):
        txt = e.text[:60] if t == 'MTEXT' else e.dxf.get('text', None)
        print(t, e.dxf.layer, e.dxf.get('name', ''), e.dxf.get('insert', None), txt)
