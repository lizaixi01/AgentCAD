import sys
import ezdxf
from ezdxf import bbox

sys.stdout.reconfigure(encoding="utf-8")

doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
print("dxfversion", doc.dxfversion, "codepage", doc.header.get("$DWGCODEPAGE"),
      "INSUNITS", doc.header.get("$INSUNITS"))
st = doc.styles.get("Standard")
print("Standard font", st.dxf.font, "bigfont", st.dxf.get("bigfont"), "width", st.dxf.width)
for e in msp:
    bb = bbox.extents([e], fast=False)
    s = f"{e.dxftype():10s} h={e.dxf.handle:4s} layer={e.dxf.layer:8s}"
    if bb.has_data:
        s += f" x[{bb.extmin.x:.2f},{bb.extmax.x:.2f}] y[{bb.extmin.y:.2f},{bb.extmax.y:.2f}]"
    if e.dxftype() == "MTEXT":
        s += f" text={e.text!r} attach={e.dxf.attachment_point} width={e.dxf.get('width')} color={e.dxf.get('color')}"
    if e.dxftype() == "TEXT":
        s += f" color={e.dxf.get('color')} halign={e.dxf.halign}"
    print(s)
tb = doc.blocks["TB"]
for x in tb:
    s = x.dxftype()
    if x.dxftype() == "LWPOLYLINE":
        s += str([tuple(p[:2]) for p in x.get_points()])
    elif x.dxftype() == "LINE":
        s += f" {tuple(x.dxf.start)}->{tuple(x.dxf.end)}"
    elif x.dxftype() in ("TEXT", "ATTDEF"):
        s += f" {x.dxf.text!r} {tuple(x.dxf.insert)} h={x.dxf.height}"
    print("  TB", s)
for l in doc.layers:
    print("LAYER", l.dxf.name, l.dxf.color)
