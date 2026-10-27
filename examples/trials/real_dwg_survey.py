"""Import every AutoCAD sample DWG through the AgentCAD backend and record what the runtime makes of it.

For each drawing: import (DWG -> DXF via accoreconsole), read_drawing, validate (no requirements), one simple
edit (add a TEXT note), and a DXF re-audit by AutoCAD. Results go to examples/trials/real_dwg_survey.json.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from agentcad.policy import Policy  # noqa: E402
from agentcad.service import Runtime  # noqa: E402

SAMPLES = Path(r"D:\Apps\AutoCAD\AutoCAD 2027\Sample")


def main() -> None:
    ws = HERE / "ws" / "real_dwg"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    rt = Runtime(Policy(root=str(ws)))
    rows = []
    files = sorted(SAMPLES.rglob("*.dwg"))
    for i, src in enumerate(files):
        name = f"s{i:02d}"
        shutil.copyfile(src, ws / f"{name}.dwg")  # ASCII names inside the workspace
        row = {"sample": str(src.relative_to(SAMPLES)), "bytes": src.stat().st_size}
        t0 = time.time()
        r = rt.import_drawing(f"{name}.dwg", f"{name}.dxf")
        row["import_ok"] = r["ok"]
        row["import_s"] = round(time.time() - t0, 1)
        if not r["ok"]:
            row["import_error"] = r["error"]
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            continue
        row["import_validation_passed"] = r["validation"]["passed"]
        d = rt.read_drawing(f"{name}.dxf")
        if d["ok"]:
            row.update(units=d["units"], entities=d["entity_count"], types=d["entity_types"],
                       layers=len(d["layers"]), extents=d["extents"])
        else:
            row["read_error"] = d["error"]
        v = rt.validate_drawing(f"{name}.dxf")
        if v["ok"]:
            issues = v["validation"]["issues"]
            codes: dict[str, int] = {}
            for it in issues:
                key = f'{it["severity"]}:{it["code"]}'
                codes[key] = codes.get(key, 0) + 1
            row["validate_passed"] = v["validation"]["passed"]
            row["issue_codes"] = codes
            row["summary"] = v["validation"]["summary"]
        else:
            row["validate_error"] = v["error"]
        if d.get("ok") and not d.get("extents"):
            row["edit_skipped"] = "no model-space extents"
        elif d.get("ok"):
            (x0, y0), (x1, y1) = d["extents"]
            h = max((y1 - y0) / 100, 1e-3)
            e = rt.apply_operations(f"{name}.dxf", [{"op": "add_text", "text": "AgentCAD note",
                                                     "insert": [x0, y0 - 3 * h], "height": h}])
            row["edit_ok"] = e["ok"]
            if not e["ok"]:
                row["edit_error"] = e["error"]
            else:
                a = rt.autocad_audit(f"{name}.dxf")
                row["acad_audit"] = {k: a.get(k) for k in ("passed", "import_rejected", "audit_errors",
                                                           "entities_seen_by_autocad")} if a["ok"] else a["error"]
                row["entities_after_edit"] = d["entity_count"] + 1
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("sample", "import_ok", "entities", "validate_passed",
                                                   "edit_ok", "acad_audit")}, ensure_ascii=False), flush=True)
    (HERE / "real_dwg_survey.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
