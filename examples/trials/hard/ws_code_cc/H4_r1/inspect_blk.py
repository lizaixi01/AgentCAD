import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
for b in doc.blocks:
    if b.name.startswith("*D") or not b.name.startswith("*"):
        for e in b:
            print(b.name, e.dxftype(), e.dxf.layer, e.dxf.get("color"), e.dxf.get("linetype"), e.dxf.get("lineweight"))
for e in doc.modelspace():
    if e.dxftype() == "DIMENSION":
        print(e.dxf.handle, "override:", e.dim_style_attributes().dxfattribs() if e.has_xdata("ACAD") else None)
    if e.dxftype() == "MTEXT":
        print(repr(e.text))
# who references layers anywhere (incl. objects)
used = {}
for e in doc.entitydb.values():
    if e.dxf.hasattr("layer"):
        used.setdefault(e.dxf.layer, []).append(e.dxftype())
for k, v in used.items():
    print("layer use", k, sorted(set(v)), len(v))
