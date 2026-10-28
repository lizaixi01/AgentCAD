import sys
import ezdxf

doc = ezdxf.readfile(sys.argv[1])
ds = doc.dimstyles.get("AGENTCAD")
print("AGENTCAD:", {k: v for k, v in ds.dxfattribs().items() if k.startswith("dim")})
msp = doc.modelspace()
for dim in msp.query("DIMENSION"):
    print(dim.dxf.handle, dim.dxf.geometry, "xdata:", dim.get_xdata("ACAD") if dim.has_xdata("ACAD") else None)
    print("   overrides:", dim.override().dimstyle_attribs)
for e in msp.query("TEXT MTEXT INSERT"):
    print(e.dxftype(), e.dxf.handle)
print("blocks:", [b.name for b in doc.blocks])
