import sys
import ezdxf

SRC = "part.dxf"
TMP = sys.argv[1] if len(sys.argv) > 1 else "part_r3_tmp.dxf"

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()

d2 = doc.entitydb["D2"]
print("D2 xdata:", d2.get_xdata("ACAD") if d2.has_xdata("ACAD") else None)

# plate outline extents -> centre
pts = [p[:2] for p in doc.entitydb["91"].get_points()]
cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
print("plate centre:", cx, cy)

if any(c.dxf.radius == 15 for c in msp.query("CIRCLE")):
    sys.exit("centre hole already present, nothing to do")

msp.add_circle((cx, cy), radius=15, dxfattribs={"layer": "HOLES"})

# diameter dimension, same style/angle as the existing 4X hole dim; text outside upper-right
dim = msp.add_diameter_dim(
    center=(cx, cy), radius=15, angle=45, location=None,
    dimstyle="EZDXF", override={"dimtoh": 1}, dxfattribs={"layer": "DIM"},
)
dim.render()

doc.saveas(TMP)
print("saved", TMP)
