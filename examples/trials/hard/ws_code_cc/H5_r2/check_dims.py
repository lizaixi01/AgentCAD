import ezdxf
from ezdxf import bbox
from ezdxf.math import BoundingBox2d

new = ezdxf.readfile("part.dxf")
old = ezdxf.readfile("part_orig.dxf")


def sig(e):
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return (t, e.dxf.layer, tuple(tuple(round(v, 6) for v in p) for p in e.get_points()), e.closed)
    if t == "LINE":
        return (t, e.dxf.layer, tuple(e.dxf.start), tuple(e.dxf.end))
    if t == "CIRCLE":
        return (t, e.dxf.layer, tuple(e.dxf.center), e.dxf.radius)
    if t == "ARC":
        return (t, e.dxf.layer, tuple(e.dxf.center), e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
    if t == "TEXT":
        return (t, e.dxf.layer, tuple(e.dxf.insert), e.dxf.text, e.dxf.height)
    return (t,)


old_sigs = [sig(e) for e in old.modelspace()]
new_geo = [sig(e) for e in new.modelspace() if e.dxftype() != "DIMENSION"]
print("原图形未改动:", old_sigs == new_geo)

# 图形线段（用于检测文字压线）
geo = [e for e in new.modelspace() if e.dxftype() != "DIMENSION"]
geo_boxes = []
for e in geo:
    if e.dxftype() == "LWPOLYLINE":
        pts = [p[:2] for p in e.get_points()]
        pts.append(pts[0])
        for a, b in zip(pts, pts[1:]):
            geo_boxes.append(("outline", a, b))
    elif e.dxftype() == "LINE":
        geo_boxes.append((e.dxf.layer, tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]))
    elif e.dxftype() in ("CIRCLE", "ARC"):
        c, r = e.dxf.center, e.dxf.radius
        geo_boxes.append(("circle", (c.x - r, c.y - r), (c.x + r, c.y + r)))
    elif e.dxftype() == "TEXT":
        b = bbox.extents([e])
        geo_boxes.append(("text", (b.extmin.x, b.extmin.y), (b.extmax.x, b.extmax.y)))


def seg_hits_box(a, b, bb, n=200):
    for i in range(n + 1):
        t = i / n
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        if bb.inside((x, y)):
            return True
    return False


dims = [e for e in new.modelspace() if e.dxftype() == "DIMENSION"]
print("尺寸数:", len(dims))
text_boxes = []
for d in dims:
    m = d.get_measurement()
    blk = new.blocks.get(d.dxf.geometry)
    txt = [e for e in blk if e.dxftype() == "MTEXT"]
    tb = bbox.extents(txt)
    box = BoundingBox2d([(tb.extmin.x, tb.extmin.y), (tb.extmax.x, tb.extmax.y)])
    text_boxes.append(box)
    hits = [g[0] + str(g[1:]) for g in geo_boxes if
            (g[0] in ("circle", "text") and box.has_intersection(BoundingBox2d([g[1], g[2]])))
            or (g[0] not in ("circle", "text") and seg_hits_box(g[1], g[2], box))]
    print(f"type={d.dimtype} layer={d.dxf.layer} meas={m:.3f} "
          f"text={[t.plain_text() for t in txt]} box=({box.extmin.x:.1f},{box.extmin.y:.1f})-"
          f"({box.extmax.x:.1f},{box.extmax.y:.1f}) 压线={hits}")

# 文字之间互相重叠
for i in range(len(text_boxes)):
    for j in range(i + 1, len(text_boxes)):
        if text_boxes[i].has_intersection(text_boxes[j]):
            print("文字重叠:", i, j)
print("检查结束")
