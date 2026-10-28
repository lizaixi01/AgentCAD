import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3

d = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
doc = ezdxf.readfile(d + r"\part.dxf")
db = doc.entitydb
msp = doc.modelspace()

ob = bbox.extents([db["91"]])
print("plate bbox", ob.extmin, ob.extmax, "size", ob.size)
for c in msp.query("CIRCLE"):
    print("circle", c.dxf.handle, tuple(c.dxf.center)[:2], "dia", 2 * c.dxf.radius, c.dxf.layer)
for h in ("96", "D2", "116"):
    dm = db[h]
    print("dim", h, "meas", round(dm.get_measurement(), 4), "text", repr(dm.dxf.text), "block", dm.dxf.geometry)
c = Vec3(db["95"].dxf.center)
dm = db["D2"]
print("D2 |p-c|", (Vec3(dm.dxf.defpoint) - c).magnitude, "|p4-c|", (Vec3(dm.dxf.defpoint4) - c).magnitude)
for e in doc.blocks["*D5"]:
    if e.dxftype() == "INSERT":
        print("  *D5 arrow dist to c", round((Vec3(e.dxf.insert) - c).magnitude, 6))
    elif e.dxftype() == "MTEXT":
        print("  *D5 text", e.text)
for layout in [msp] + list(doc.blocks):
    for e in layout:
        if e.dxftype() in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            s = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            if "12" in s or "%%c" in s.lower() or "Ø" in s:
                print("text check:", e.dxftype(), e.dxf.handle, repr(s))
print("audit errors:", len(doc.audit().errors))
