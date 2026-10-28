import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("version", doc.dxfversion, "INSUNITS", doc.header.get("$INSUNITS"))
print("layers", [l.dxf.name for l in doc.layers])
print("dimstyles", [s.dxf.name for s in doc.dimstyles])
for e in msp:
    d = e.dxf
    t = e.dxftype()
    s = f"{t} h={d.handle} layer={d.layer} color={d.get('color')} lt={d.get('linetype')}"
    if t == "CIRCLE":
        s += f" c={tuple(d.center)} r={d.radius}"
    elif t == "LINE":
        s += f" {tuple(d.start)} -> {tuple(d.end)}"
    elif t == "LWPOLYLINE":
        s += f" pts={list(e.get_points('xy'))} closed={e.closed}"
    elif t == "TEXT":
        s += f" {d.text!r} at {tuple(d.insert)} h={d.height}"
    elif t == "MTEXT":
        s += f" {e.text!r} at {tuple(d.insert)}"
    elif t == "DIMENSION":
        s += (f" type={d.dimtype} text={d.text!r} block={d.geometry} style={d.dimstyle}"
              f" defpt={tuple(d.defpoint)} defpt4={tuple(d.get('defpoint4', (0, 0, 0)))}"
              f" tm={tuple(d.text_midpoint)}")
        s += f" xdata={e.get_xdata('ACAD') if e.has_xdata('ACAD') else None}"
    elif t == "INSERT":
        s += f" {d.name} at {tuple(d.insert)}"
    print(s)
ds = doc.dimstyles.get("STANDARD") if doc.dimstyles.has_entry("STANDARD") else None
for st in doc.dimstyles:
    print("DIMSTYLE", st.dxf.name, {k: st.dxf.get(k) for k in ("dimtxt", "dimasz", "dimexe", "dimexo", "dimgap", "dimcen", "dimdec", "dimtad", "dimblk")})
for b in doc.blocks:
    if b.name.startswith("*D"):
        print("BLOCK", b.name)
        for x in b:
            t = x.dxftype()
            info = f"layer={x.dxf.layer} color={x.dxf.get('color')}"
            if t == "LINE":
                info += f" {tuple(x.dxf.start)} -> {tuple(x.dxf.end)}"
            elif t == "MTEXT":
                info += f" {x.text!r} at {tuple(x.dxf.insert)} h={x.dxf.char_height}"
            elif t == "INSERT":
                info += f" {x.dxf.name} at {tuple(x.dxf.insert)} rot={x.dxf.rotation}"
            elif t == "POINT":
                info += f" {tuple(x.dxf.location)}"
            print("   ", t, x.dxf.handle, info)
