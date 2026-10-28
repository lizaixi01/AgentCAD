"""Which primitives sit around the paper-space Ø40 holes?"""
from pathlib import Path
import ezdxf
from ezdxf import bbox
from ezdxf.math import BoundingBox2d, Vec3

HERE = Path(__file__).resolve().parent
doc = ezdxf.readfile(HERE / "part.dxf")
ps = doc.layouts.get("Base Plate")


def prims(ents, src=""):
    for e in ents:
        if e.dxftype() == "INSERT":
            yield from prims(e.virtual_entities(), src or e.dxf.name)
        elif e.dxftype() not in ("VIEWPORT", "POINT"):
            yield e, src


for cx in (168.811685184828, 271.511685184828):
    c = Vec3(cx, 138.9690077022958)
    print("hole", c)
    win = BoundingBox2d([(cx - 25, 138.97 - 25), (cx + 25, 138.97 + 25)])
    for p, src in prims(ps):
        b = bbox.extents([p], fast=False)
        if not b.has_data:
            continue
        b2 = BoundingBox2d([b.extmin.vec2, b.extmax.vec2])
        if win.has_overlap(b2) and b2.size.x < 60 and b2.size.y < 60:
            extra = p.text if p.dxftype() == "MTEXT" else ""
            print(f"  {p.dxftype():7} {p.dxf.layer:14} {src:16} ({b2.extmin.x:6.1f},{b2.extmin.y:6.1f})-({b2.extmax.x:6.1f},{b2.extmax.y:6.1f}) {extra}")
        elif win.has_overlap(b2):
            print(f"  BIG {p.dxftype()} {p.dxf.layer} {src} {b2.extmin} {b2.extmax}")
