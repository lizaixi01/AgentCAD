import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
for b in doc.blocks:
    print("BLOCK", b.name, b.block_record_handle)
    for e in b:
        t = e.dxftype()
        s = f"   {t} h={e.dxf.handle} layer={e.dxf.layer}"
        if t == "MTEXT":
            s += f" {e.text!r} at {tuple(e.dxf.insert)}"
        elif t in ("TEXT", "ATTDEF"):
            s += f" {e.dxf.text!r}"
        elif t == "LINE":
            s += f" {tuple(e.dxf.start)[:2]}->{tuple(e.dxf.end)[:2]}"
        print(s)
for e in doc.modelspace():
    if e.dxftype() == "DIMENSION":
        print(e.dxf.handle, "xdata:", {a: e.get_xdata(a) for a in ("ACAD", "EZDXF") if e.has_xdata(a)})
for e in doc.objects:
    print("OBJ", e.dxftype(), e.dxf.handle, getattr(e.dxf, "name", ""))
print("HANDSEED", doc.header.get("$HANDSEED"))
