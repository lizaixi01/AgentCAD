import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("slot_plate.dxf")
msp = doc.modelspace()
print("audit errors:", len(doc.audit().errors))

for e in msp:
    t = e.dxftype()
    if t == "LWPOLYLINE":
        pts = [tuple(round(v, 3) for v in p) for p in e.get_points("xyb")]
        ext = bbox.extents([e])
        print(t, e.dxf.layer, "closed" if e.closed else "open", pts,
              "bbox", tuple(round(v, 3) for v in ext.extmin)[:2], tuple(round(v, 3) for v in ext.extmax)[:2])
    elif t == "CIRCLE":
        print(t, e.dxf.layer, tuple(e.dxf.center)[:2], "D =", 2 * e.dxf.radius)
    elif t == "DIMENSION":
        print(t, "type", e.dimtype & 0x0F, "measurement =", round(e.get_measurement(), 3),
              "defpoints", tuple(round(v, 2) for v in e.dxf.defpoint)[:2],
              tuple(round(v, 2) for v in e.dxf.defpoint2)[:2], tuple(round(v, 2) for v in e.dxf.defpoint3)[:2])
        blk = doc.blocks.get(e.dxf.geometry)
        texts = [x.plain_text() for x in blk if x.dxftype() == "MTEXT"]
        print("   text:", texts)

all_ext = bbox.extents(msp)
print("overall extents:", all_ext.extmin, all_ext.extmax)
