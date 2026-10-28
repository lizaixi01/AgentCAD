from pathlib import Path
import ezdxf
from ezdxf import bbox

HERE = Path(__file__).resolve().parent
orig = ezdxf.readfile(HERE / "part.dxf")
rev = ezdxf.readfile(HERE / "part_rev.dxf")
for h in ["673", "674", "B7F", "D11"]:
    a, b = orig.entitydb[h], rev.entitydb[h]
    da, db = a.dxf.all_existing_dxf_attribs(), b.dxf.all_existing_dxf_attribs()
    print(h, a.dxftype(), {k: (da.get(k), db.get(k)) for k in set(da) | set(db) if da.get(k) != db.get(k)})
ps = rev.layouts.get("Base Plate")
for e in ps.query("DIMENSION"):
    for v in e.virtual_entities():
        print(v.dxftype(), bbox.extents([v], fast=False), v.dxf.get("char_height") if v.dxftype() == "MTEXT" else "")
    for x in ps.query("INSERT"):
        if x.dxf.name in ("2dTransSymbol58", "2dTransSymbol59", "2dTransSymbol38", "2dTransSymbol12"):
            print(x.dxf.name, bbox.extents([x], fast=False))
    break
