import ezdxf, sys
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector

d = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
old = ezdxf.readfile(d + r"\part_r0_backup.dxf")
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
    print(label, "changed:", [(h, ho[h].dxftype()) for h in changed])

cmp_layout(old.modelspace(), new.modelspace(), "MSP")
for b in old.blocks:
    if b.name in new.blocks:
        cmp_layout(b, new.blocks[b.name], "BLOCK " + b.name)
print("tables layers equal:", [l.dxf.name for l in old.layers] == [l.dxf.name for l in new.layers])

msp = new.modelspace()
ol = new.entitydb["91"]
print("outline:", [(round(x, 3), round(y, 3), round(b, 4)) for x, y, b in ol.get_points("xyb")])
print("outline bbox:", bbox.extents([ol]))
for c in msp.query("CIRCLE"):
    print("hole", tuple(c.dxf.center)[:2], "r", c.dxf.radius)
for dm in msp.query("DIMENSION"):
    print("dim", dm.dxf.handle, "meas", round(dm.get_measurement(), 4) if dm.dimtype != 3 else dm.get_measurement(),
          "texts in block:", [e.text for e in new.blocks[dm.dxf.geometry].query("MTEXT")])
for e in new.blocks["*D1"]:
    print("  D1", e.dxftype(), bbox.extents([e]))
for e in new.blocks["*D5"]:
    print("  D5", e.dxftype(), bbox.extents([e]))
for h in ("E1", "E2", "E3", "ED"):
    print("other", h, bbox.extents([new.entitydb[h]]))
print("audit errors:", len(new.audit().errors))
