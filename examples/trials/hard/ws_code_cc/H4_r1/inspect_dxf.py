import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
print("units", doc.header.get("$INSUNITS"), doc.dxfversion)
for l in doc.layers:
    print("LAYER", l.dxf.name, l.dxf.color, l.dxf.linetype, l.dxf.get("lineweight"))
print("LT", [lt.dxf.name for lt in doc.linetypes])
print("DIMSTYLES", [d.dxf.name for d in doc.dimstyles])
print("BLOCKS", [b.name for b in doc.blocks])
for lay in doc.layouts:
    print("LAYOUT", lay.name, len(lay))
msp = doc.modelspace()
for e in msp:
    d = e.dxf
    t = e.dxftype()
    info = f"{d.handle} {t} L={d.layer} c={d.get('color')} lt={d.get('linetype')} lw={d.get('lineweight')}"
    if t == "LINE":
        info += f" {tuple(d.start)}->{tuple(d.end)}"
    elif t in ("CIRCLE", "ARC"):
        info += f" c={tuple(d.center)} r={d.radius}" + (f" a={d.start_angle},{d.end_angle}" if t == "ARC" else "")
    elif t == "LWPOLYLINE":
        info += f" closed={e.closed} pts={list(e.get_points('xyb'))}"
    elif t == "TEXT":
        info += f" '{d.text}' ins={tuple(d.insert)} h={d.height}"
    elif t == "MTEXT":
        info += f" '{e.text}' ins={tuple(d.insert)} h={d.char_height}"
    elif t == "DIMENSION":
        info += f" type={d.dimtype} m={e.get_measurement()} txt='{d.get('text')}' blk={d.get('geometry')} style={d.get('dimstyle')} p={tuple(d.defpoint)}"
    elif t == "INSERT":
        info += f" {d.name}"
    print(info)
