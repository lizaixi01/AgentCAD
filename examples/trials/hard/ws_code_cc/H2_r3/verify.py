import sys
from collections import Counter
import ezdxf
from ezdxf import bbox

sys.stdout.reconfigure(encoding="utf-8")
a = ezdxf.readfile(sys.argv[1])
b = ezdxf.readfile(sys.argv[2])
print("rev version", b.dxfversion, "audit errors:", len(b.audit().errors))


def sig(e):
    t = e.dxftype()
    d = e.dxf
    r = lambda v: tuple(round(x, 4) for x in v)
    if t == "CIRCLE":
        return (t, d.layer, r(d.center), round(d.radius, 5))
    if t == "LINE":
        return (t, d.layer, r(d.start), r(d.end))
    if t == "ARC":
        return (t, d.layer, r(d.center), round(d.radius, 5), round(d.start_angle, 4), round(d.end_angle, 4))
    if t == "INSERT":
        return (t, d.layer, d.name, r(d.insert))
    if t in ("TEXT", "MTEXT"):
        return (t, d.layer, r(d.insert), e.text if t == "MTEXT" else d.text)
    if t == "DIMENSION":
        return (t, d.layer, d.dimtype, round(e.get_measurement(), 4))
    return (t, d.layer, d.handle)


for name in ("Model", "Base Plate"):
    la, lb = a.layouts.get(name), b.layouts.get(name)
    sa, sb = Counter(sig(e) for e in la), Counter(sig(e) for e in lb)
    print(f"\n== {name}: {len(la)} -> {len(lb)} entities")
    print(" removed:", sorted((sa - sb).items()))
    print(" added:  ", sorted((sb - sa).items()))
    scale = 1.0 if name == "Model" else 0.325
    ca = Counter(round(c.dxf.radius * 2 / scale, 3) for c in la.query("CIRCLE"))
    cb = Counter(round(c.dxf.radius * 2 / scale, 3) for c in lb.query("CIRCLE"))
    print(" hole count by true diameter (before -> after):")
    for d in sorted(set(ca) | set(cb)):
        print(f"   Ø{d:g}: {ca[d]} -> {cb[d]}")
    # handle check: circles kept their handles
    ha = {c.dxf.handle: c for c in la.query("CIRCLE")}
    hb = {c.dxf.handle: c for c in lb.query("CIRCLE")}
    print(" circle handles identical:", set(ha) == set(hb),
          " centers unchanged:", all(ha[h].dxf.center.isclose(hb[h].dxf.center) for h in ha))
    for dim in lb.query("DIMENSION"):
        ov = dim.override()
        blk = b.blocks.get(dim.dxf.geometry)
        texts = [x.plain_text() for x in blk.query("MTEXT")]
        print(" DIM", dim.dxf.layer, "type", dim.dimtype, "meas", round(dim.get_measurement(), 4),
              "dimlfac", ov.get("dimlfac", 1), "center", dim.dxf.defpoint, "->", dim.dxf.defpoint4,
              "block", dim.dxf.geometry, Counter(x.dxftype() for x in blk), "text", texts)
    for t in lb.query("TEXT"):
        print(" TEXT", t.dxf.layer, t.dxf.insert, "h", t.dxf.height, repr(t.dxf.text), "bbox", bbox.extents([t]))

# blocks: compare non-anonymous-dimension blocks
ba = {blk.name: Counter(sig(e) for e in blk) for blk in a.blocks if not blk.name.startswith("*")}
bb = {blk.name: Counter(sig(e) for e in blk) for blk in b.blocks if not blk.name.startswith("*")}
print("\nnamed blocks identical:", ba == bb)
print("new anonymous blocks:", sorted(set(x.name for x in b.blocks) - set(x.name for x in a.blocks)))
print("layers same:", [l.dxf.name for l in a.layers] == [l.dxf.name for l in b.layers])
