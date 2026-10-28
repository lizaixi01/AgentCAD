import ezdxf
from ezdxf import bbox

orig = ezdxf.readfile("part_orig.dxf")
doc = ezdxf.readfile("part.dxf")
print("audit errors:", len(doc.audit().errors))


def sig(d):
    out = []
    for e in d.modelspace():
        out.append((e.dxftype(), e.dxf.layer, str(sorted(
            (k, str(v)) for k, v in e.dxf.all_existing_dxf_attribs().items() if k not in ("handle", "owner")))))
    return sorted(out)


print("modelspace unchanged:", sig(orig) == sig(doc))
print("layouts:", doc.layouts.names())
lay = doc.layouts.get("A3")
p = lay.dxf_layout.dxf
print("paper", p.paper_width, p.paper_height, "units", p.plot_paper_units, "rot", p.plot_rotation)
for e in lay:
    t = e.dxftype()
    if t == "LWPOLYLINE":
        pts = [tuple(round(c, 2) for c in pt[:2]) for pt in e.get_points()]
        print(t, e.dxf.layer, pts)
    elif t == "TEXT":
        print(t, e.dxf.text, tuple(round(c, 2) for c in tuple(e.dxf.align_point)[:2]), e.dxf.height, e.dxf.style)
    elif t == "VIEWPORT":
        d = e.dxf
        print(t, "id", d.id, "center", d.center, "size", d.width, d.height,
              "view_center", d.view_center_point, "view_height", d.view_height,
              "scale 1:%.3f" % (d.view_height / d.height), "status", d.status)
        if d.id > 1:
            x0, x1 = d.center.x - d.width / 2, d.center.x + d.width / 2
            y0, y1 = d.center.y - d.height / 2, d.center.y + d.height / 2
            print("  vp paper box", x0, y0, x1, y1)
            print("  inside inner frame:", x0 >= 25 and x1 <= 415 and y0 >= 5 and y1 <= 292)
            print("  clear of title block (y>45 or x<235):", y0 > 45 or x1 < 235)
            s = d.height / d.view_height
            ext = bbox.extents(doc.modelspace())
            vx0 = d.view_center_point.x - d.width / s / 2
            vx1 = d.view_center_point.x + d.width / s / 2
            vy0 = d.view_center_point.y - d.view_height / 2
            vy1 = d.view_center_point.y + d.view_height / 2
            print("  model window", (vx0, vy0), (vx1, vy1))
            print("  whole part+dims visible:", vx0 <= ext.extmin.x and vx1 >= ext.extmax.x
                  and vy0 <= ext.extmin.y and vy1 >= ext.extmax.y)
            # part (with dims) on paper
            px0 = d.center.x + (ext.extmin.x - d.view_center_point.x) * s
            px1 = d.center.x + (ext.extmax.x - d.view_center_point.x) * s
            py0 = d.center.y + (ext.extmin.y - d.view_center_point.y) * s
            py1 = d.center.y + (ext.extmax.y - d.view_center_point.y) * s
            print("  drawing on paper", (round(px0, 1), round(py0, 1)), (round(px1, 1), round(py1, 1)))
            print("  margins L/R/B/T to inner frame:", round(px0 - 25, 1), round(415 - px1, 1),
                  round(py0 - 5, 1), round(292 - py1, 1))
    else:
        print(t, e.dxf.layer)
