import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("layers:", [(l.dxf.name, l.dxf.color) for l in doc.layers])
print("dimstyles:", [d.dxf.name for d in doc.dimstyles])
print("blocks:", [b.name for b in doc.blocks])
for e in msp:
    t = e.dxftype()
    d = dict(layer=e.dxf.layer)
    if t == "LINE":
        d.update(s=tuple(e.dxf.start), e=tuple(e.dxf.end))
    elif t == "CIRCLE":
        d.update(c=tuple(e.dxf.center), r=e.dxf.radius)
    elif t == "LWPOLYLINE":
        d.update(pts=[tuple(p)[:2] for p in e.get_points()], closed=e.closed)
    elif t == "TEXT":
        d.update(text=e.dxf.text, ins=tuple(e.dxf.insert), h=e.dxf.height)
    elif t == "MTEXT":
        d.update(text=e.text, ins=tuple(e.dxf.insert))
    elif t == "DIMENSION":
        d.update(type=e.dimtype, text=e.dxf.text, style=e.dxf.dimstyle,
                 defp=tuple(e.dxf.defpoint), defp4=tuple(e.dxf.defpoint4),
                 tm=tuple(e.dxf.text_midpoint), meas=e.get_measurement(),
                 block=e.dxf.geometry)
    elif t == "INSERT":
        d.update(name=e.dxf.name, ins=tuple(e.dxf.insert))
    print(t, e.dxf.handle, d)
