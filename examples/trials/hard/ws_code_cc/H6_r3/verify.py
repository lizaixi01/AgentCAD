import ezdxf
from ezdxf import bbox


def sig(doc):
    out = []
    for e in doc.modelspace():
        d = e.dxfattribs()
        d.pop("handle", None)
        d.pop("owner", None)
        out.append((e.dxftype(), sorted((k, str(v)) for k, v in d.items())))
    return out


orig = ezdxf.readfile("part_orig.dxf")
doc = ezdxf.readfile("part.dxf")
print("audit errors:", len(doc.audit().errors))
print("modelspace unchanged:", sig(orig) == sig(doc), len(sig(doc)))
print("layouts:", doc.layouts.names_in_taborder())

a3 = doc.layouts.get("A3")
d = a3.dxf_layout.dxf
print("paper", d.paper_width, d.paper_height, "margins", d.left_margin, d.bottom_margin, d.right_margin, d.top_margin,
      "units", d.plot_paper_units, "scale", d.scale_numerator, d.scale_denominator)
for e in a3:
    if e.dxftype() == "LWPOLYLINE":
        print("PLINE", e.dxf.layer, [tuple(round(v, 2) for v in p[:2]) for p in e.get_points()])
    elif e.dxftype() == "TEXT":
        print("TEXT", repr(e.dxf.text), e.dxf.height, e.dxf.align_point)
    elif e.dxftype() == "VIEWPORT":
        v = e.dxf
        print("VP id", v.id, "center", v.center, "w,h", v.width, v.height, "view_center", v.view_center_point,
              "view_height", v.view_height, "scale 1:%g" % (v.view_height / v.height), "status", v.status)

vps = [v for v in a3.viewports() if v.dxf.id != 1]
v = vps[0].dxf
x0, x1 = v.center.x - v.width / 2, v.center.x + v.width / 2
y0, y1 = v.center.y - v.height / 2, v.center.y + v.height / 2
print("vp paper box", x0, y0, x1, y1)
print("inside inner frame:", x0 >= 25 and x1 <= 415 and y0 >= 5 and y1 <= 292)
print("no overlap with title block (235..415, 5..45):", y0 >= 45 or x1 <= 235)
s = v.height / v.view_height
ext = bbox.extents(doc.modelspace())
px0 = v.center.x + (ext.extmin.x - v.view_center_point.x) * s
px1 = v.center.x + (ext.extmax.x - v.view_center_point.x) * s
py0 = v.center.y + (ext.extmin.y - v.view_center_point.y) * s
py1 = v.center.y + (ext.extmax.y - v.view_center_point.y) * s
print("part(with dims) on paper", round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2),
      "centre", round((px0 + px1) / 2, 2), round((py0 + py1) / 2, 2))
print("part fully in viewport:", px0 >= x0 and px1 <= x1 and py0 >= y0 and py1 <= y1)
