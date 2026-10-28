import ezdxf

doc = ezdxf.readfile("part.dxf")
print(ascii([t.dxf.text for t in doc.modelspace().query("TEXT")]))
for d in doc.modelspace().query("DIMENSION"):
    if d.dimtype == 3:
        print("override text:", ascii(d.dxf.text), "style:", d.dxf.dimstyle)
        for e in d.get_geometry_block():
            if e.dxftype() == "LINE":
                print("  LINE", e.dxf.start.round(2), e.dxf.end.round(2))
            elif e.dxftype() == "MTEXT":
                print("  MTEXT", ascii(e.text), e.dxf.insert.round(2))
            else:
                print(" ", e.dxftype())
print("audit errors:", len(doc.audit().errors))
