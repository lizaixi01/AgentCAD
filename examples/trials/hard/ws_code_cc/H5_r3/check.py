import sys
import ezdxf
sys.stdout.reconfigure(encoding="utf-8")
from ezdxf import bbox
from ezdxf.math import BoundingBox2d, Vec2

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()
geo = [e for e in msp if e.dxftype() != "DIMENSION"]
print("non-dim entities:", len(geo), [e.dxf.handle for e in geo])

# 原图形线段采样点，用于检查文字框是否压线
pts = []
for e in geo:
    if e.dxf.layer not in ("OUTLINE", "CENTER"):
        continue
    if e.dxftype() == "TEXT":
        continue
    for v in e.flattening(0.2) if hasattr(e, "flattening") else []:
        pts.append(Vec2(v))
    if e.dxftype() == "LINE":
        s, t = Vec2(e.dxf.start), Vec2(e.dxf.end)
        n = int(s.distance(t) / 0.2) + 1
        pts += [s.lerp(t, i / n) for i in range(n + 1)]
    if e.dxftype() == "LWPOLYLINE":
        vs = [Vec2(p[:2]) for p in e.get_points()]
        vs.append(vs[0])
        for s, t in zip(vs, vs[1:]):
            n = int(s.distance(t) / 0.2) + 1
            pts += [s.lerp(t, i / n) for i in range(n + 1)]

dims = msp.query("DIMENSION")
print("dimension count:", len(dims), "codepage:", doc.header.get("$DWGCODEPAGE"), doc.encoding)
print("title text:", repr(msp.query("TEXT")[0].dxf.text))
for d in dims:
    blk = d.get_geometry_block()
    texts = [e for e in blk if e.dxftype() in ("MTEXT", "TEXT")]
    txt = [t.plain_text() if t.dxftype() == "MTEXT" else t.dxf.text for t in texts]
    hits = 0
    for t in texts:
        bb = bbox.extents([t])
        b2 = BoundingBox2d([Vec2(bb.extmin), Vec2(bb.extmax)])
        hits += sum(1 for p in pts if b2.inside(p))
        box = (round(bb.extmin.x, 1), round(bb.extmin.y, 1), round(bb.extmax.x, 1), round(bb.extmax.y, 1))
    print(d.dxf.layer, d.dimtype, "meas=%.3f" % d.get_measurement() if not hasattr(d.get_measurement(), "x") else d.get_measurement(),
          "text=", txt, "box=", box, "line-hits=", hits)
