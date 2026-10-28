import ezdxf
from ezdxf import bbox

old = ezdxf.readfile("part_orig.dxf")
new = ezdxf.readfile("part.dxf")
print("audit errors:", len(new.audit().errors))

STD = {"OUTLINE": (7, "CENTER_X", 50), "CENTER": (1, "CENTER", 25), "DIM": (3, "", 25), "TEXT": (4, "", 25)}
for l in new.layers:
    print("LAYER", l.dxf.name, l.dxf.color, l.dxf.linetype, l.dxf.lineweight)

ok = True
for e in new.modelspace():
    d = e.dxf
    byl = d.get("color", 256) == 256 and d.get("linetype", "BYLAYER").upper() == "BYLAYER" and d.get("lineweight", -1) == -1
    if not byl:
        ok = False
        print("NOT BYLAYER", d.handle)
    print(d.handle, e.dxftype(), d.layer)
print("all ByLayer:", ok)


def sig(doc):
    out = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "LINE":
            out.append((t, tuple(sorted([tuple(e.dxf.start), tuple(e.dxf.end)]))))
        elif t == "CIRCLE":
            out.append((t, tuple(e.dxf.center), e.dxf.radius))
        elif t == "LWPOLYLINE":
            out.append((t, tuple(map(tuple, e.get_points("xyb")))))
        elif t == "TEXT":
            out.append((t, e.dxf.text, tuple(e.dxf.insert), e.dxf.height))
        elif t == "MTEXT":
            out.append((t, e.text, tuple(e.dxf.insert), e.dxf.char_height))
        elif t == "DIMENSION":
            out.append((t, e.dxf.dimtype, round(e.get_measurement(), 9), e.dxf.text, tuple(e.dxf.defpoint)))
    return out


so, sn = sig(old), sig(new)
print("removed signatures:", [s for s in so if s not in sn or so.count(s) > sn.count(s)])
print("added signatures:", [s for s in sn if s not in so])
bo, bn = bbox.extents(old.modelspace()), bbox.extents(new.modelspace())
print("bbox old:", bo.extmin, bo.extmax, "new:", bn.extmin, bn.extmax)
print("circles new:", len(new.modelspace().query("CIRCLE")), "old:", len(old.modelspace().query("CIRCLE")))
for e in new.modelspace().query("DIMENSION"):
    print("dim", e.dxf.handle, e.get_measurement(), [be.dxf.color for be in new.blocks.get(e.dxf.geometry)])
print("LTSCALE", new.header["$LTSCALE"])
