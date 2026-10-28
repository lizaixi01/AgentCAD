import math
from pathlib import Path

import ezdxf
from ezdxf.math import Vec2

HERE = Path(__file__).parent
SRC = HERE / "part.dxf"
DST = HERE / "part_rev.dxf"
TOL = 1e-6

# old diameter -> new diameter
CHANGES = {10.2: 10.5, 25.0: 26.0}
PS_SCALE = 0.325  # scale of the 2D copy in the "Base Plate" layout

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()
ps = doc.layouts.get("Base Plate")


def resize(layout, scale):
    changed = {}
    for c in layout.query("CIRCLE"):
        d = 2 * c.dxf.radius / scale
        for old, new in CHANGES.items():
            if abs(d - old) < TOL:
                c.dxf.radius = new * scale / 2
                changed[old] = changed.get(old, 0) + 1
    return changed


# 1 + 2: resize holes in model space and in the scaled layout copy
print("model space changed:", resize(msp, 1.0))
print("layout copy changed:", resize(ps, PS_SCALE))

# 3: diameter dimensions on the two Ø40 holes
big = sorted(
    (c for c in msp.query("CIRCLE") if abs(2 * c.dxf.radius - 40) < TOL),
    key=lambda c: c.dxf.center.x,
)
assert len(big) == 2, len(big)
angle = 75.0  # leader direction, points into the empty band above each hole
for c in big:
    center = Vec2(c.dxf.center)
    location = center + Vec2.from_deg_angle(angle, 40.0)
    dim = msp.add_diameter_dim(
        center=center,
        radius=c.dxf.radius,
        location=location,
        dimstyle="Standard",
        override={
            "dimtxt": 5,
            "dimasz": 4,
            "dimtxsty": "Standard",
            "dimdec": 0,
            "dimtad": 0,
        },
        dxfattribs={"layer": "Dimensions"},
    )
    dim.render()

# 4: revision note below the part outline (outline bottom edge is y=135.597)
outline_left = min(
    min(l.dxf.start.x, l.dxf.end.x)
    for l in msp.query('LINE[layer=="Visible Edges"]')
)
msp.add_text(
    "REV B: Ø10.2→Ø10.5, Ø25→Ø26",
    height=5,
    dxfattribs={"layer": "Text", "style": "Standard", "insert": (outline_left, 112.0)},
)

doc.saveas(DST)
print("saved", DST)
