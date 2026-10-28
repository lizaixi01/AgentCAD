"""Compare round-1 file (argv1) with round-2 result (argv2): only holes + diameter dim may differ."""
import sys
import ezdxf

a, b = ezdxf.readfile(sys.argv[1]), ezdxf.readfile(sys.argv[2])
CHANGED = {'92', '93', '94', '95', 'D2'}


def sig(e):
    d = e.dxfattribs()
    d.pop('owner', None)
    extra = None
    if e.dxftype() == 'LWPOLYLINE':
        extra = list(e.get_points('xyseb'))
    elif e.dxftype() in ('MTEXT',):
        extra = e.text
    elif e.dxftype() == 'INSERT':
        extra = [(x.dxf.tag, x.dxf.text) for x in e.attribs]
    elif e.dxftype() == 'HATCH':
        extra = [[tuple(v) for v in p.vertices] if hasattr(p, 'vertices') else str(p) for p in e.paths]
    return str(d), str(extra)


ea = {e.dxf.handle: e for e in a.modelspace()}
eb = {e.dxf.handle: e for e in b.modelspace()}
assert ea.keys() == eb.keys(), (ea.keys() ^ eb.keys())
diff = [h for h in ea if sig(ea[h]) != sig(eb[h])]
print('changed entities:', diff)
assert set(diff) <= CHANGED, set(diff) - CHANGED

for h in ('92', '93', '94', '95'):
    ca, cb = ea[h], eb[h]
    print(h, 'center', tuple(cb.dxf.center), 'dia', 2 * cb.dxf.radius)
    assert ca.dxf.center.isclose(cb.dxf.center) and abs(cb.dxf.radius - 6) < 1e-9

d = eb['D2']
blk = b.blocks.get(d.dxf.geometry)
texts = [m.text for m in blk.query('MTEXT')]
c = (d.dxf.defpoint + d.dxf.defpoint4) / 2
print('dim measurement', d.get_measurement(), 'centre', c, 'text', texts, 'block', d.dxf.geometry)
assert abs(d.get_measurement() - 12) < 1e-9 and texts == ['4X %%c12'] and c.isclose((138, 68, 0))

# block table: TB untouched, no orphan *D blocks
used = {x.dxf.geometry for x in b.modelspace().query('DIMENSION')}
orphans = [bl.name for bl in b.blocks if bl.name.startswith('*D') and bl.name not in used]
print('orphan dim blocks:', orphans)
assert not orphans
assert [sig(x) for x in a.blocks.get('TB')] == [sig(x) for x in b.blocks.get('TB')]
for name in ('*D2', '*D3', '*D4', '*D6'):
    assert [sig(x) for x in a.blocks.get(name)] == [sig(x) for x in b.blocks.get(name)], name
print('OK')
