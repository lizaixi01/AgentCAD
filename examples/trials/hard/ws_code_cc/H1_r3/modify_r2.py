"""Round 2: mounting holes Ø10 -> Ø12 (centres unchanged); update the 4X diameter dim."""
import sys
import ezdxf
from ezdxf.math import Vec3

SRC, DST = 'part.dxf', sys.argv[1]
OLD_R, NEW_R = 5.0, 6.0
HOLES = ('92', '93', '94', '95')

doc = ezdxf.readfile(SRC)
db = doc.entitydb
if db['D2'].get_measurement() != 2 * OLD_R:
    raise SystemExit('part.dxf already modified - abort')

# 1) hole radii
for h in HOLES:
    c = db[h]
    assert abs(c.dxf.radius - OLD_R) < 1e-9
    c.dxf.radius = NEW_R

# 2) diameter dim: keep centre, direction and text position, scale the defpoints to the new radius
ddim = db['D2']
p1, p2 = Vec3(ddim.dxf.defpoint), Vec3(ddim.dxf.defpoint4)
center = (p1 + p2) / 2
direction = (p1 - center).normalize()
ddim.dxf.defpoint = center + direction * NEW_R
ddim.dxf.defpoint4 = center - direction * NEW_R
old_block = ddim.dxf.geometry
ddim.override().render()
if old_block != ddim.dxf.geometry:
    doc.blocks.delete_block(old_block, safe=False)

doc.saveas(DST)
print('saved', DST, 'new block', ddim.dxf.geometry)
