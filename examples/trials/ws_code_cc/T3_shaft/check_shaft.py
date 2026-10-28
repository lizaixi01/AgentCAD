import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("shaft.dxf")
msp = doc.modelspace()
print("audit errors:", len(doc.audit().errors))
for e in msp:
    if e.dxftype() == "LWPOLYLINE":
        pts = [tuple(round(v, 3) for v in p[:2]) for p in e.get_points()]
        print("POLY", e.dxf.layer, "closed" if e.closed else "open", pts)
    elif e.dxftype() == "LINE":
        print("LINE", e.dxf.layer, doc.layers.get(e.dxf.layer).dxf.linetype,
              tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2])
    elif e.dxftype() == "DIMENSION":
        print("DIM", e.dxf.layer, "meas=%.3f" % e.get_measurement(), "text=%r" % e.dxf.text,
              "p1", tuple(round(v, 2) for v in e.dxf.defpoint2)[:2],
              "p2", tuple(round(v, 2) for v in e.dxf.defpoint3)[:2])
print("bbox outline:", bbox.extents(msp.query('*[layer=="OUTLINE"]')))
print("CENTER linetype present:", "CENTER" in doc.linetypes)
