# Round 3: add a central Dia.30 hole at the plate center and a diameter dimension for it.
import os
import shutil
import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3

D = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
SRC = DST = os.path.join(D, "part.dxf")
BACKUP = os.path.join(D, "part_r2_backup.dxf")
DIA = 30.0

if not os.path.exists(BACKUP):
    shutil.copyfile(SRC, BACKUP)

doc = ezdxf.readfile(BACKUP)
msp = doc.modelspace()

# guard: do not add twice
assert not any(abs(c.dxf.radius - DIA / 2) < 1e-6 for c in msp.query("CIRCLE")), "Dia.30 hole already exists"

# plate center from the outline bbox (outline h=91)
ob = bbox.extents([doc.entitydb["91"]])
center = ob.center
cx, cy = center.x, center.y

# hole, same layer/attributes as the existing mounting holes (layer HOLES, ByLayer)
msp.add_circle((cx, cy), DIA / 2, dxfattribs={"layer": "HOLES"})

# diameter dimension in the same style as the 4X callout (EZDXF, layer DIM, DIMTOH=1),
# always rebuilt from the round-2 backup so re-running is safe
# leader going out to the upper right at 45 deg into free plate area
dim = msp.add_diameter_dim(
    center=(cx, cy),
    radius=DIA / 2,
    angle=45,
    location=(cx + 18, cy + 18),
    dimstyle="EZDXF",
    # EZDXF style has dimtmove=2 (text moved without leader); force a leader
    override={"dimtoh": 1, "dimtmove": 1},
    dxfattribs={"layer": "DIM"},
)
dim.render()

# ezdxf renders a text-outside diameter like a radius (one arrow, line from the center).
# Make it look like the existing 4X callout (*D5): arrows at both circle points and the
# dimension line running across the full diameter, starting behind the outside arrow.
dimension = dim.dimension
blk = doc.blocks[dimension.dxf.geometry]
c = Vec3(cx, cy)
near_p = Vec3(dimension.dxf.defpoint4)  # text-side point on the circle
far_p = Vec3(dimension.dxf.defpoint)
u = (near_p - c).normalize()  # from center towards the text side
asz = doc.dimstyles.get("EZDXF").dxf.dimasz
lines = [e for e in blk.query("LINE") if Vec3(e.dxf.start).isclose(c) and Vec3(e.dxf.end).isclose(near_p)]
assert len(lines) == 1, lines
arrows = [e for e in blk.query("INSERT") if Vec3(e.dxf.insert).isclose(near_p)]
assert len(arrows) == 1, arrows
arrow = arrows[0]
lines[0].dxf.start = near_p + u * asz  # behind the outside arrow (same as the leader start)
lines[0].dxf.end = far_p + u * asz  # stops at the base of the far arrow
blk.add_blockref(
    arrow.dxf.name, far_p,
    dxfattribs={"layer": arrow.dxf.layer, "color": arrow.dxf.color, "rotation": arrow.dxf.rotation,
                "xscale": arrow.dxf.xscale, "yscale": arrow.dxf.yscale},
)

doc.saveas(DST)
print("center", (cx, cy), "saved")
