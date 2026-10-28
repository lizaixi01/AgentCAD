import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("frame_a3.dxf")
msp = doc.modelspace()
print("audit errors:", len(doc.audit().errors))
for p in msp.query("LWPOLYLINE"):
    print(p.dxf.layer, [tuple(round(v, 2) for v in pt[:2]) for pt in p.get_points()])
lines = msp.query("LINE")
xs = [c for l in lines for c in (l.dxf.start.x, l.dxf.end.x)]
ys = [c for l in lines for c in (l.dxf.start.y, l.dxf.end.y)]
print("lines:", len(lines), "x range", min(xs), max(xs), "y range", min(ys), max(ys))
for t in msp.query("TEXT"):
    print(f"{t.dxf.text!r:20} at ({t.dxf.align_point.x:.1f},{t.dxf.align_point.y:.1f}) h={t.dxf.height} style={t.dxf.style}")
print("extents:", bbox.extents(msp))
