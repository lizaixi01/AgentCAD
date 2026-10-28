import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()
print("msp entities", len(msp), [(d.dxf.dimtype, round(d.get_measurement(), 3)) for d in msp.query("DIMENSION")])
ext = bbox.extents(msp)
print("msp ext", ext.extmin, ext.extmax)
lay = doc.layouts.get("A3")
print("layout A3 paper", lay.dxf.paper_width, lay.dxf.paper_height, "plot_paper_units", lay.dxf.plot_paper_units)
print("limits", lay.dxf.limmin, lay.dxf.limmax)
for e in lay:
    t = e.dxftype()
    if t == "LWPOLYLINE":
        print(t, e.dxf.layer, [tuple(round(v, 2) for v in p[:2]) for p in e.get_points()])
    elif t == "TEXT":
        print(t, repr(e.dxf.text), e.dxf.align_point, e.dxf.height)
    elif t == "VIEWPORT":
        print(t, "id", e.dxf.id, "center", e.dxf.center, "w", e.dxf.width, "h", e.dxf.height,
              "vc", e.dxf.view_center_point, "vh", e.dxf.view_height, "status", e.dxf.status)
vps = [v for v in lay.query("VIEWPORT") if v.dxf.id > 1]
for vp in vps:
    s = vp.dxf.height / vp.dxf.view_height
    cx, cy = vp.dxf.center.x, vp.dxf.center.y
    x0, x1 = cx - vp.dxf.width / 2, cx + vp.dxf.width / 2
    y0, y1 = cy - vp.dxf.height / 2, cy + vp.dxf.height / 2
    print("scale", s, "vp rect", (x0, y0, x1, y1))
    print("inside inner frame", x0 >= 25 and y0 >= 5 and x1 <= 415 and y1 <= 292)
    print("overlap title", not (x1 <= 235 or x0 >= 415 or y1 <= 5 or y0 >= 45))
    # 模型范围映射到图纸
    vc = vp.dxf.view_center_point
    px0 = cx + (ext.extmin.x - vc.x) * s; px1 = cx + (ext.extmax.x - vc.x) * s
    py0 = cy + (ext.extmin.y - vc.y) * s; py1 = cy + (ext.extmax.y - vc.y) * s
    print("part on paper", (round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2)),
          "fits", px0 >= x0 and px1 <= x1 and py0 >= y0 and py1 <= y1)
    print("part center on paper", ((px0 + px1) / 2, (py0 + py1) / 2), "inner frame center", (220, 148.5))
print("layouts", doc.layouts.names())
print("audit errors", len(doc.audit().errors))
