import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
print("units", doc.header.get("$INSUNITS"), "dimstyles", [d.dxf.name for d in doc.dimstyles])
print("layers", [(l.dxf.name, l.dxf.color) for l in doc.layers])
for e in doc.modelspace():
    t = e.dxftype()
    d = {"layer": e.dxf.layer, "handle": e.dxf.handle}
    if t == "LINE":
        d.update(s=tuple(e.dxf.start), e=tuple(e.dxf.end))
    elif t == "CIRCLE":
        d.update(c=tuple(e.dxf.center), r=e.dxf.radius)
    elif t == "ARC":
        d.update(c=tuple(e.dxf.center), r=e.dxf.radius, a=(e.dxf.start_angle, e.dxf.end_angle))
    elif t == "LWPOLYLINE":
        d.update(pts=list(e.get_points()), closed=e.closed)
    elif t == "TEXT":
        d.update(txt=e.dxf.text, ins=tuple(e.dxf.insert), h=e.dxf.height)
    elif t == "MTEXT":
        d.update(txt=e.text, ins=tuple(e.dxf.insert), h=e.dxf.char_height)
    elif t == "DIMENSION":
        d.update(m=e.get_measurement(), txt=e.dxf.text, dimtype=e.dimtype, style=e.dxf.dimstyle)
    print(t, d)
