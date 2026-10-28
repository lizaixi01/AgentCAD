import ezdxf

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()
for e in doc.blocks.get("TB"):
    print("TB:", e.dxftype(), e.dxf.layer, e.dxf.text if e.dxftype() in ("TEXT", "ATTDEF") else "",
          e.dxf.tag if e.dxftype() == "ATTDEF" else "",
          [tuple(v)[:2] for v in e.get_points()] if e.dxftype() == "LWPOLYLINE" else "")
ins = msp.query("INSERT")[0]
for a in ins.attribs:
    print("ATTRIB", a.dxf.tag, a.dxf.text)
d = doc.entitydb["D2"]
print("D2 overrides:", d.get_dim_style().__class__, d.dimstyle_overrides if hasattr(d, 'dimstyle_overrides') else None)
print(d.get_xdata("ACAD") if d.has_xdata("ACAD") else "no xdata")
print(dict(d.dxf.all_existing_dxf_attribs()))
blk = doc.blocks.get("*D1")
for e in blk:
    print(" *D1", e.dxftype(), e.dxf.layer, e.dxf.get("text", ""), e.dxf.get("color"))
st = doc.dimstyles.get("EZDXF")
print({k: st.dxf.get(k) for k in ("dimtxt", "dimasz", "dimblk", "dimdec", "dimtad", "dimclrd", "dimclrt", "dimexo", "dimgap", "dimcen", "dimtix", "dimtofl")})
