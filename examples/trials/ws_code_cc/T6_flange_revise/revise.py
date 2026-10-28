import math
import os
import shutil

import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "flange.dxf")
BAK = os.path.join(HERE, "flange_orig.dxf")

N_HOLES = 8
HOLE_R = 6.0          # Ø12
PCD_R = 115.0 / 2     # Ø115
FIRST_ANGLE = 90.0    # first hole at top

if not os.path.exists(BAK):
    shutil.copyfile(SRC, BAK)

doc = ezdxf.readfile(BAK)
msp = doc.modelspace()


def polar(r, deg):
    a = math.radians(deg)
    return (r * math.cos(a), r * math.sin(a), 0.0)


# 1. pitch circle (center line circle on layer CENTER)
pcd_circles = [c for c in msp.query("CIRCLE[layer=='CENTER']")
               if math.isclose(c.dxf.radius, 55.0)]
assert len(pcd_circles) == 1
pcd_circles[0].dxf.radius = PCD_R

# 2. bolt holes: remove old 6, add 8 evenly spaced
old_holes = list(msp.query("CIRCLE[layer=='HOLES']"))
assert len(old_holes) == 6
for h in old_holes:
    msp.delete_entity(h)
for i in range(N_HOLES):
    msp.add_circle(polar(PCD_R, FIRST_ANGLE + i * 360.0 / N_HOLES), HOLE_R,
                   dxfattribs={"layer": "HOLES"})

# 3. dimensions
dims = {d.dxf.handle: d for d in msp.query("DIMENSION")}
hole_dim = next(d for d in dims.values() if "×" in d.dxf.text)
pcd_dim = next(d for d in dims.values()
               if math.isclose(d.get_measurement(), 110.0))

# hole dim: same 45° direction as before, moved to the new top hole (0, 57.5)
top = ezdxf.math.Vec3(polar(PCD_R, FIRST_ANGLE))
off = ezdxf.math.Vec3.from_deg_angle(45.0, HOLE_R)
hole_dim.dxf.defpoint = top + off
hole_dim.dxf.defpoint4 = top - off
hole_dim.dxf.text = f"{N_HOLES}×Ø12"

# PCD dim: as before, measured through two opposite hole centers (135°/315°)
pcd_dim.dxf.defpoint = polar(PCD_R, 135.0)
pcd_dim.dxf.defpoint4 = polar(PCD_R, 315.0)
pcd_dim.dxf.text = "<>"

# re-render the dimension geometry blocks, remove the stale ones
for dim in (hole_dim, pcd_dim):
    old_block = dim.dxf.geometry
    dim.override().render()
    if dim.dxf.geometry != old_block:
        doc.blocks.delete_block(old_block, safe=False)

doc.saveas(SRC)
print("saved", SRC)
