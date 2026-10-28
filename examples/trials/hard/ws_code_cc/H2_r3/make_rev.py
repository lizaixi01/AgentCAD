"""Generate part_rev.dxf from part.dxf (REV B hole changes)."""
import math
import sys
import ezdxf
from ezdxf.math import Vec2

SRC, DST = sys.argv[1], sys.argv[2]
PS_SCALE = 0.325  # paper-space view scale (psp = msp * 0.325, verified on all circles)
TOL = 1e-6
NOTE = "REV B: Ø10.2→Ø10.5, Ø25→Ø26"

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()
psp = doc.paperspace("Base Plate")

# 1 + 2: change hole diameters in place (handles / layer / color / center unchanged)
CHANGES = {10.2: 10.5, 25.0: 26.0}
for space, scale in ((msp, 1.0), (psp, PS_SCALE)):
    for c in space.query("CIRCLE"):
        d = c.dxf.radius * 2.0
        for old, new in CHANGES.items():
            if abs(d - old * scale) < TOL:
                c.dxf.radius = new * scale / 2.0
                break

# 3: diameter dimension on each Ø40 hole (model space 1:1, paper space view with DIMLFAC)
def add_dia_dims(space, scale):
    holes = [c for c in space.query("CIRCLE") if abs(c.dxf.radius * 2.0 - 40.0 * scale) < TOL]
    assert len(holes) == 2, holes
    for c in holes:
        center = Vec2(c.dxf.center)
        r = c.dxf.radius
        angle = 45.0
        # text 8 mm (on paper) outside the hole edge
        location = center + Vec2.from_deg_angle(angle, r + 8.0 * scale / PS_SCALE)
        override = {"dimzin": 8, "dimdec": 2, "dimtih": 0, "dimtoh": 0}
        if scale == 1.0:
            override["dimscale"] = 1.0 / PS_SCALE  # same look as on the 1:0.325 sheet
        else:
            override["dimlfac"] = 1.0 / scale  # display true size 40
        dim = space.add_diameter_dim(
            center=center, radius=r, angle=angle, location=location,
            dimstyle="2dTranslator Dimension Style", override=override,
            dxfattribs={"layer": "Dimensions"},
        )
        dim.render()

add_dia_dims(msp, 1.0)
add_dia_dims(psp, PS_SCALE)

# 4: revision note below the part outline, height 5
# model space: outline bottom y = 135.597, left x = 219.921 -> 20 mm below, left aligned
msp.add_text(NOTE, height=5, dxfattribs={"layer": "Text", "style": "Standard",
                                          "insert": (219.9205697994706, 115.0)})
# paper space: free strip between the notes (bottom y=18.5) and the frame (y=10)
psp.add_text(NOTE, height=5, dxfattribs={"layer": "Text", "style": "Standard",
                                          "insert": (15.0, 12.3)})

doc.saveas(DST)
print("saved", DST)
