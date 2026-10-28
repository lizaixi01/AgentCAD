import ezdxf
from ezdxf.math import Vec3

SRC, DST = 'part_orig.dxf', 'part.dxf'
TOL = 1e-6
doc = ezdxf.readfile(SRC)
msp = doc.modelspace()

# 1. layers per company standard (lineweight in 1/100 mm)
STD = {
    'OUTLINE': (7, 'Continuous', 50),
    'CENTER': (1, 'CENTER', 25),
    'DIM': (3, 'Continuous', 25),
    'TEXT': (4, 'Continuous', 25),
}
for name, (color, lt, lw) in STD.items():
    layer = doc.layers.get(name) if doc.layers.has_entry(name) else doc.layers.add(name)
    layer.color = color
    layer.dxf.linetype = lt
    layer.dxf.lineweight = lw

deleted = []

def desc(e):
    d = e.dxf
    t = e.dxftype()
    if t == 'LINE':
        return f'LINE #{d.handle} {tuple(d.start)[:2]}->{tuple(d.end)[:2]}'
    if t == 'CIRCLE':
        return f'CIRCLE #{d.handle} c={tuple(d.center)[:2]} r={d.radius}'
    return f'{t} #{d.handle}'

# 2. zero-length lines
for e in list(msp.query('LINE')):
    if e.dxf.start.isclose(e.dxf.end, abs_tol=TOL):
        deleted.append(desc(e) + '  (zero length)')
        msp.delete_entity(e)

# 3. exact duplicates: circles with same center/radius
seen = []
for e in list(msp.query('CIRCLE')):
    key = (e.dxf.center, e.dxf.radius)
    dup = next((s for s in seen if s[0].isclose(key[0], abs_tol=TOL) and abs(s[1] - key[1]) < TOL), None)
    if dup:
        deleted.append(desc(e) + f'  (duplicate of CIRCLE #{dup[2]})')
        msp.delete_entity(e)
    else:
        seen.append((key[0], key[1], e.dxf.handle))

# lines identical to another line or to a segment of the outline polyline
segments = []  # (p1, p2, owner handle)
for pl in msp.query('LWPOLYLINE'):
    pts = [Vec3(p[0], p[1]) for p in pl.get_points('xy')]
    n = len(pts) if pl.closed else len(pts) - 1
    for i in range(n):
        segments.append((pts[i], pts[(i + 1) % len(pts)], f'LWPOLYLINE #{pl.dxf.handle} edge {i}'))

def same_seg(a1, a2, b1, b2):
    return ((a1.isclose(b1, abs_tol=TOL) and a2.isclose(b2, abs_tol=TOL)) or
            (a1.isclose(b2, abs_tol=TOL) and a2.isclose(b1, abs_tol=TOL)))

for e in list(msp.query('LINE')):
    s, t = Vec3(e.dxf.start), Vec3(e.dxf.end)
    hit = next((seg for seg in segments if same_seg(s, t, seg[0], seg[1])), None)
    if hit:
        deleted.append(desc(e) + f'  (coincides with {hit[2]})')
        msp.delete_entity(e)
    else:
        segments.append((s, t, f'LINE #{e.dxf.handle}'))

# 4. assign layers, reset properties to ByLayer
def bylayer(e, layer):
    e.dxf.layer = layer
    e.dxf.color = 256
    e.dxf.linetype = 'BYLAYER'
    e.dxf.lineweight = -1  # BYLAYER
    if e.dxf.hasattr('true_color'):
        e.dxf.discard('true_color')

for e in msp:
    t = e.dxftype()
    if t in ('LWPOLYLINE', 'CIRCLE', 'ARC'):
        bylayer(e, 'OUTLINE')
    elif t == 'LINE':
        # remaining lines are all center lines (originally color 1)
        bylayer(e, 'CENTER')
    elif t == 'DIMENSION':
        bylayer(e, 'DIM')
        blk = doc.blocks.get(e.dxf.geometry)
        for x in blk:
            if x.dxf.layer == 'Defpoints':
                continue
            bylayer(x, 'DIM')
    elif t in ('TEXT', 'MTEXT'):
        bylayer(e, 'TEXT')
    else:
        print('UNHANDLED', t, e.dxf.handle)

# 5. remove empty layers
used = {e.dxf.layer for e in msp}
for b in doc.blocks:
    used |= {x.dxf.layer for x in b}
removed_layers = []
for layer in list(doc.layers):
    name = layer.dxf.name
    if name in ('0', 'Defpoints') or name in STD:
        continue
    if name not in used:
        removed_layers.append(name)
        doc.layers.remove(name)

doc.saveas(DST)
print('Deleted entities:')
for d in deleted:
    print('  ', d)
print('Removed layers:', removed_layers)
