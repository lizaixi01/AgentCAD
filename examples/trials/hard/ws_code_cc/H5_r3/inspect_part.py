import ezdxf
doc = ezdxf.readfile("part.dxf")
print(doc.dxfversion, doc.header.get("$INSUNITS"))
for l in doc.layers: print("layer", l.dxf.name)
for s in doc.dimstyles: print("dimstyle", s.dxf.name, s.dxf.dimtxt, s.dxf.dimasz)
msp = doc.modelspace()
for e in msp:
    d = e.dxfattribs()
    if e.dxftype() == "LWPOLYLINE":
        d["pts"] = list(e.get_points())
    print(e.dxftype(), d)
