import sys
from collections import Counter
import ezdxf
from ezdxf import bbox
from ezdxf.math import BoundingBox2d

sys.stdout.reconfigure(encoding="utf-8")
a = ezdxf.readfile(sys.argv[1])
b = ezdxf.readfile(sys.argv[2])


def sig(e):
    return (e.dxftype(), e.dxf.layer, str(sorted((k, str(v)) for k, v in e.dxfattribs().items() if k not in ("handle", "owner", "flow_direction"))))


ba = {blk.name: Counter(sig(e) for e in blk) for blk in a.blocks}
bb = {blk.name: Counter(sig(e) for e in blk if True) for blk in b.blocks}
diff = [n for n in ba if not n.startswith("*") and ba[n] != bb.get(n)]
print("pre-existing named blocks changed:", diff)

# overlap check of new annotation in each layout against old entities
for name in ("Model", "Base Plate"):
    old = {e.dxf.handle for e in a.layouts.get(name)}
    lay = b.layouts.get(name)
    new = [e for e in lay if e.dxftype() in ("DIMENSION", "TEXT")]
    for n in new:
        nb = bbox.extents([n])
        hits = []
        for e in lay:
            if e.dxf.handle not in old or e.dxftype() == "VIEWPORT":
                continue
            if e.dxftype() == "INSERT" and e.dxf.name == "Title":
                # check against title-block contents individually
                subs = list(e.virtual_entities())
            else:
                subs = [e]
            for s in subs:
                if s.dxftype() == "INSERT":
                    subs2 = list(s.virtual_entities())
                else:
                    subs2 = [s]
                for s2 in subs2:
                    eb = bbox.extents([s2])
                    if eb.has_data and BoundingBox2d([nb.extmin, nb.extmax]).has_intersection(BoundingBox2d([eb.extmin, eb.extmax])):
                        hits.append((e.dxftype(), e.dxf.layer, e.dxf.name if e.dxftype() == "INSERT" else "", s2.dxftype(),
                                     [round(v, 1) for v in (*eb.extmin.vec2, *eb.extmax.vec2)]))
        print(name, n.dxftype(), [round(v, 1) for v in (*nb.extmin.vec2, *nb.extmax.vec2)])
        for h in hits:
            print("    overlaps", h)
