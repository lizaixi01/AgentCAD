import ezdxf


def snapshot(doc):
    out = {}
    for e in doc.modelspace():
        out[e.dxf.handle] = (e.dxftype(), str(sorted(
            (k, str(v)) for k, v in e.dxf.all_existing_dxf_attribs().items())))
    return out


old = ezdxf.readfile("part_before_r3.bak")
new = ezdxf.readfile("part.dxf")
so, sn = snapshot(old), snapshot(new)
print("removed:", [h for h in so if h not in sn])
print("changed:", [h for h in so if h in sn and so[h] != sn[h]])
added = [h for h in sn if h not in so]
print("added:", added)
for h in added:
    e = new.entitydb[h]
    print(" ", e.dxftype(), e.dxf.layer, {k: v for k, v in e.dxf.all_existing_dxf_attribs().items()
                                         if k in ("center", "radius", "defpoint", "defpoint4", "text_midpoint", "dimstyle", "geometry", "text")})
    if e.dxftype() == "DIMENSION":
        print("  measurement:", e.get_measurement())
        for be in e.get_geometry_block():
            if be.dxftype() == "MTEXT":
                print("  rendered text:", be.plain_text(), be.dxf.insert)
ins = new.modelspace().query("INSERT")[0]
print("attribs:", [(a.dxf.tag, a.dxf.text) for a in ins.attribs])
print("audit errors:", len(new.audit().errors))
