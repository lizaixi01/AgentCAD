"""Verify round 5: compare part.dxf with the pre-round-5 backup."""
import os
import sys

import ezdxf
from ezdxf import bbox

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
old = ezdxf.readfile(os.path.join(HERE, "part_r4_final.dxf"))
new = ezdxf.readfile(os.path.join(HERE, "part.dxf"))
print("audit errors:", len(new.audit().errors))


def dump(doc):
    out = {}
    for e in doc.modelspace():
        tags = [str(t) for t in e.dxf.all_existing_dxf_attribs().items()]
        if e.dxftype() == "INSERT":
            tags += [str(a.dxf.all_existing_dxf_attribs()) for a in e.attribs]
        out[e.dxf.handle] = (e.dxftype(), tags)
    return out


o, n = dump(old), dump(new)
print("removed:", set(o) - set(n))
added = set(n) - set(o)
print("added:", added)
print("changed:", [h for h in o if h in n and o[h] != n[h]])

tb = [e for e in new.modelspace().query("INSERT") if e.dxf.name == "TB"][0]
print("attribs:", [(a.dxf.tag, a.dxf.text) for a in tb.attribs])

others = [e for e in new.modelspace() if e.dxf.handle not in added]
for h in added:
    t = new.entitydb[h]
    ext = bbox.extents([t])
    print("note:", t.dxftype(), t.dxf.layer, repr(t.dxf.text), "plain:", t.plain_text(),
          "h", t.dxf.height, "bbox", ext.extmin, ext.extmax)
    for e in others:
        eb = bbox.extents([e])
        if eb.has_data and ext.has_intersection(eb):
            print("  OVERLAPS", e.dxftype(), e.dxf.handle, eb.extmin, eb.extmax)

# blocks unchanged (apart from nothing)
print("block names equal:", sorted(b.name for b in old.blocks) == sorted(b.name for b in new.blocks))
