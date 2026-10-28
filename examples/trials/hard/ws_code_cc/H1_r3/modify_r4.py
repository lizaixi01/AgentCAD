"""Round 4: revert round 2 - mounting holes Ø12 -> Ø10, restore the 4X diameter dim from the round-1 baseline."""
import sys
import ezdxf

SRC, BASE, DST = 'part.dxf', 'part_new.dxf', sys.argv[1]
OLD_R, NEW_R = 6.0, 5.0
HOLES = ('92', '93', '94', '95')

doc = ezdxf.readfile(SRC)
base = ezdxf.readfile(BASE)
db, bdb = doc.entitydb, base.entitydb
if abs(db['D2'].get_measurement() - 2 * OLD_R) > 1e-6:
    raise SystemExit('part.dxf holes are not Ø12 - abort')

# 1) hole radii (centres unchanged)
for h in HOLES:
    c = db[h]
    assert abs(c.dxf.radius - OLD_R) < 1e-9 and c.dxf.center.isclose(bdb[h].dxf.center)
    c.dxf.radius = NEW_R

# 2) diameter dim: take defpoints and text position back from the round-1 baseline
ddim, bdim = db['D2'], bdb['D2']
for attr in ('defpoint', 'defpoint4', 'text_midpoint'):
    ddim.dxf.set(attr, bdim.dxf.get(attr))
old_block = ddim.dxf.geometry
ddim.override().render()
if old_block != ddim.dxf.geometry:
    doc.blocks.delete_block(old_block, safe=False)

doc.saveas(DST)
print('saved', DST, 'new block', ddim.dxf.geometry)
