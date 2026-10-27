"""Experiment A4: the checks that were BLOCKED without AutoCAD (research record §5.8)
plus open questions. Each crafted DXF is DXFIN'ed into a fresh AutoCAD 2027 drawing,
audited, dumped, and written back with DXFOUT 2018; the written file is re-read
with ezdxf to see what AutoCAD stored.

    python research/autocad/exp_blocked_items.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from acad import WORK, run_lisp  # noqa: E402

OUT = WORK / "blocked_inputs"

DUMP = r'''
(defun fmt (v) (cond ((= (type v) 'REAL) (rtos v 2 12)) ((= (type v) 'INT) (itoa v)) ((= (type v) 'STR) v)
  ((= (type v) 'LIST) (if (numberp (car v)) (strcat (rtos (car v) 2 12) "," (rtos (cadr v) 2 12) (if (caddr v) (strcat "," (rtos (caddr v) 2 12)) "")) "?")) (T "?")))
(setq ss (ssget "X") i 0)
(out "nent" (if ss (sslength ss) 0))
(if ss (repeat (sslength ss) (setq ed (entget (ssname ss i) '("*")) s (cdr (assoc 0 ed)) i (1+ i))
  (foreach g ed (if (member (car g) '(10 11 13 14 40 42 50 51 210)) (setq s (strcat s "|" (itoa (car g)) ":" (fmt (cdr g))))))
  (if (assoc -3 ed) (setq s (strcat s "|xdata:" (apply 'strcat (mapcar '(lambda (x) (strcat (car x) ";")) (cdr (assoc -3 ed)))))))
  (out "ent" s)))
(command "_.AUDIT" "_N")
(command "_.DXFOUT" "%DIR%/acad_out.dxf" "_V" "2018" "16")
'''


def make_inputs() -> dict[str, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}

    def new():
        d = ezdxf.new("R2010", setup=True)
        d.header["$INSUNITS"] = 4
        return d

    # 1: dimensions as ezdxf writes them (no group 42) + one with a stale block
    d = new()
    m = d.modelspace()
    m.add_linear_dim(base=(50, -10), p1=(0, 0), p2=(100, 0), dimstyle="EZDXF").render()
    m.add_radius_dim(center=(0, 50), radius=10, angle=45, dimstyle="EZDXF").render()
    stale = m.add_linear_dim(base=(50, -30), p1=(0, 0), p2=(100, 0), dimstyle="EZDXF")
    stale.render()
    stale.dimension.dxf.defpoint3 = (150, 0, 0)  # moved after rendering: block still shows 100
    files["dims_no42_and_stale"] = OUT / "dims.dxf"
    d.saveas(files["dims_no42_and_stale"])

    # 2: negative radius; 2b: NaN coordinate (raw text edit, ezdxf refuses to write NaN)
    d = new()
    d.modelspace().add_circle((0, 0), 5).dxf.radius = -5
    d.modelspace().add_line((0, 0), (10, 0))
    files["negative_radius"] = OUT / "negr.dxf"
    d.saveas(files["negative_radius"])
    d = new()
    d.modelspace().add_line((0, 0), (12345.678, 0))
    p = OUT / "nan.dxf"
    d.saveas(p)
    p.write_text(p.read_text("cp1252").replace("12345.678", "nan"), "cp1252")
    files["nan_coordinate"] = p

    # 3: arc with extrusion -Z
    d = new()
    d.modelspace().add_arc((10, 0), 5, 0, 90, dxfattribs={"extrusion": (0, 0, -1)})
    files["arc_extrusion_negz"] = OUT / "negz.dxf"
    d.saveas(files["arc_extrusion_negz"])

    # 4: xdata with an unregistered APPID, plus a registered one; 4b: > 16 KB xdata
    d = new()
    d.appids.add("REGD")
    ln = d.modelspace().add_line((0, 0), (10, 0))
    ln.set_xdata("REGD", [(1000, "kept?")])
    ln.set_xdata("NOTREG", [(1000, "dropped?")])
    files["xdata_unregistered_appid"] = OUT / "xdata.dxf"
    d.saveas(files["xdata_unregistered_appid"])
    d = new()
    d.appids.add("BIG")
    ln = d.modelspace().add_line((0, 0), (10, 0))
    ln.set_xdata("BIG", [(1000, "x" * 250)] * 80)  # ~20 KB
    files["xdata_over_16kb"] = OUT / "bigx.dxf"
    d.saveas(files["xdata_over_16kb"])

    # 5: non-normalised arc angles
    d = new()
    d.modelspace().add_arc((0, 0), 10, -90, 450)
    files["arc_angles_-90_450"] = OUT / "angles.dxf"
    d.saveas(files["arc_angles_-90_450"])
    return files


def sysvars() -> dict:
    names = ["MIRRTEXT", "FILLETRAD", "TRIMMODE", "TRIMEXTENDMODE", "ARRAYASSOCIATIVITY", "OFFSETGAPTYPE",
             "CHAMFERA", "CHAMFERB", "CHAMMODE", "INSUNITS", "MEASUREMENT", "DIMASSOC", "ANGBASE", "ANGDIR",
             "LUNITS", "OSMODE", "SECURELOAD", "ACADVER", "DWGNAME"]
    r = run_lisp("sysvars", "\n".join(f'(out "{n}" (getvar "{n}"))' for n in names))
    return dict(r.pairs)


def main() -> dict:
    res = {"sysvars_fresh_drawing_acadiso_dwt": sysvars(), "cases": {}}
    for name, f in make_inputs().items():
        r = run_lisp("blocked_" + name, '(command "_.DXFIN" "%DIR%/in.dxf")\n' + DUMP, files={"in.dxf": f})
        seg = r.log[r.log.find('"_.AUDIT"'):] if '"_.AUDIT"' in r.log else ""
        audit = [l.strip() for l in seg.splitlines() if ("错误" in l or "无效" in l or "重复" in l) and l.strip()]
        imp = r.log[r.log.find("DXFIN"):r.log.find('"_.AUDIT"')] if "DXFIN" in r.log else ""
        import_msgs = [l.strip() for l in imp.splitlines() if any(k in l for k in ("错误", "无效", "无法", "拒绝", "Error"))]
        back = {}
        out = r.dir / "acad_out.dxf"
        if out.is_file():
            try:
                bd = ezdxf.readfile(out)
                back = {"entities": [(e.dxftype(), {k: str(v) for k, v in e.dxf.all_existing_dxf_attribs().items()
                                                   if k in ("radius", "start_angle", "end_angle", "extrusion", "center",
                                                            "start", "end", "actual_measurement")},
                                      [a for a in ("REGD", "NOTREG", "BIG") if e.has_xdata(a)])
                                     for e in bd.modelspace()],
                        "appids": [a.dxf.name for a in bd.appids]}
                for e in bd.modelspace():
                    if e.dxftype() == "DIMENSION":
                        blk = bd.blocks.get(e.dxf.geometry)
                        xs = [round(x.dxf.end.x, 6) for x in blk if x.dxftype() == "LINE"] if blk else []
                        back.setdefault("dimension_block_line_ends_x", []).append(sorted(set(xs)))
            except Exception as exc:  # noqa: BLE001 - report whatever happened
                back = {"error": repr(exc)}
        res["cases"][name] = {"autocad_entities": r.all("ent"), "nent": r.get("nent"), "import_messages": import_msgs[:10],
                              "audit": audit[:10], "dxfout_reread": back, "seconds": r.seconds}
        print(name, json.dumps(res["cases"][name], ensure_ascii=False)[:900])
    return res


if __name__ == "__main__":
    out = main()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "exp_blocked_items.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), "utf-8")
    print(json.dumps(out["sysvars_fresh_drawing_acadiso_dwt"], ensure_ascii=False))
