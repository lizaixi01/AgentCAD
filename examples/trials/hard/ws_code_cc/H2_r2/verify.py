from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec2

HERE = Path(__file__).parent
a = ezdxf.readfile(HERE / "part.dxf")
b = ezdxf.readfile(HERE / "part_rev.dxf")
print("rev version", b.dxfversion, "INSUNITS", b.header.get("$INSUNITS"))

auditor = b.audit()
print("audit errors:", len(auditor.errors), "fixes:", len(auditor.fixes))
for e in auditor.errors:
    print("  ", e)


def dia_count(layout, scale=1.0):
    return Counter(round(2 * c.dxf.radius / scale, 3) for c in layout.query("CIRCLE"))


for name, scale in (("Model", 1.0), ("Base Plate", 0.325)):
    ca, cb = dia_count(a.layouts.get(name), scale), dia_count(b.layouts.get(name), scale)
    print(f"[{name}] hole counts (full-scale dia): before / after")
    for d in sorted(set(ca) | set(cb)):
        print(f"   Ø{d:<6} {ca[d]:>3} -> {cb[d]:>3}")

# entity-level comparison by handle
for name in ("Model", "Base Plate"):
    la, lb = a.layouts.get(name), b.layouts.get(name)
    ea = {e.dxf.handle: e for e in la}
    eb = {e.dxf.handle: e for e in lb}
    removed = set(ea) - set(eb)
    added = [eb[h] for h in eb if h not in ea]
    changed = Counter()
    bad = []
    for h, e in ea.items():
        if h not in eb:
            continue
        x, y = e.dxf.all_existing_dxf_attribs(), eb[h].dxf.all_existing_dxf_attribs()
        diff = {k for k in set(x) | set(y) if x.get(k) != y.get(k)}
        if not diff:
            continue
        if e.dxftype() == "CIRCLE" and diff == {"radius"} and x["center"] == y["center"]:
            changed[(round(2 * x["radius"], 4), round(2 * y["radius"], 4))] += 1
        else:
            bad.append((h, e.dxftype(), diff))
    print(f"[{name}] removed={len(removed)} added={[(e.dxftype(), e.dxf.layer) for e in added]}")
    print(f"   radius-only changes (old->new dia, centers equal): {dict(changed)}")
    print(f"   unexpected modifications: {bad}")

# compare block definitions (title block etc.) by entity attribs
blk_diff = []
for blk in a.blocks:
    if blk.name.startswith("*") :
        continue
    nb = b.blocks.get(blk.name)
    sa = [e.dxf.all_existing_dxf_attribs() for e in blk]
    sb = [e.dxf.all_existing_dxf_attribs() for e in nb] if nb else None
    if sa != sb:
        blk_diff.append(blk.name)
print("changed named blocks:", blk_diff)
print("new blocks:", [x.name for x in b.blocks if x.name not in a.blocks])

msp = b.modelspace()
circles = list(msp.query("CIRCLE"))
for d in msp.query("DIMENSION"):
    m = d.get_measurement()
    ov = d.get_dim_style()
    blk = d.get_geometry_block()
    ext = bbox.extents(d.virtual_entities())
    texts = [e.text for e in d.virtual_entities() if e.dxftype() == "MTEXT"]
    p = Vec2(d.dxf.defpoint)
    q = Vec2(d.dxf.defpoint4)
    print("DIM type", d.dimtype, "layer", d.dxf.layer, "measure", round(m, 4), "text", texts,
          "chord", p.round(3), q.round(3), "center", ((p + q) / 2).round(3), "block", blk.dxf.name)
    print("    dimtxt override", d.get_acad_dstyle(ov) if False else d.override().get("dimtxt"),
          "extents", ext.extmin.round(2), ext.extmax.round(2))
    # clash check of the dimension text/leader box with other holes
    hits = []
    for c in circles:
        cc = Vec2(c.dxf.center)
        r = c.dxf.radius
        if abs(2 * r - 40) < 1e-6:
            continue
        nx = min(max(cc.x, ext.extmin.x), ext.extmax.x)
        ny = min(max(cc.y, ext.extmin.y), ext.extmax.y)
        if (Vec2(nx, ny) - cc).magnitude < r:
            hits.append((cc.round(2), round(2 * r, 2)))
    print("    holes overlapping dim bbox:", hits)

for t in msp.query("TEXT"):
    ext = bbox.extents([t])
    print("TEXT", repr(t.dxf.text), "h", t.dxf.height, "layer", t.dxf.layer, "insert", Vec2(t.dxf.insert).round(3),
          "bbox", ext.extmin.round(2), ext.extmax.round(2))
outline_bottom = min(min(l.dxf.start.y, l.dxf.end.y) for l in msp.query('LINE[layer=="Visible Edges"]'))
print("outline bottom y =", round(outline_bottom, 3))
