import ezdxf
doc = ezdxf.readfile("part.dxf")
print(doc.dxfversion, doc.header.get("$INSUNITS"), doc.header.get("$DIMSTYLE"))
for l in doc.layers: print("layer", l.dxf.name, l.dxf.color)
for s in doc.dimstyles: print("dimstyle", s.dxf.name, s.dxf.get("dimtxt"), s.dxf.get("dimasz"))
msp = doc.modelspace()
for e in msp:
    t = e.dxftype()
    d = {}
    if t == "LINE": d = (tuple(e.dxf.start), tuple(e.dxf.end))
    elif t == "CIRCLE": d = (tuple(e.dxf.center), e.dxf.radius)
    elif t == "ARC": d = (tuple(e.dxf.center), e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
    elif t == "LWPOLYLINE": d = (list(e.get_points()), e.closed)
    elif t == "TEXT": d = (tuple(e.dxf.insert), e.dxf.text, e.dxf.height)
    elif t == "MTEXT": d = (tuple(e.dxf.insert), e.text, e.dxf.char_height)
    elif t == "DIMENSION": d = (e.dxf.dimtype, e.dxf.get("text"))
    print(t, e.dxf.layer, d)
