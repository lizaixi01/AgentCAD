import ezdxf
from ezdxf import bbox
from collections import Counter

doc = ezdxf.readfile("part.dxf")
print(doc.dxfversion, doc.units, doc.header.get("$INSUNITS"))
print("layouts", doc.layouts.names())
msp = doc.modelspace()
print(Counter(e.dxftype() for e in msp))
for e in msp:
    if e.dxftype() == "DIMENSION":
        print("DIM", e.dxf.dimtype, round(e.get_measurement(), 3) if not hasattr(e.get_measurement(), "x") else e.get_measurement(),
              e.dxf.get("text"), e.dxf.layer, e.dxf.dimstyle, e.dxf.get("geometry"))
    else:
        print(e.dxftype(), e.dxf.layer)
ext = bbox.extents(msp)
print("ext", ext.extmin, ext.extmax)
print("layers", [l.dxf.name for l in doc.layers])
for n in doc.dimstyles:
    print("dimstyle", n.dxf.name, n.dxf.get("dimscale"), n.dxf.get("dimtxt"))
for lay in doc.layouts:
    print("layout", lay.name, len(lay), lay.dxf.get("taborder"))
