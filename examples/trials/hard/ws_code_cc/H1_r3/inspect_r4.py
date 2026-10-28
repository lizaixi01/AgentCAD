"""Round 4 inspection: circles and dimensions in each given file."""
import sys
import ezdxf

for fn in sys.argv[1:]:
    doc = ezdxf.readfile(fn)
    print("==", fn)
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "CIRCLE":
            print(e.dxf.handle, t, e.dxf.layer, tuple(e.dxf.center), e.dxf.radius)
        elif t == "DIMENSION":
            d = e.dxf
            blk = doc.blocks.get(d.geometry)
            texts = [m.text for m in blk.query("MTEXT TEXT")] if blk else None
            print(d.handle, t, d.layer, d.dimtype, d.geometry, repr(d.get("text")), tuple(d.defpoint),
                  tuple(d.defpoint4) if d.hasattr("defpoint4") else None, tuple(d.text_midpoint),
                  e.get_measurement(), texts)
            print("   ov:", e.dim_style_attributes())
