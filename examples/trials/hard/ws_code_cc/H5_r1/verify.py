import math
import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec2, BoundingBox2d

orig = ezdxf.readfile("part_orig.dxf")
new = ezdxf.readfile("part.dxf")


def sig(e):
    return (e.dxftype(), e.dxf.handle, e.dxf.layer, str(sorted(
        (k, str(v)) for k, v in e.dxfattribs().items())))


o = [sig(e) for e in orig.modelspace()]
n = [sig(e) for e in new.modelspace() if e.dxftype() != "DIMENSION"]
print("original entities unchanged:", o == n, len(o))
print("title text:", [t.dxf.text for t in new.modelspace().query("TEXT")])

# 几何线段（用于检测文字压线）
segs = []
for e in new.modelspace():
    if e.dxftype() == "DIMENSION":
        continue
    if e.dxftype() == "LINE":
        segs.append((e.dxf.layer, Vec2(e.dxf.start), Vec2(e.dxf.end)))
    elif e.dxftype() == "LWPOLYLINE":
        pts = [Vec2(p) for p in e.get_points("xy")]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            segs.append((e.dxf.layer, a, b))
circles = [(Vec2(e.dxf.center), e.dxf.radius) for e in new.modelspace().query("CIRCLE ARC")]


def seg_hits_box(a, b, box, n=200):
    for i in range(n + 1):
        p = a.lerp(b, i / n)
        if box.inside(p):
            return True
    return False


boxes = []
for d in new.modelspace().query("DIMENSION"):
    blk = d.get_geometry_block()
    texts = list(blk.query("MTEXT TEXT"))
    t = texts[0]
    raw = t.text if t.dxftype() == "MTEXT" else t.dxf.text
    h = t.dxf.char_height if t.dxftype() == "MTEXT" else t.dxf.height
    # 文本框：用 ezdxf bbox 估算
    bb = bbox.extents([t])
    box = BoundingBox2d([Vec2(bb.extmin), Vec2(bb.extmax)])
    hits = [s[0] for s in segs if seg_hits_box(s[1], s[2], box)]
    for c, r in circles:
        for k in range(360):
            p = c + Vec2.from_deg_angle(k, r)
            if box.inside(p):
                hits.append("circle/arc")
                break
    boxes.append((raw, box))
    print(f"{d.dimtype:3d} layer={d.dxf.layer} meas={d.get_measurement():8.3f} "
          f"text={raw!r:14} box=({box.extmin.x:.1f},{box.extmin.y:.1f})-({box.extmax.x:.1f},{box.extmax.y:.1f}) "
          f"hits={hits}")

# 文字互相重叠检查
for i in range(len(boxes)):
    for j in range(i + 1, len(boxes)):
        if boxes[i][1].has_intersection(boxes[j][1]):
            print("TEXT OVERLAP:", boxes[i][0], boxes[j][0])
