from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.math import BoundingBox2d

HERE = Path(__file__).resolve().parent
orig = ezdxf.readfile(HERE / "part.dxf")
rev = ezdxf.readfile(HERE / "part_rev.dxf")
print("rev version", rev.dxfversion, "units", rev.header.get("$INSUNITS"))
aud = rev.audit()
print("audit errors", len(aud.errors), "fixes", len(aud.fixes))

EXPECT = {10.2: 10.5, 25.0: 26.0}
# attributes ezdxf does not write back when they equal the DXF default
DEFAULT_ONLY = {"flow_direction": 1, "line_spacing_style": 1, "line_spacing_factor": 1.0,
                "default_lighting_flag": 1}
problems, cosmetic = [], []


def attrs(e):
    d = e.dxf.all_existing_dxf_attribs()
    d.pop("radius", None)
    return {k: (tuple(v) if hasattr(v, "__iter__") and not isinstance(v, str) else v) for k, v in d.items()}


def prims(ents):
    for e in ents:
        if e.dxftype() in ("INSERT", "POLYLINE", "LWPOLYLINE"):
            yield from prims(e.virtual_entities())
        elif e.dxftype() not in ("VIEWPORT", "POINT"):
            yield e


def box2d(ents):
    b = bbox.extents(ents, fast=False)
    return BoundingBox2d([b.extmin.vec2, b.extmax.vec2]) if b.has_data else None


for name, scale in (("Model", 1.0), ("Base Plate", 0.325)):
    lo, lr = orig.layouts.get(name), rev.layouts.get(name)
    eo = {e.dxf.handle: e for e in lo}
    er = {e.dxf.handle: e for e in lr}
    missing = set(eo) - set(er)
    added = [er[h] for h in er if h not in eo]
    if missing:
        problems.append(f"{name}: missing {missing}")
    for h, a in eo.items():
        b = er.get(h)
        if b is None:
            continue
        da, db = attrs(a), attrs(b)
        diff = {k for k in set(da) | set(db) if da.get(k) != db.get(k)}
        if diff - set(DEFAULT_ONLY) or any(da.get(k, DEFAULT_ONLY[k]) != DEFAULT_ONLY[k] for k in diff):
            problems.append(f"{name}: {h} attributes changed {diff}")
        elif diff:
            cosmetic.append((name, h, a.dxftype(), sorted(diff)))
        if a.dxftype() == "CIRCLE":
            do, dr = a.dxf.radius * 2 / scale, b.dxf.radius * 2 / scale
            want = next((n for o, n in EXPECT.items() if abs(do - o) < 1e-4), do)
            if abs(dr - want) > 1e-9:
                problems.append(f"{name}: circle {h} {do}->{dr}, want {want}")
        elif a.dxftype() == "ARC" and a.dxf.radius != b.dxf.radius:
            problems.append(f"{name}: arc {h} radius changed")
    co = Counter(round(e.dxf.radius * 2 / scale, 3) for e in lo.query("CIRCLE"))
    cr = Counter(round(e.dxf.radius * 2 / scale, 3) for e in lr.query("CIRCLE"))
    print(f"\n[{name}]  true diameter: orig -> rev")
    for d in sorted(set(co) | set(cr)):
        print(f"  Ø{d:<5}: {co[d]:>3} -> {cr[d]:>3}")
    print("  orig", dict(Counter(e.dxftype() for e in lo)))
    print("  rev ", dict(Counter(e.dxftype() for e in lr)))
    big = [c for c in lr.query("CIRCLE") if abs(c.dxf.radius * 2 / scale - 40) < 1e-4]
    obs = [(p, box2d([p])) for p in prims(e for e in lr if e.dxf.handle in eo)]
    obs = [(p, b) for p, b in obs if b is not None]
    dimmed = set()
    for e in added:
        if e.dxftype() == "DIMENSION":
            ov = e.override()
            blk = rev.blocks.get(e.dxf.geometry)
            texts = [x.text for x in blk if x.dxftype() == "MTEXT"]
            hole = [x for x in big if (x.dxf.center - e.dxf.defpoint).magnitude <= x.dxf.radius + 1e-6
                    and (x.dxf.center - e.dxf.defpoint4).magnitude <= x.dxf.radius + 1e-6
                    and abs((e.dxf.defpoint - e.dxf.defpoint4).magnitude - 2 * x.dxf.radius) < 1e-6]
            dimmed.update(x.dxf.handle for x in hole)
            lfac = ov.get("dimlfac", 1)
            parts = [v for v in e.virtual_entities() if v.dxftype() == "MTEXT"]
            tb = box2d(parts)
            hits = [p for p, b in obs if p not in hole and tb.has_overlap(b)]
            print(f"  DIM diameter={e.dimtype & 7 == 3} layer={e.dxf.layer} meas={e.get_measurement():.4f} x lfac {lfac:.4f} "
                  f"= {e.get_measurement() * lfac:.3f}; text={texts}; hole={[x.dxf.center.round(3) for x in hole]}; "
                  f"text collisions={len(hits)}")
        elif e.dxftype() == "TEXT":
            tb = box2d([e])
            ol = bbox.extents([x for x in lr.query("LINE ARC") if x.dxf.layer == "Visible Edges"])
            hits = [(p.dxftype(), p.dxf.layer) for p, b in obs if tb.has_overlap(b)]
            print(f"  TEXT {e.dxf.text!r} h={e.dxf.height} layer={e.dxf.layer} style={e.dxf.style} "
                  f"ins={e.dxf.insert.round(3)} bbox=({tb.extmin.x:.1f},{tb.extmin.y:.1f})-({tb.extmax.x:.1f},{tb.extmax.y:.1f}); "
                  f"outline y={ol.extmin.y:.2f} below={tb.extmax.y < ol.extmin.y}; collisions={hits}")
        else:
            problems.append(f"{name}: unexpected new {e.dxftype()}")
    if len(dimmed) != 2:
        problems.append(f"{name}: Ø40 holes dimensioned: {len(dimmed)}")

bo = {b.name for b in orig.blocks}
br = {b.name for b in rev.blocks}
print("\nblocks removed:", bo - br, " added:", sorted(br - bo))
for bn in sorted(br - bo):
    print("  ", bn, dict(Counter(x.dxftype() for x in rev.blocks.get(bn))))
cf = rev.blocks.get("_CLOSEDFILLED")
if cf is not None:
    h = cf.block_record_handle
    refs = [x for x in rev.entitydb.values() if h in str(getattr(x, "tags", ""))]
    print("_CLOSEDFILLED record", h)
print("cosmetic (default-valued attrs not re-written by ezdxf):", cosmetic)
print("PROBLEMS:", problems or "none")
