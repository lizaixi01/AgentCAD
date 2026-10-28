import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3
from ezdxf.lldxf.tagwriter import TagCollector

d = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
old = ezdxf.readfile(d + r"\part_r1_backup.dxf")
new = ezdxf.readfile(d + r"\part.dxf")


def tags(e):
    tc = TagCollector(dxfversion=e.doc.dxfversion)
    e.export_dxf(tc)
    return tc.tags


def cmp_layout(lo, ln, label):
    ho = {e.dxf.handle: e for e in lo}
    hn = {e.dxf.handle: e for e in ln}
    if set(ho) != set(hn):
        print(label, "HANDLE SET DIFF", set(ho) ^ set(hn))
    changed = [h for h in ho if h in hn and tags(ho[h]) != tags(hn[h])]
    if changed:
        print(label, "changed:", [(h, ho[h].dxftype()) for h in changed])


cmp_layout(old.modelspace(), new.modelspace(), "MSP")
for b in old.blocks:
    if b.name in new.blocks:
        cmp_layout(b, new.blocks[b.name], "BLOCK " + b.name)
print("block names equal:", sorted(b.name for b in old.blocks) == sorted(b.name for b in new.blocks))

msp = new.modelspace()
for c in msp.query("CIRCLE"):
    print("hole", tuple(c.dxf.center)[:2], "dia", 2 * c.dxf.radius)
dm = new.entitydb["D2"]
c = Vec3(new.entitydb["95"].dxf.center)
print("D2 meas", dm.get_measurement(), "text", dm.dxf.text,
      "|p-c|", (Vec3(dm.dxf.defpoint) - c).magnitude, "|p4-c|", (Vec3(dm.dxf.defpoint4) - c).magnitude)
for e in new.blocks["*D5"]:
    t = e.dxftype()
    if t == "LINE":
        print("  D5 LINE", e.dxf.handle, tuple(round(v, 4) for v in e.dxf.start), tuple(round(v, 4) for v in e.dxf.end))
    elif t == "INSERT":
        print("  D5 ARROW", tuple(round(v, 4) for v in e.dxf.insert), "dist to c", round((Vec3(e.dxf.insert) - c).magnitude, 4))
    elif t == "MTEXT":
        print("  D5 MTEXT", e.text, tuple(round(v, 4) for v in e.dxf.insert))
    elif t == "POINT":
        print("  D5 POINT", tuple(round(v, 4) for v in e.dxf.location))
# any leftover Ø10 strings anywhere?
for layout in [new.modelspace()] + list(new.blocks):
    for e in layout:
        if e.dxftype() in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            s = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            if "10" in s:
                print("contains '10':", e.dxftype(), e.dxf.handle, repr(s))
outline = new.entitydb["91"]
ob = bbox.extents([outline])
for h in ("92", "93", "94", "95"):
    cb = bbox.extents([new.entitydb[h]])
    print("hole", h, "bbox", cb.extmin, cb.extmax, "inside plate:", ob.inside(cb.extmin) and ob.inside(cb.extmax))
print("audit errors:", len(new.audit().errors))
