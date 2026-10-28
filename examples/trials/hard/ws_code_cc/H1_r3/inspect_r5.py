import ezdxf, sys
from ezdxf import bbox
doc = ezdxf.readfile(sys.argv[1])
sys.stdout.reconfigure(encoding="utf-8")
msp = doc.modelspace()
print("ver", doc.dxfversion, "units", doc.header.get("$INSUNITS"), "codepage", doc.header.get("$DWGCODEPAGE"))
for e in msp:
    t = e.dxftype(); d = e.dxf
    info = ""
    if t == "LINE": info = f"{d.start} {d.end}"
    elif t == "CIRCLE": info = f"c={d.center} r={d.radius}"
    elif t == "LWPOLYLINE": info = f"{[tuple(map(float, p)) for p in e.get_points('xy')]} closed={e.closed}"
    elif t == "TEXT": info = f"{d.text!r} ins={d.insert} h={d.height} style={d.style} halign={d.halign} align={d.get('align_point')}"
    elif t == "MTEXT": info = f"{e.text!r} ins={d.insert} h={d.char_height} style={d.style} attach={d.attachment_point} w={d.get('width')}"
    elif t == "INSERT": info = f"{d.name} ins={d.insert} scale={d.xscale} " + str([(a.dxf.tag, a.dxf.text, a.dxf.handle, a.dxf.insert, a.dxf.height) for a in e.attribs])
    elif t == "DIMENSION": info = f"{d.dimtype} meas={e.get_measurement()} text={d.get('text')!r} blk={d.geometry}"
    ext = bbox.extents([e])
    print(t, d.layer, d.handle, info, "| bbox", ext.extmin if ext.has_data else None, ext.extmax if ext.has_data else None)
for b in doc.blocks:
    if not b.name.startswith("*"):
        print("BLOCK", b.name)
        for e in b:
            print("   ", e.dxftype(), e.dxf.layer, e.dxf.get("insert") if e.dxf.is_supported("insert") else "", e.dxf.get("tag") if e.dxf.is_supported("tag") else "", e.dxf.get("text") if e.dxf.is_supported("text") else "")
print("styles", [(s.dxf.name, s.dxf.font) for s in doc.styles])
print("layers", [l.dxf.name for l in doc.layers])
