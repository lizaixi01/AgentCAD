import sys
import ezdxf

old = ezdxf.readfile(sys.argv[1])
new = ezdxf.readfile(sys.argv[2])


def sig(doc):
    out = {}
    for e in doc.modelspace():
        out[e.dxf.handle] = (e.dxftype(), sorted((k, str(v)) for k, v in e.dxf.all_existing_dxf_attribs().items()))
    return out


so, sn = sig(old), sig(new)
changed = [h for h in so if h not in sn or so[h] != sn[h]]
added = [h for h in sn if h not in so]
print("changed/removed old entities:", changed)
print("added:", [(h, sn[h][0]) for h in added])

# blocks unchanged (TB etc.)
for b in old.blocks:
    nb = new.blocks.get(b.name)
    same = nb is not None and [e.dxftype() for e in b] == [e.dxftype() for e in nb]
    if not same:
        print("block differs:", b.name)
print("new blocks:", [b.name for b in new.blocks if b.name not in old.blocks])

msp = new.modelspace()
for h in added:
    e = new.entitydb[h]
    if e.dxftype() == "CIRCLE":
        print("circle", tuple(e.dxf.center), "dia", 2 * e.dxf.radius, "layer", e.dxf.layer)
    if e.dxftype() == "DIMENSION":
        print("dim meas", e.get_measurement(), "layer", e.dxf.layer, "xdata", e.get_xdata("ACAD"))
        for be in new.blocks[e.dxf.geometry]:
            if be.dxftype() in ("MTEXT", "TEXT"):
                print("  dim text:", be.dxftype(), repr(be.text if be.dxftype() == "MTEXT" else be.dxf.text), tuple(be.dxf.insert))
            else:
                print("  ", be.dxftype())
