import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("units:", doc.header.get('$INSUNITS'))
print("layers:", [(l.dxf.name, l.dxf.color, l.dxf.linetype, l.dxf.get('lineweight')) for l in doc.layers])
print("linetypes:", [lt.dxf.name for lt in doc.linetypes])
print("blocks:", [b.name for b in doc.blocks])
for lay in doc.layouts:
    print("layout", lay.name, len(lay))
for e in msp:
    d = e.dxf
    info = f"{d.handle} {e.dxftype()} layer={d.layer} color={d.get('color')} lt={d.get('linetype')} lw={d.get('lineweight')} tc={d.get('true_color')}"
    t = e.dxftype()
    if t == 'LINE':
        info += f" {tuple(d.start)} -> {tuple(d.end)}"
    elif t in ('CIRCLE', 'ARC'):
        info += f" c={tuple(d.center)} r={d.radius}" + (f" a={d.start_angle},{d.end_angle}" if t == 'ARC' else '')
    elif t == 'LWPOLYLINE':
        info += f" pts={list(e.get_points())} closed={e.closed}"
    elif t == 'TEXT':
        info += f" text={d.text!r} ins={tuple(d.insert)} h={d.height}"
    elif t == 'MTEXT':
        info += f" text={e.text!r} ins={tuple(d.insert)} h={d.char_height}"
    elif t == 'DIMENSION':
        info += f" type={d.dimtype} block={d.get('geometry')} meas={e.get_measurement()} text={d.get('text')!r} dimstyle={d.dimstyle} defpt={tuple(d.defpoint)} d2={d.get('defpoint2')} d3={d.get('defpoint3')}"
    print(info)
