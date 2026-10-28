import sys
import ezdxf
from ezdxf import bbox

fn = sys.argv[1] if len(sys.argv) > 1 else "part.dxf"
doc = ezdxf.readfile(fn)
msp = doc.modelspace()
for e in msp:
    d = e.dxf
    s = f"{e.dxftype():10s} h={d.handle} layer={d.layer}"
    t = e.dxftype()
    if t == "LINE":
        s += f" {tuple(d.start)[:2]}->{tuple(d.end)[:2]}"
    elif t == "CIRCLE":
        s += f" c={tuple(d.center)[:2]} r={d.radius}"
    elif t == "TEXT":
        s += f" ins={tuple(d.insert)[:2]} h={d.height} style={d.style} '{d.text}'"
    elif t == "MTEXT":
        s += f" ins={tuple(d.insert)[:2]} h={d.char_height} style={d.style} '{e.text}'"
    elif t == "LWPOLYLINE":
        s += f" pts={[tuple(p)[:2] for p in e.get_points('xy')]} closed={e.closed}"
    elif t == "DIMENSION":
        s += f" txt='{d.text}' meas={e.get_measurement()} blk={d.geometry} style={d.dimstyle}"
    elif t == "INSERT":
        s += f" name={d.name} ins={tuple(d.insert)[:2]} scale={d.xscale}"
        for a in e.attribs:
            s += f"\n    ATTRIB {a.dxf.tag}='{a.dxf.text}' h={a.dxf.handle} ins={tuple(a.dxf.insert)[:2]} ht={a.dxf.height} style={a.dxf.style}"
    print(s)
print("layers:", [l.dxf.name for l in doc.layers])
print("styles:", [(s.dxf.name, s.dxf.font) for s in doc.styles])
for e in msp:
    if e.dxftype() == "INSERT":
        print(e.dxf.name, "block bbox:", bbox.extents([e]))
print("msp bbox:", bbox.extents(msp))
