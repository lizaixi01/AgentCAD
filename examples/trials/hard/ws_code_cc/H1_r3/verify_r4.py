"""Round 4 check: argv1 = pre-round-4 file, argv2 = result, argv3 = round-1 baseline (before round 2)."""
import sys
import ezdxf

pre, res, base = (ezdxf.readfile(f) for f in sys.argv[1:4])
CHANGED = {'92', '93', '94', '95', 'D2'}


def sig(e, skip=('owner', 'handle', 'geometry')):
    d = {k: v for k, v in e.dxfattribs().items() if k not in skip}
    extra = None
    if e.dxftype() == 'LWPOLYLINE':
        extra = list(e.get_points('xyseb'))
    elif e.dxftype() == 'MTEXT':
        extra = e.text
    elif e.dxftype() == 'INSERT':
        extra = [(x.dxf.tag, x.dxf.text) for x in e.attribs]
    elif e.dxftype() == 'HATCH':
        extra = [[tuple(v) for v in p.vertices] if hasattr(p, 'vertices') else str(p) for p in e.paths]
    xd = e.get_xdata('ACAD') if e.has_xdata('ACAD') else None
    return str(d), str(extra), str(xd)


ep = {e.dxf.handle: e for e in pre.modelspace()}
er = {e.dxf.handle: e for e in res.modelspace()}
eb = {e.dxf.handle: e for e in base.modelspace()}
assert ep.keys() == er.keys(), ep.keys() ^ er.keys()
diff = [h for h in ep if sig(ep[h], skip=('owner',)) != sig(er[h], skip=('owner',))]
print('changed vs pre-round-4:', diff)
assert set(diff) <= CHANGED, set(diff) - CHANGED

# holes and diameter dim identical to the pre-round-2 baseline
for h in sorted(CHANGED):
    assert sig(er[h]) == sig(eb[h]), h
for h in ('92', '93', '94', '95'):
    c = er[h]
    print(h, 'center', tuple(c.dxf.center), 'dia', 2 * c.dxf.radius)
    assert abs(c.dxf.radius - 5) < 1e-9

d = er['D2']
blk = res.blocks.get(d.dxf.geometry)
texts = [m.text for m in blk.query('MTEXT')]
c = (d.dxf.defpoint + d.dxf.defpoint4) / 2
print('D2 measurement', d.get_measurement(), 'centre', c, 'text', texts, 'block', d.dxf.geometry)
assert abs(d.get_measurement() - 10) < 1e-9 and texts == ['4X %%c10'] and c.isclose((138, 68, 0))
bblk = base.blocks.get(eb['D2'].dxf.geometry)
assert [sig(x) for x in blk] == [sig(x) for x in bblk], 'dim block differs from baseline'

# round 1 kept (plate 150 wide), round 3 kept (centre hole + Ø30 dim)
print('width dim', er['96'].get_measurement(), '| centre hole', tuple(er['13D'].dxf.center), 2 * er['13D'].dxf.radius,
      '| Ø30 dim', er['13E'].get_measurement())

# other blocks untouched, no orphan *D blocks
used = {x.dxf.geometry for x in res.modelspace().query('DIMENSION')}
orphans = [bl.name for bl in res.blocks if bl.name.startswith('*D') and bl.name not in used]
print('orphan dim blocks:', orphans)
assert not orphans
for bl in pre.blocks:
    if bl.name in (ep['D2'].dxf.geometry, '*Model_Space'):  # modelspace compared above
        continue
    assert [sig(x) for x in bl] == [sig(x) for x in res.blocks.get(bl.name)], bl.name
print('OK')
