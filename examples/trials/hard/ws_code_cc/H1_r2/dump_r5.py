import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("styles:", [s.dxf.name for s in doc.styles], "font of Standard:",
      [(s.dxf.name, s.dxf.font) for s in doc.styles])
for e in msp:
    info = f"{e.dxftype():12s} h={e.dxf.handle} layer={e.dxf.layer}"
    t = e.dxftype()
    if t in ("TEXT", "MTEXT"):
        txt = e.dxf.text if t == "TEXT" else e.text
        h = e.dxf.height if t == "TEXT" else e.dxf.char_height
        info += f" ins={tuple(e.dxf.insert)} h={h} style={e.dxf.style} text={txt!r}"
    elif t == "INSERT":
        info += f" name={e.dxf.name} ins={tuple(e.dxf.insert)} scale=({e.dxf.xscale},{e.dxf.yscale})"
        for a in e.attribs:
            info += f"\n    ATTRIB h={a.dxf.handle} tag={a.dxf.tag} text={a.dxf.text!r} ins={tuple(a.dxf.insert)} height={a.dxf.height}"
    elif t == "CIRCLE":
        info += f" c={tuple(e.dxf.center)} r={e.dxf.radius}"
    elif t == "LWPOLYLINE":
        info += f" pts={[tuple(p[:2]) for p in e.get_points()]}"
    elif t == "LINE":
        info += f" {tuple(e.dxf.start)}->{tuple(e.dxf.end)}"
    print(info)
    try:
        bb = ezdxf.bbox.extents([e])
        if bb.has_data:
            print(f"    bbox {bb.extmin} {bb.extmax}")
    except Exception as ex:
        print("    bbox err", ex)
for b in doc.blocks:
    if not b.name.startswith("*"):
        print("BLOCK", b.name, [(x.dxftype(), x.dxf.handle) for x in b])
        for x in b:
            if x.dxftype() == "ATTDEF":
                print("   ATTDEF", x.dxf.tag, repr(x.dxf.text), tuple(x.dxf.insert))
