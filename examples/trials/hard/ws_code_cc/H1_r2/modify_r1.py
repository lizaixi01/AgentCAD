# Round 1: plate width 120 -> 150, right holes stay 12 from right edge.
import ezdxf
from ezdxf.math import Vec3

SRC = DST = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2\part.dxf"
OLD_W, NEW_W = 120.0, 150.0
DX = NEW_W - OLD_W
EPS = 1e-6

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()
db = doc.entitydb

# 1) outline: shift right-side vertices (x near 115/120) by DX, keep bulges
outline = db["91"]
pts = []
for x, y, s, e, b in outline.get_points("xyseb"):
    if x > OLD_W / 2:
        x += DX
    pts.append((x, y, s, e, b))
outline.set_points(pts, format="xyseb")

# 2) right-side holes: x = 108 -> 138
for h in ("93", "95"):
    c = db[h]
    assert abs(c.dxf.center.x - (OLD_W - 12)) < EPS
    c.dxf.center = Vec3(NEW_W - 12, c.dxf.center.y, 0)

# 3) overall width dimension (handle 96, block *D1)
dim = db["96"]
assert abs(dim.dxf.defpoint3.x - OLD_W) < EPS
dim.dxf.defpoint3 = Vec3(NEW_W, dim.dxf.defpoint3.y, 0)
tm = dim.dxf.text_midpoint
dim.dxf.text_midpoint = Vec3(NEW_W / 2, tm.y, tm.z)
blk = doc.blocks[dim.dxf.geometry]
for e in blk:
    t = e.dxftype()
    if t == "LINE":
        s, en = e.dxf.start, e.dxf.end
        if abs(s.y - en.y) < EPS:  # dimension line: extend right end
            if en.x > s.x:
                e.dxf.end = en + (DX, 0, 0)
            else:
                e.dxf.start = s + (DX, 0, 0)
        elif s.x > OLD_W / 2:      # right extension line
            e.translate(DX, 0, 0)
    elif t in ("INSERT", "POINT"):
        loc = e.dxf.insert if t == "INSERT" else e.dxf.location
        if loc.x > OLD_W / 2:
            e.translate(DX, 0, 0)
    elif t == "MTEXT":
        assert e.text == "120"
        e.text = "150"
        e.translate(DX / 2, 0, 0)

# 4) hole diameter callout (handle D2, block *D5) is attached to the top-right
#    hole -> move it together with the hole
ddim = db["D2"]
for attr in ("defpoint", "defpoint4", "text_midpoint"):
    if ddim.dxf.hasattr(attr):
        ddim.dxf.set(attr, ddim.dxf.get(attr) + (DX, 0, 0))
for e in doc.blocks[ddim.dxf.geometry]:
    e.translate(DX, 0, 0)

doc.saveas(DST)
print("saved")
