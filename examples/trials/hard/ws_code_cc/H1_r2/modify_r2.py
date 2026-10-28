# Round 2: mounting hole diameter 10 -> 12 (centers unchanged), update 4X diameter callout.
import os
import shutil
import ezdxf
from ezdxf.math import Vec3

D = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
SRC = DST = os.path.join(D, "part.dxf")
BACKUP = os.path.join(D, "part_r1_backup.dxf")
OLD_R, NEW_R = 5.0, 6.0
EPS = 1e-6

if not os.path.exists(BACKUP):
    shutil.copyfile(SRC, BACKUP)

doc = ezdxf.readfile(SRC)
db = doc.entitydb

# 1) the four holes: radius 5 -> 6
for h in ("92", "93", "94", "95"):
    c = db[h]
    assert abs(c.dxf.radius - OLD_R) < EPS
    c.dxf.radius = NEW_R

# 2) diameter dimension (handle D2, block *D5) on the top-right hole (138, 68).
#    defpoint / defpoint4 sit on the circle at 45deg; push them outward by
#    (NEW_R - OLD_R) along the diagonal. Text position and leader landing stay.
ddim = db["D2"]
center = Vec3(db["95"].dxf.center)
u = (Vec3(ddim.dxf.defpoint) - center).normalize()  # direction to defpoint (45deg)
dr = u * (NEW_R - OLD_R)
assert abs((Vec3(ddim.dxf.defpoint) - center).magnitude - OLD_R) < EPS
assert abs((Vec3(ddim.dxf.defpoint4) - center).magnitude - OLD_R) < EPS
old_p, old_p4 = Vec3(ddim.dxf.defpoint), Vec3(ddim.dxf.defpoint4)
ddim.dxf.defpoint = old_p + dr
ddim.dxf.defpoint4 = old_p4 - dr


def near(a, b):
    return Vec3(a).isclose(Vec3(b), abs_tol=1e-6)


blk = doc.blocks[ddim.dxf.geometry]
for e in blk:
    t = e.dxftype()
    if t == "INSERT":  # arrowheads at the two circle points
        if near(e.dxf.insert, old_p):
            e.dxf.insert = old_p + dr
        elif near(e.dxf.insert, old_p4):
            e.dxf.insert = old_p4 - dr
    elif t == "POINT" and near(e.dxf.location, old_p4):
        e.dxf.location = old_p4 - dr
    elif t == "LINE":
        if e.dxf.handle == "DA":  # dimension line between the arrows
            e.dxf.start = Vec3(e.dxf.start) - dr
            e.dxf.end = Vec3(e.dxf.end) + dr
        elif e.dxf.handle == "DB":  # leader from arrow to landing (landing fixed)
            e.dxf.start = Vec3(e.dxf.start) - dr
    elif t == "MTEXT":
        assert e.text == "4X %%c10", e.text
        e.text = "4X %%c12"

doc.saveas(DST)
print("saved")
