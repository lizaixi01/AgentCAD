import ezdxf
from ezdxf import audit

new = ezdxf.readfile("part.dxf")
old = ezdxf.readfile("part_orig_backup.dxf")
auditor = new.audit()
print("audit errors:", len(auditor.errors), "fixes:", len(auditor.fixes))

print("layers:")
for l in new.layers:
    print("  ", l.dxf.name, l.color, l.dxf.linetype, l.dxf.lineweight)

msp = new.modelspace()
ok = True
for e in msp:
    d = e.dxf
    bylayer = d.get("color", 256) == 256 and d.get("linetype", "BYLAYER").upper() == "BYLAYER" \
        and d.get("lineweight", -1) == -1 and not d.hasattr("true_color")
    if not bylayer:
        ok = False
    print(f"  {d.handle} {e.dxftype():10s} {d.layer:8s} bylayer={bylayer}")
print("all ByLayer:", ok)
from collections import Counter
print("count per layer:", Counter(e.dxf.layer for e in msp))

# compare geometry/content of kept entities with the original by handle
oldmsp = {e.dxf.handle: e for e in old.modelspace()}
def sig(e):
    t = e.dxftype(); d = e.dxf
    if t == "LINE": return (tuple(d.start), tuple(d.end))
    if t == "CIRCLE": return (tuple(d.center), d.radius)
    if t == "LWPOLYLINE": return (tuple(map(tuple, e.get_points())), e.closed)
    if t == "TEXT": return (d.text, tuple(d.insert), d.height, d.rotation, d.style)
    if t == "MTEXT": return (e.text, tuple(d.insert), d.char_height, d.style)
    if t == "DIMENSION": return (d.dimtype, e.get_measurement(), d.text, tuple(d.defpoint),
                                 tuple(d.get("defpoint2", (0, 0, 0))), tuple(d.get("defpoint3", (0, 0, 0))),
                                 tuple(d.get("defpoint4", (0, 0, 0))), tuple(d.text_midpoint), d.geometry)
same = all(sig(e) == sig(oldmsp[e.dxf.handle]) for e in msp)
print("kept entities identical geometry/content:", same, "| kept", len(msp), "of", len(oldmsp))

# dimension block geometry unchanged
for dim in msp.query("DIMENSION"):
    nb = new.blocks.get(dim.dxf.geometry); ob = old.blocks.get(dim.dxf.geometry)
    geo = lambda b: [(e.dxftype(), e.dxf.layer, str(e.dxf.all_existing_dxf_attribs().get('start', '')),
                      str(e.dxf.all_existing_dxf_attribs().get('insert', ''))) for e in b]
    print("  ", dim.dxf.geometry, "meas", dim.get_measurement(), "block geo same:", geo(nb) == geo(ob),
          "colors:", sorted({e.dxf.get('color', 256) for e in nb}))
print("header CLAYER:", new.header.get("$CLAYER"))
