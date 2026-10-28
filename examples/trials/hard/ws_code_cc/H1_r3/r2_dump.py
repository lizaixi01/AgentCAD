import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
for e in doc.modelspace():
    d = e.dxfattribs()
    d.pop("owner", None)
    print(e.dxftype(), d)
    if e.dxftype() == "LWPOLYLINE":
        print("  pts", list(e.get_points("xyb")), e.closed)
    if e.dxftype() == "DIMENSION":
        print("  measurement", e.get_measurement())
        blk = doc.blocks.get(e.dxf.geometry)
        if blk:
            for be in blk:
                print("   blk", be.dxftype(), be.dxfattribs())
print("blocks:", [b.name for b in doc.blocks])
