"""Round 1: plate width 120 -> 150; right holes follow (stay 12 from right edge)."""
import ezdxf
from ezdxf.math import Vec3

SRC, DST = 'part.dxf', 'part.dxf'
OLD_W, NEW_W = 120.0, 150.0
DX = NEW_W - OLD_W

doc = ezdxf.readfile(SRC)
db = doc.entitydb
if db['96'].get_measurement() != OLD_W:
    raise SystemExit('part.dxf already modified - abort')

# 1) outline: shift every vertex on the right side (x > half old width) by DX
outline = db['91']
pts = [(x + DX if x > OLD_W / 2 else x, y, s, e, b)
       for x, y, s, e, b in outline.get_points('xyseb')]
outline.set_points(pts, 'xyseb')

# 2) right holes
for h in ('93', '95'):
    c = db[h]
    c.dxf.center = Vec3(c.dxf.center) + (DX, 0, 0)

# 3) overall width dimension
wdim = db['96']
wdim.dxf.defpoint3 = Vec3(NEW_W, wdim.dxf.defpoint3.y, 0)
wdim.override().render()

# 4) 4X diameter dim sits on the upper-right hole -> move with it
ddim = db['D2']
for k in ('defpoint', 'defpoint4', 'text_midpoint'):
    ddim.dxf.set(k, Vec3(ddim.dxf.get(k)) + (DX, 0, 0))
ddim.override().render()

# drop the now-unreferenced old dimension geometry blocks
used = {d.dxf.geometry for d in doc.modelspace().query('DIMENSION')}
for name in [b.name for b in doc.blocks if b.name.startswith('*D') and b.name not in used]:
    doc.blocks.delete_block(name, safe=False)

doc.saveas(DST)
print('saved', DST)
