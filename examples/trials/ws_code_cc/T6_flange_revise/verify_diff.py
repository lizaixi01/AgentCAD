import math
import os

import ezdxf
from ezdxf.math import Vec3

HERE = os.path.dirname(os.path.abspath(__file__))
old = ezdxf.readfile(os.path.join(HERE, "flange_orig.dxf"))
new = ezdxf.readfile(os.path.join(HERE, "flange.dxf"))


def sig(e):
    t = e.dxftype()
    d = e.dxf
    if t == "CIRCLE":
        c = Vec3(d.center)
        return f"CIRCLE[{d.layer}] c=({c.x:.3f},{c.y:.3f}) Ø{2 * d.radius:.3f}"
    if t == "LINE":
        return f"LINE[{d.layer}] {Vec3(d.start).round(3)}->{Vec3(d.end).round(3)}"
    if t == "DIMENSION":
        return (f"DIM[{d.layer}] text={d.text!r} meas={e.get_measurement():.3f} "
                f"p1={Vec3(d.defpoint).round(3)} p4={Vec3(d.defpoint4).round(3)}")
    return f"{t}[{d.layer}]"


so = {sig(e) for e in old.modelspace()}
sn = {sig(e) for e in new.modelspace()}
print("=== DIFF (orig -> new) ===")
for s in sorted(so - sn):
    print("  -", s)
for s in sorted(sn - so):
    print("  +", s)
print(f"  unchanged: {len(so & sn)} entities")

print("\n=== CHECKS ===")
msp = new.modelspace()
holes = list(msp.query("CIRCLE[layer=='HOLES']"))
angs = sorted(round(math.degrees(math.atan2(h.dxf.center.y, h.dxf.center.x)) % 360, 6) for h in holes)
print("hole count:", len(holes))
print("hole Ø:", {round(2 * h.dxf.radius, 6) for h in holes})
print("hole center radius:", {round(Vec3(h.dxf.center).magnitude, 6) for h in holes})
print("hole angles:", angs)
print("top hole:", [Vec3(h.dxf.center).round(6) for h in holes if h.dxf.center.y > 57])
print("CENTER circles Ø:", [2 * c.dxf.radius for c in msp.query("CIRCLE[layer=='CENTER']")])
for dim in msp.query("DIMENSION"):
    blk = new.blocks.get(dim.dxf.geometry)
    mt = [b for b in blk if b.dxftype() == "MTEXT"][0]
    print(f"dim {dim.dxf.handle}: rendered={mt.text!r} meas={dim.get_measurement():.6f} "
          f"text_ins={Vec3(mt.dxf.insert).round(2)} rot={mt.dxf.get('rotation', 0):.1f}")
# any stale dimension blocks?
used = {d.dxf.geometry for d in msp.query("DIMENSION")}
print("D-blocks:", [b.name for b in new.blocks if b.name.startswith("*D")], "used:", sorted(used))
auditor = new.audit()
print("audit errors:", len(auditor.errors), "fixes:", len(auditor.fixes))
