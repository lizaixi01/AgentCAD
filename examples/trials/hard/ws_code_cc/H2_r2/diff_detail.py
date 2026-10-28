from collections import Counter
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent
a = ezdxf.readfile(HERE / "part.dxf")
b = ezdxf.readfile(HERE / "part_rev.dxf")


def diffs(ents_a, ents_b):
    out = Counter()
    samples = {}
    for x, y in zip(ents_a, ents_b):
        da, db = x.dxf.all_existing_dxf_attribs(), y.dxf.all_existing_dxf_attribs()
        for k in set(da) | set(db):
            if da.get(k) != db.get(k):
                key = (x.dxftype(), k)
                out[key] += 1
                samples.setdefault(key, (da.get(k), db.get(k)))
    return out, samples


tot = Counter()
smp = {}
for blk in a.blocks:
    if blk.name.startswith("*"):
        continue
    nb = b.blocks.get(blk.name)
    la, lb = list(blk), list(nb)
    if len(la) != len(lb) or [e.dxftype() for e in la] != [e.dxftype() for e in lb]:
        print("STRUCTURE DIFF", blk.name)
    o, s = diffs(la, lb)
    tot.update(o)
    smp.update(s)
    # also compare text content and polyline vertices
    for x, y in zip(la, lb):
        if x.dxftype() == "MTEXT" and x.text != y.text:
            print("MTEXT TEXT DIFF", blk.name)
        if x.dxftype() == "POLYLINE" and list(x.points()) != list(y.points()):
            print("POLY DIFF", blk.name)
print("block attribute diffs:", tot)
print("samples (old, new):", smp)

ps_a, ps_b = a.layouts.get("Base Plate"), b.layouts.get("Base Plate")
for h in ("673", "674", "B7F", "D11"):
    x, y = a.entitydb[h], b.entitydb[h]
    da, db = x.dxf.all_existing_dxf_attribs(), y.dxf.all_existing_dxf_attribs()
    print(h, x.dxftype(), {k: (da.get(k), db.get(k)) for k in set(da) | set(db) if da.get(k) != db.get(k)})
