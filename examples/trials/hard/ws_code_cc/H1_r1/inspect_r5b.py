import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()
for e in msp:
    ext = bbox.extents([e])
    print(e.dxftype(), e.dxf.handle, e.dxf.layer, ext.extmin, ext.extmax)
mt = msp.query("MTEXT")[0]
print("mtext attach", mt.dxf.attachment_point, "width", mt.dxf.get("width"))
tb = msp.query("INSERT")[0]
for a in tb.attribs:
    print(a.dxf.tag, a.dxf.text, a.dxf.halign, a.dxf.valign, a.dxf.get("align_point"))
for be in doc.blocks.get("TB"):
    print("  TB:", be.dxftype(), be.dxf.layer, be.dxf.get("tag", ""), be.dxf.get("text", ""))
print("header $INSUNITS", doc.header.get("$INSUNITS"), doc.dxfversion)
