import ezdxf, sys
from collections import Counter
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
for lay in doc.layouts:
    print("LAYOUT", lay.name, lay.dxf_layout.dxf.get('block_record_handle'), Counter(e.dxftype() for e in lay))
psp = doc.layouts.get(doc.layouts.names_in_taborder()[1])
print("msp INSERT:", [(e.dxf.name, e.dxf.insert, e.dxf.layer) for e in msp.query('INSERT')])
for e in psp:
    t = e.dxftype()
    if t == 'MTEXT':
        print("PS MTEXT", e.dxf.layer, e.dxf.insert, e.dxf.char_height, e.dxf.style, repr(e.text))
    if t == 'VIEWPORT':
        print("VP", e.dxf.center, e.dxf.width, e.dxf.height, e.dxf.view_center_point, e.dxf.view_height, e.dxf.status)
names = Counter()
for e in psp.query('INSERT'):
    names[(e.dxf.name.rstrip('0123456789'), e.dxf.layer)] += 1
print(names)
# compare circles msp vs psp
def key(e):
    return (round(e.dxf.center.x, 3), round(e.dxf.center.y, 3), round(e.dxf.radius, 4))
mc = sorted(key(e) for e in msp.query('CIRCLE'))
pc = sorted(key(e) for e in psp.query('CIRCLE'))
print("msp circles == psp circles:", mc == pc)
print("msp circle extents x", min(c[0] for c in mc), max(c[0] for c in mc), "y", min(c[1] for c in mc), max(c[1] for c in mc))
print("psp circle extents x", min(c[0] for c in pc), max(c[0] for c in pc), "y", min(c[1] for c in pc), max(c[1] for c in pc))
for d in (10.2, 25, 40):
    print(d, "msp", [k[:2] for k in mc if abs(k[2]*2-d) < 1e-3])
    print(d, "psp", [k[:2] for k in pc if abs(k[2]*2-d) < 1e-3])
print("dia exact values:", sorted(set(e.dxf.radius*2 for e in msp.query('CIRCLE'))))
for sp, nm in ((msp, 'msp'), (psp, 'psp')):
    xs = []; ys = []
    for l in sp.query('LINE'):
        xs += [l.dxf.start.x, l.dxf.end.x]; ys += [l.dxf.start.y, l.dxf.end.y]
    print(nm, "lines extent", min(xs), max(xs), min(ys), max(ys))
    print(nm, "line layers", Counter(l.dxf.layer for l in sp.query('LINE')))
# MTEXT in symbol blocks
for b in doc.blocks:
    if b.name.startswith('2dTransSymbol') or b.name in ('Title', 'Print#'):
        for x in b.query('MTEXT'):
            print(b.name, repr(x.text))
