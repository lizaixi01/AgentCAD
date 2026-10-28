import ezdxf
from ezdxf import bbox

doc = ezdxf.readfile("part.dxf")
print(doc.dxfversion, doc.header.get("$INSUNITS"))
msp = doc.modelspace()
for e in msp:
    print(e.dxftype(), e.dxf.layer, end=" ")
    if e.dxftype() == "DIMENSION":
        print(e.dxf.dimtype, e.get_measurement(), e.dxf.get("text"), e.dxf.dimstyle, e.dxf.get("geometry"))
    elif e.dxftype() == "LINE":
        print(e.dxf.start, e.dxf.end)
    elif e.dxftype() == "CIRCLE":
        print(e.dxf.center, e.dxf.radius)
    else:
        print()
print("bbox", bbox.extents(msp))
print([l.name for l in doc.layouts])
for ds in doc.dimstyles:
    print(ds.dxf.name, ds.dxf.get("dimscale"), ds.dxf.get("dimtxt"))
for l in doc.layers:
    print("layer", l.dxf.name, l.dxf.color)
