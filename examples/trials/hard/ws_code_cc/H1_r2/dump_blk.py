import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
for name in sys.argv[2:]:
    print("BLOCK", name)
    for x in doc.blocks[name]:
        t = x.dxftype()
        s = f"  {t} h={x.dxf.handle} layer={x.dxf.layer} color={x.dxf.get('color')}"
        if t == "LINE":
            s += f" {tuple(x.dxf.start)} -> {tuple(x.dxf.end)}"
        elif t == "INSERT":
            s += f" {x.dxf.name} at {tuple(x.dxf.insert)} rot={x.dxf.rotation} scale={x.dxf.xscale}"
        elif t == "POINT":
            s += f" {tuple(x.dxf.location)}"
        elif t == "MTEXT":
            s += f" {x.text!r} attach={x.dxf.attachment_point}"
        print(s)
for h in sys.argv[1:2]:
    pass
dim = [d for d in doc.modelspace().query("DIMENSION") if d.dxf.geometry == sys.argv[-1]]
if dim:
    print("xdata", dim[0].get_xdata("ACAD") if dim[0].has_xdata("ACAD") else None)
