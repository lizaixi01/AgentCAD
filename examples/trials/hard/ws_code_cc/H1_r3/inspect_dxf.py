import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("units", doc.header.get('$INSUNITS'))
for e in msp:
    t = e.dxftype()
    d = e.dxf
    s = f"{t} h={d.handle} layer={d.layer}"
    if t == 'LINE':
        s += f" {tuple(d.start)[:2]}->{tuple(d.end)[:2]}"
    elif t == 'CIRCLE':
        s += f" c={tuple(d.center)[:2]} r={d.radius}"
    elif t == 'ARC':
        s += f" c={tuple(d.center)[:2]} r={d.radius} {d.start_angle}-{d.end_angle}"
    elif t == 'LWPOLYLINE':
        s += f" pts={list(e.get_points('xyb'))} closed={e.closed}"
    elif t == 'TEXT':
        s += f" ins={tuple(d.insert)[:2]} txt={d.text!r}"
    elif t == 'MTEXT':
        s += f" ins={tuple(d.insert)[:2]} txt={e.text!r}"
    elif t == 'DIMENSION':
        s += (f" type={d.dimtype} p2={tuple(d.defpoint2)[:2] if d.hasattr('defpoint2') else None}"
              f" p3={tuple(d.defpoint3)[:2] if d.hasattr('defpoint3') else None}"
              f" base={tuple(d.defpoint)[:2]} text={d.get('text')!r} meas={e.get_measurement()}"
              f" angle={d.get('angle')} block={d.get('geometry')} style={d.get('dimstyle')}")
    elif t == 'INSERT':
        s += f" name={d.name} ins={tuple(d.insert)[:2]}"
    print(s)
print([b.name for b in doc.blocks])
