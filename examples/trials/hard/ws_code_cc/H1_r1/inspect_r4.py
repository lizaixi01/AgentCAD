import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
for e in msp:
    t = e.dxftype()
    d = e.dxf
    s = f"{t} h={d.handle} layer={d.layer}"
    if t == "CIRCLE":
        s += f" c={tuple(d.center)} r={d.radius}"
    elif t == "LINE":
        s += f" {tuple(d.start)}->{tuple(d.end)}"
    elif t == "TEXT":
        s += f" {d.text!r} at {tuple(d.insert)}"
    elif t == "MTEXT":
        s += f" {e.plain_text()!r} at {tuple(d.insert)}"
    elif t == "DIMENSION":
        s += (f" text={d.get('text')!r} meas={e.get_measurement()} style={d.dimstyle}"
              f" block={d.geometry} dp={tuple(d.defpoint)} tmid={tuple(d.get('text_midpoint', (0, 0, 0)))}"
              f" dimtype={d.dimtype}")
        if d.hasattr("defpoint4"):
            s += f" dp4={tuple(d.defpoint4)}"
        if d.hasattr("defpoint2"):
            s += f" dp2={tuple(d.defpoint2)} dp3={tuple(d.defpoint3)}"
    elif t == "INSERT":
        s += f" {d.name} " + str([(a.dxf.tag, a.dxf.text) for a in e.attribs])
    elif t == "LWPOLYLINE":
        s += f" {list(e.get_points('xy'))}"
    print(s)
print("INSUNITS", doc.header.get("$INSUNITS"))
for b in doc.blocks:
    if not b.name.startswith("*"):
        print("BLOCK", b.name, [x.dxftype() for x in b])
for k in doc.header.varnames():
    if "CUSTOM" in k.upper():
        print(k)
print("XDATA/appids", [a.dxf.name for a in doc.appids])
