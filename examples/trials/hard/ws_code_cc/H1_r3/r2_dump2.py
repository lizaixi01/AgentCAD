import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("NOTES:", repr(doc.entitydb["E0"].text))
for a in doc.entitydb["ED"].attribs:
    print("ATTRIB", a.dxf.tag, repr(a.dxf.text))
for e in doc.blocks.get("TB"):
    print("TB", e.dxftype(), getattr(e.dxf, "text", ""))
d = doc.entitydb["D2"]
print("D2 block mtext:", repr([m.text for m in doc.blocks.get(d.dxf.geometry).query("MTEXT")]))
print("D2 overrides:", d.get_dim_style() if hasattr(d, "get_dim_style") else None)
xd = d.get_xdata("ACAD") if d.has_xdata("ACAD") else None
print("D2 xdata:", xd)
print(open("modify_r1.py", encoding="utf-8").read())
