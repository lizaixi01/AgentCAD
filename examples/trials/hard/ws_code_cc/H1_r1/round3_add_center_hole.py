import math
import ezdxf
from ezdxf.math import Vec2

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

# Board centre from the outline bounding box
outline = msp.query('LWPOLYLINE[layer=="OUTLINE"]')[0]
pts = [Vec2(p) for p in outline.get_points("xy")]
cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
center = Vec2(cx, cy)
r = 15.0

msp.add_circle(center, r, dxfattribs={"layer": "HOLES"})

# Diameter dimension, same style/layer as the existing 4X hole dimension;
# leader at 45 deg, text placed outside the hole toward the upper right.
ang = math.radians(45)
loc = center + Vec2.from_angle(ang, r + 10)
dim = msp.add_diameter_dim(center=center, radius=r, location=loc,
                           dimstyle="EZDXF", dxfattribs={"layer": "DIM"})
dim.render()

doc.saveas("part.dxf")
print("center", center)
