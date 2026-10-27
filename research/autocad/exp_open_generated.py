"""Experiment A1: does AutoCAD 2027 accept the DXF files AgentCAD generates?

For each file: DXFIN into a fresh drawing, AUDIT, report what AutoCAD sees
(units, entity counts by type, dimension measurements from group 42 as
AutoCAD recomputes it, AGENTCAD xdata tags, the AGENTCAD dictionary), then
write AutoCAD's own DXF (R2018) and DWG for round-trip checks.

    python research/autocad/exp_open_generated.py [file.dxf ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from acad import run_lisp  # noqa: E402

ROOT = HERE.parents[1]
DEFAULT = [ROOT / "examples/output/A_mounting_plate_100x60.dxf", ROOT / "examples/output/B_mounting_plate.dxf",
           ROOT / "examples/output/C_bracket_from_pdf.dxf", ROOT / "examples/output/C_plate_from_zh_md.dxf",
           ROOT / "examples/output/A_mounting_plate_100x60_R12.dxf", ROOT / "examples/agent_codex/ws/bracket.dxf"]

LISP = r'''
(command "_.DXFIN" "%DIR%/in.dxf")
(out "insunits" (getvar "INSUNITS"))
(out "measurement" (getvar "MEASUREMENT"))
(setq ss (ssget "X") i 0 counts '())
(if ss (repeat (sslength ss)
  (setq e (ssname ss i) ed (entget e '("AGENTCAD")) typ (cdr (assoc 0 ed)) i (1+ i))
  (if (assoc typ counts) (setq counts (subst (cons typ (1+ (cdr (assoc typ counts)))) (assoc typ counts) counts))
      (setq counts (cons (cons typ 1) counts)))
  (setq x (assoc -3 ed))
  (if x (out "tag" (strcat (cdr (assoc 5 ed)) " " (cdr (cadr (cadr x))))))
  (if (= typ "DIMENSION") (out "dim" (strcat (cdr (assoc 5 ed)) " " (rtos (cdr (assoc 42 ed)) 2 10))))))
(out "nent" (if ss (sslength ss) 0))
(foreach c counts (out (strcat "count." (car c)) (cdr c)))
(setq d (dictsearch (namedobjdict) "AGENTCAD"))
(out "agentcad_dict" (if d "present" "missing"))
(command "_.AUDIT" "_N")
(out "extmin" (pt2s (getvar "EXTMIN")))
(out "extmax" (pt2s (getvar "EXTMAX")))
(command "_.SAVEAS" "2018" "%DIR%/acad.dwg")
(command "_.DXFOUT" "%DIR%/acad_out.dxf" "_V" "2018" "16")
(out "saved" "yes")
'''


def audit_summary(log: str) -> str:
    keys = ("错误", "error", "Error", "修复", "fixed", "已找到")
    return " | ".join(l.strip() for l in log.splitlines() if any(k in l for k in keys))[:600]


def main(files: list[Path]) -> list[dict]:
    rows = []
    for f in files:
        job = "open_" + f.stem
        r = run_lisp(job, LISP, files={"in.dxf": f})
        row = {"file": str(f.relative_to(ROOT)), "rc": r.rc, "seconds": r.seconds,
               "insunits": r.get("insunits"), "nent": r.get("nent"),
               "counts": {k[6:]: int(v) for k, v in r.pairs if k.startswith("count.")},
               "dims": r.all("dim"), "tags": len(r.all("tag")), "agentcad_dict": r.get("agentcad_dict"),
               "ext": [r.get("extmin"), r.get("extmax")], "saved": r.get("saved"),
               "audit_log": audit_summary(r.log), "job_dir": str(r.dir)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    return rows


if __name__ == "__main__":
    args = [Path(a).resolve() for a in sys.argv[1:]] or DEFAULT
    out = main(args)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "exp_open_generated.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), "utf-8")
