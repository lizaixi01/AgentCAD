"""Primitives in the bottom band (y < 45) of the paper-space sheet."""
from pathlib import Path
import ezdxf
from ezdxf import bbox

HERE = Path(__file__).resolve().parent
doc = ezdxf.readfile(HERE / "part.dxf")
ps = doc.layouts.get("Base Plate")


def prims(ents, src=""):
    for e in ents:
        if e.dxftype() in ("INSERT", "POLYLINE", "LWPOLYLINE"):
            yield from prims(e.virtual_entities(), src or (e.dxf.name if e.dxftype() == "INSERT" else ""))
        elif e.dxftype() not in ("VIEWPORT", "POINT"):
            yield e, src


rows = []
for p, src in prims(ps):
    b = bbox.extents([p], fast=False)
    if b.has_data and b.extmin.y < 45 and b.extmin.x < 245 and p.dxftype() != "SOLID":
        t = p.text if p.dxftype() == "MTEXT" else ""
        rows.append((round(b.extmin.y, 1), f"{p.dxftype():6} {p.dxf.layer:16} {src:15} ({b.extmin.x:6.1f},{b.extmin.y:5.1f})-({b.extmax.x:6.1f},{b.extmax.y:5.1f}) {t[:30]!r}"))
for _, r in sorted(rows):
    print(r)
