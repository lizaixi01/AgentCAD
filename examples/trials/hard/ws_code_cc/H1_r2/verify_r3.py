import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3
from ezdxf.lldxf.tagwriter import TagCollector

d = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
old = ezdxf.readfile(d + r"\part_r2_backup.dxf")
new = ezdxf.readfile(d + r"\part.dxf")


def tags(e):
    tc = TagCollector(dxfversion=e.doc.dxfversion)
    e.export_dxf(tc)
    return tc.tags


def cmp_layout(lo, ln, label):
    ho = {e.dxf.handle: e for e in lo}
    hn = {e.dxf.handle: e for e in ln}
    if set(ho) - set(hn):
        print(label, "REMOVED", set(ho) - set(hn))
    added = [(h, hn[h].dxftype()) for h in hn if h not in ho]
    if added:
        print(label, "added:", added)
    changed = [h for h in ho if h in hn and tags(ho[h]) != tags(hn[h])]
    if changed:
        print(label, "CHANGED:", [(h, ho[h].dxftype()) for h in changed])


cmp_layout(old.modelspace(), new.modelspace(), "MSP")
for b in old.blocks:
    if b.name in new.blocks:
        cmp_layout(b, new.blocks[b.name], "BLOCK " + b.name)
print("new blocks:", sorted(set(b.name for b in new.blocks) - set(b.name for b in old.blocks)))
print("removed blocks:", sorted(set(b.name for b in old.blocks) - set(b.name for b in new.blocks)))

msp = new.modelspace()
outline = new.entitydb["91"]
ob = bbox.extents([outline])
print("plate bbox", ob.extmin, ob.extmax, "center", ob.center)
for c in msp.query("CIRCLE"):
    print("hole", c.dxf.handle, c.dxf.layer, tuple(c.dxf.center)[:2], "dia", 2 * c.dxf.radius)
big = [c for c in msp.query("CIRCLE") if abs(c.dxf.radius - 15) < 1e-9]
assert len(big) == 1
c0 = Vec3(big[0].dxf.center)
print("center hole offset from plate center:", (c0 - ob.center).magnitude)
for c in msp.query("CIRCLE"):
    if c is not big[0]:
        gap = (Vec3(c.dxf.center) - c0).magnitude - 15 - c.dxf.radius
        print("  wall to hole", c.dxf.handle, round(gap, 3))
cb = bbox.extents([big[0]])
print("center hole inside plate:", ob.inside(cb.extmin) and ob.inside(cb.extmax))

for dm in msp.query("DIMENSION"):
    if dm.dimtype == 3:
        p, p4 = Vec3(dm.dxf.defpoint), Vec3(dm.dxf.defpoint4)
        print("DIA dim", dm.dxf.handle, dm.dxf.layer, dm.dxf.dimstyle, "block", dm.dxf.geometry,
              "meas", round(dm.get_measurement(), 4), "text", repr(dm.dxf.text),
              "|p-c0|", round((p - c0).magnitude, 4), "|p4-c0|", round((p4 - c0).magnitude, 4))
        blk = new.blocks[dm.dxf.geometry]
        for e in blk:
            t = e.dxftype()
            if t == "MTEXT":
                print("   MTEXT", repr(e.text), tuple(round(v, 3) for v in e.dxf.insert), "h", e.dxf.char_height)
            elif t == "LINE":
                print("   LINE", tuple(round(v, 3) for v in e.dxf.start), "->", tuple(round(v, 3) for v in e.dxf.end))
            elif t == "INSERT":
                print("   ARROW", e.dxf.name, tuple(round(v, 3) for v in e.dxf.insert))
        eb = bbox.extents(blk)
        print("   dim block bbox", eb.extmin, eb.extmax)
        logo = bbox.extents([new.entitydb[h] for h in ("E1", "E3")])
        print("   overlaps LOGO bbox:", eb.has_intersection(logo))
print("audit errors:", len(new.audit().errors))
