import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("layers:")
for l in doc.layers:
    print(" ", l.dxf.name, l.dxf.color, l.dxf.linetype, l.dxf.get('lineweight'),
          sum(1 for e in msp if e.dxf.layer == l.dxf.name))
print("linetypes:", [lt.dxf.name for lt in doc.linetypes])
print("insunits", doc.header.get('$INSUNITS'))
for e in msp:
    d = e.dxf
    t = e.dxftype()
    s = f"{t:10s} h={d.handle} L={d.layer} c={d.get('color')} lt={d.get('linetype')} lw={d.get('lineweight')}"
    if t == 'LINE':
        s += f" {tuple(d.start)}->{tuple(d.end)}"
    elif t == 'CIRCLE':
        s += f" c={tuple(d.center)} r={d.radius}"
    elif t == 'ARC':
        s += f" c={tuple(d.center)} r={d.radius} {d.start_angle}-{d.end_angle}"
    elif t == 'LWPOLYLINE':
        s += f" closed={e.closed} pts={list(e.get_points())}"
    elif t == 'TEXT':
        s += f" '{d.text}' at {tuple(d.insert)} h={d.height}"
    elif t == 'MTEXT':
        s += f" '{e.text}' at {tuple(d.insert)}"
    elif t == 'DIMENSION':
        s += (f" type={d.dimtype} meas={e.get_measurement()} text='{d.get('text')}' "
              f"blk={d.get('geometry')} style={d.dimstyle} p1={d.get('defpoint')} p2={d.get('defpoint2')} p3={d.get('defpoint3')} p4={d.get('defpoint4')}")
    elif t == 'INSERT':
        s += f" name={d.name}"
    print(s)
print("blocks:", [b.name for b in doc.blocks])
for b in doc.blocks:
    if b.name.startswith('*D'):
        print(b.name, [(x.dxftype(), x.dxf.layer, x.dxf.get('color')) for x in b])
