import ezdxf, sys
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
print(doc.dxfversion, doc.header.get('$INSUNITS'), doc.header.get('$DIMSTYLE'), doc.header.get('$DIMSCALE'))
msp = doc.modelspace()
print(Counter(e.dxftype() for e in msp))
print(Counter((e.dxftype(), e.dxf.layer) for e in msp))
c = Counter()
for e in msp:
    if e.dxftype() == 'CIRCLE':
        c[round(e.dxf.radius * 2, 3)] += 1
print(sorted(c.items()))
print('radii raw', sorted({repr(e.dxf.radius) for e in msp if e.dxftype() == 'CIRCLE'}))
for e in msp:
    if e.dxftype() == 'LINE':
        print('LINE', e.dxf.handle, e.dxf.layer, tuple(round(v, 3) for v in e.dxf.start), tuple(round(v, 3) for v in e.dxf.end))
for e in msp:
    if e.dxftype() == 'CIRCLE' and len(sys.argv) > 2:
        print('CIRCLE', e.dxf.handle, tuple(round(v, 3) for v in e.dxf.center), round(e.dxf.radius * 2, 4), e.dxf.layer)
for e in msp:
    if e.dxftype() == 'ARC':
        print('ARC', e.dxf.handle, tuple(round(v, 3) for v in e.dxf.center), round(e.dxf.radius, 4), e.dxf.start_angle, e.dxf.end_angle, e.dxf.layer)
for e in msp:
    if e.dxftype() in ('TEXT', 'MTEXT', 'DIMENSION', 'INSERT'):
        t = e.text if e.dxftype() == 'MTEXT' else (e.dxf.get('text', '') if e.dxftype() != 'INSERT' else '')
        g = lambda k: e.dxf.get(k) if e.dxf.is_supported(k) else None
        print(e.dxftype(), e.dxf.handle, e.dxf.layer, g('insert'), repr(t), g('name'), g('dimstyle'), g('height'), g('xscale'), g('rotation'))
        if e.dxftype() == 'INSERT':
            blk = doc.blocks.get(e.dxf.name)
            from collections import Counter as C2
            print('  block content', C2(x.dxftype() for x in blk), [x.dxf.get('text') for x in blk if x.dxftype() in ('TEXT', 'ATTDEF')][:30])
            print('  attribs', [(a.dxf.tag, a.dxf.text) for a in e.attribs])
print('blocks', [b.name for b in doc.blocks])
print('layers', [(l.dxf.name, l.dxf.color) for l in doc.layers])
print('dimstyles', [(s.dxf.name, s.dxf.get('dimtxt'), s.dxf.get('dimasz'), s.dxf.get('dimscale')) for s in doc.dimstyles])
print('styles', [(s.dxf.name, s.dxf.font, s.dxf.get('bigfont')) for s in doc.styles])
from ezdxf import bbox
print('bbox', bbox.extents(msp))
