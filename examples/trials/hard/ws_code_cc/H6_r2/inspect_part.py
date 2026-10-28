import ezdxf
from collections import Counter
from ezdxf import bbox

doc = ezdxf.readfile("part.dxf")
print(doc.dxfversion, doc.header.get("$INSUNITS"))
msp = doc.modelspace()
print(Counter(e.dxftype() for e in msp))
print("layouts", doc.layouts.names())
for e in msp:
    if e.dxftype() == "DIMENSION":
        print(e.dxf.layer, e.dxf.dimtype, e.dxf.get("defpoint"), e.dxf.get("text_midpoint"),
              e.get_measurement(), e.dxf.get("geometry"))
ext = bbox.extents(msp)
print("extents", ext.extmin, ext.extmax)
ext2 = bbox.extents([e for e in msp if e.dxftype() != "DIMENSION"])
print("geom extents", ext2.extmin, ext2.extmax)
print([l.dxf.name for l in doc.layers])
