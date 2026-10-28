import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
print("version", doc.dxfversion, "units", doc.header.get("$INSUNITS"))
for l in doc.layers:
    print("layer", l.dxf.name, l.dxf.color, l.dxf.linetype)
for ds in doc.dimstyles:
    print("dimstyle", ds.dxf.name)
msp = doc.modelspace()


def r(p):
    return tuple(round(v, 3) for v in p)


for e in msp:
    t = e.dxftype()
    d = e.dxf
    s = f"{t} layer={d.layer} h={d.handle} color={d.get('color')} lt={d.get('linetype')}"
    if t == "CIRCLE":
        s += f" c={r(d.center)} r={d.radius}"
    elif t == "LINE":
        s += f" {r(d.start)} -> {r(d.end)}"
    elif t == "ARC":
        s += f" c={r(d.center)} r={d.radius} a={d.start_angle}-{d.end_angle}"
    elif t == "TEXT":
        s += f" text={d.text!r} ins={r(d.insert)} h={d.height}"
    elif t == "MTEXT":
        s += f" text={e.text!r} ins={r(d.insert)}"
    elif t == "DIMENSION":
        s += (f" dimtype={d.dimtype} style={d.get('dimstyle')} text={d.get('text')!r}"
              f" meas={e.get_measurement()} blk={d.get('geometry')}")
        for k in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint", "angle"):
            if d.hasattr(k):
                v = d.get(k)
                s += f" {k}={r(v) if hasattr(v, '__iter__') else v}"
        s += f" overrides={e.dim_style_attributes().as_dict() if False else ''}"
    elif t == "LWPOLYLINE":
        s += f" pts={[r(p) for p in e.get_points('xy')]} closed={e.closed}"
    elif t == "INSERT":
        s += f" name={d.name} ins={r(d.insert)}"
    elif t == "LEADER" or t == "MULTILEADER":
        s += f" vertices={[r(v) for v in getattr(e, 'vertices', [])]}"
    print(s)
    if t == "DIMENSION":
        blk = doc.blocks.get(d.get("geometry"))
        if blk:
            for be in blk:
                extra = ""
                if be.dxftype() in ("TEXT", "MTEXT"):
                    extra = repr(be.dxf.text)
                print("    blk:", be.dxftype(), extra)
