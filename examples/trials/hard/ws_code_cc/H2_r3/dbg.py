import sys
import ezdxf

sys.stdout.reconfigure(encoding="utf-8")
a = ezdxf.readfile(sys.argv[1])
b = ezdxf.readfile(sys.argv[2])
for name in ("2dTransSymbol1", "Default Border", "Title"):
    shown = set()
    for x, y in zip(a.blocks[name], b.blocks[name]):
        da, db = x.dxfattribs(), y.dxfattribs()
        d = {k: (da.get(k), db.get(k)) for k in set(da) | set(db)
             if k not in ("flow_direction",) and str(da.get(k)) != str(db.get(k))}
        if d and x.dxftype() not in shown:
            shown.add(x.dxftype())
            print(name, x.dxftype(), d)
        if x.dxftype() == "POLYLINE":
            pa = [v.dxfattribs() for v in x.vertices]
            pb = [v.dxfattribs() for v in y.vertices]
            for va, vb in zip(pa, pb):
                dd = {k: (va.get(k), vb.get(k)) for k in set(va) | set(vb) if k not in ("handle", "owner") and str(va.get(k)) != str(vb.get(k))}
                if dd and "VERTEX" not in shown:
                    shown.add("VERTEX")
                    print(name, "VERTEX", dd)
