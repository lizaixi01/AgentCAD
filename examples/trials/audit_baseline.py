"""For sample drawings whose AutoCAD AUDIT failed after the survey's edit: audit a fresh import of the same DWG
(no edit) to tell pre-existing problems from ones the runtime introduced."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from agentcad.policy import Policy  # noqa: E402
from agentcad.service import Runtime  # noqa: E402

rows = json.loads((HERE / "real_dwg_survey.json").read_text(encoding="utf-8"))
rt = Runtime(Policy(root=str(HERE / "ws" / "real_dwg")))
for i, r in enumerate(rows):
    a = r.get("acad_audit")
    if not isinstance(a, dict) or a.get("passed"):
        continue
    name = f"s{i:02d}"
    imp = rt.import_drawing(f"{name}.dwg", f"{name}_base.dxf", overwrite=True)
    base = rt.autocad_audit(f"{name}_base.dxf") if imp["ok"] else imp
    after = rt.autocad_audit(f"{name}.dxf")
    r["audit_baseline"] = {k: base.get(k) for k in ("passed", "audit_errors", "messages")}
    r["audit_after_edit"] = {k: after.get(k) for k in ("passed", "audit_errors", "messages")}
    print(json.dumps({"sample": r["sample"], "baseline": r["audit_baseline"], "after": r["audit_after_edit"]},
                     ensure_ascii=False)[:900], flush=True)
(HERE / "real_dwg_survey.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
