import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1] if len(sys.argv) > 1 else "part.dxf")
print(doc.dxfversion, doc.header.get('$INSUNITS'))
print("layers", [(l.dxf.name, l.dxf.color, l.dxf.linetype) for l in doc.layers])
print("dimstyles", [d.dxf.name for d in doc.dimstyles])
msp = doc.modelspace()
for e in msp:
    d = e.dxf
    t = e.dxftype()
    s = f"{t} L={d.layer} h={d.handle} col={d.get('color')}"
    if t == "LINE":
        s += f" {tuple(d.start)[:2]}->{tuple(d.end)[:2]} lt={d.get('linetype')}"
    elif t == "CIRCLE":
        s += f" c={tuple(d.center)[:2]} r={d.radius}"
    elif t == "ARC":
        s += f" c={tuple(d.center)[:2]} r={d.radius} {d.start_angle}-{d.end_angle}"
    elif t == "TEXT":
        s += f" {tuple(d.insert)[:2]} h={d.height} {d.text!r}"
    elif t == "MTEXT":
        s += f" {tuple(d.insert)[:2]} h={d.char_height} {e.plain_text()!r}"
    elif t == "LWPOLYLINE":
        s += f" {list(e.get_points('xyb'))} closed={e.closed}"
    elif t == "DIMENSION":
        s += (f" type={d.dimtype} style={d.dimstyle} text={d.get('text')!r} "
              f"defpt={tuple(d.defpoint)[:2]} defpt2={tuple(d.get('defpoint2',(0,0,0)))[:2]} "
              f"defpt3={tuple(d.get('defpoint3',(0,0,0)))[:2]} defpt4={tuple(d.get('defpoint4',(0,0,0)))[:2]} "
              f"textpt={tuple(d.get('text_midpoint',(0,0,0)))[:2]} "
              f"meas={d.get('actual_measurement')} blk={d.get('geometry')}")
    elif t == "INSERT":
        s += f" {d.name} {tuple(d.insert)[:2]}"
    print(s)
for b in doc.blocks:
    if not b.name.startswith('*'):
        print("block", b.name, len(b))
