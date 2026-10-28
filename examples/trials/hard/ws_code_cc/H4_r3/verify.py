import ezdxf
from ezdxf import audit

a = ezdxf.readfile('part_orig.dxf')
b = ezdxf.readfile('part.dxf')
ma, mb = a.modelspace(), b.modelspace()
DELETED = {'A0', 'A1', '93', '9E', '9F'}

print('Layers:')
for l in b.layers:
    print(f'  {l.dxf.name:10s} color={l.color} lt={l.dxf.linetype} lw={l.dxf.lineweight}',
          'count=', sum(1 for e in mb if e.dxf.layer == l.dxf.name))

ok = True
EXPECT = {'LWPOLYLINE': 'OUTLINE', 'CIRCLE': 'OUTLINE', 'LINE': 'CENTER',
          'DIMENSION': 'DIM', 'TEXT': 'TEXT', 'MTEXT': 'TEXT'}
for e in mb:
    d = e.dxf
    if d.layer != EXPECT[e.dxftype()] or d.color != 256 or d.linetype.upper() != 'BYLAYER' or d.lineweight != -1:
        ok = False
        print('BAD props', e.dxftype(), d.handle)
for blk in b.blocks:
    if blk.name.startswith('*D'):
        for x in blk:
            if x.dxf.layer != 'Defpoints' and (x.dxf.layer != 'DIM' or x.dxf.color != 256):
                ok = False
                print('BAD block entity', blk.name, x.dxftype())

# geometry / values unchanged for every kept entity
def sig(e):
    t, d = e.dxftype(), e.dxf
    if t == 'LINE': return (tuple(d.start), tuple(d.end))
    if t == 'CIRCLE': return (tuple(d.center), d.radius)
    if t == 'LWPOLYLINE': return (e.closed, tuple(map(tuple, e.get_points())))
    if t == 'TEXT': return (d.text, tuple(d.insert), d.height)
    if t == 'MTEXT': return (e.text, tuple(d.insert), d.char_height)
    if t == 'DIMENSION': return (d.dimtype, round(e.get_measurement(), 9), d.get('text'), d.geometry)

sa = {e.dxf.handle: (e.dxftype(), sig(e)) for e in ma if e.dxf.handle not in DELETED}
sb = {e.dxf.handle: (e.dxftype(), sig(e)) for e in mb}
print('kept entities match original:', sa == sb, len(sa), len(sb))
ok &= sa == sb
for h, (t, s) in sb.items():
    if t == 'DIMENSION': print('  DIM', h, s[1])
    if t in ('TEXT', 'MTEXT'): print('  ', t, s[0].encode('unicode_escape'))

# no remaining duplicates / zero-length lines
lines = [(tuple(e.dxf.start), tuple(e.dxf.end)) for e in mb.query('LINE')]
print('zero-length lines:', sum(1 for s, t in lines if s == t))
circles = [(tuple(e.dxf.center), e.dxf.radius) for e in mb.query('CIRCLE')]
print('duplicate circles:', len(circles) - len(set(circles)))

r = b.audit()
print('audit errors:', len(r.errors), 'fixes:', len(r.fixes))
print('ALL OK' if ok else 'PROBLEMS FOUND')
