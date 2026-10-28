import ezdxf
from ezdxf import bbox

old = ezdxf.readfile("part_before_r5.bak")
new = ezdxf.readfile("part.dxf")
om, nm = old.modelspace(), new.modelspace()


def snapshot(e):
    d = dict(e.dxf.all_existing_dxf_attribs())
    if e.dxftype() == "INSERT":
        d["attribs"] = {a.dxf.tag: a.dxf.text for a in e.attribs}
    if e.dxftype() == "LWPOLYLINE":
        d["pts"] = list(e.get_points())
    return d


oh = {e.dxf.handle: e for e in om}
nh = {e.dxf.handle: e for e in nm}
print("removed:", set(oh) - set(nh))
print("added:", set(nh) - set(oh))
for h in oh:
    if h in nh:
        a, b = snapshot(oh[h]), snapshot(nh[h])
        if a != b:
            print("changed", h, {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)})

tb = [e for e in nm.query("INSERT") if e.dxf.name == "TB"][0]
print("TB attribs:", {a.dxf.tag: a.dxf.text for a in tb.attribs})

t = nh["157"]
print("new text:", repr(t.dxf.text), t.dxf.layer, t.dxf.style, t.dxf.height, tuple(t.dxf.insert))
tb_ext = bbox.extents([t])
print("new text bbox:", tb_ext.extmin, tb_ext.extmax)
for e in nm:
    if e.dxf.handle == "157":
        continue
    ext = bbox.extents([e])
    if ext.has_data and ext.has_intersection(tb_ext):
        print("  OVERLAP with", e.dxftype(), e.dxf.handle, ext.extmin, ext.extmax)
print("blocks equal count:", len(old.blocks), len(new.blocks))
print("audit errors:", len(new.audit().errors))
