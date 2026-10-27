"""AutoCAD AUDIT + PNG render of both comparison arms (run from PowerShell/cmd; launches accoreconsole).

    python examples/trials/acad_compare.py A_root B_root

Writes examples/trials/png_compare/{A,B}/<task>.png and examples/trials/acad_compare.json.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
from agentcad.backends import autocad  # noqa: E402
from grade import OUTPUT  # noqa: E402
from render_png import render  # noqa: E402

TASKS = ["T1_flange", "T2_slot_plate", "T3_shaft", "T4_frame", "T5_room", "T6_flange_revise"]


def main() -> None:
    roots = {"A": Path(sys.argv[1]), "B": Path(sys.argv[2])}
    jobs = Path(tempfile.mkdtemp(prefix="acadcmp"))
    out: dict = {}
    for arm, root in roots.items():
        for t in TASKS:
            f = root / t / OUTPUT[t[:2]]
            if not f.is_file():
                out[f"{arm}/{t}"] = {"exists": False}
                continue
            a = autocad.audit_dxf(f, jobs)
            png = render(f, HERE / "png_compare" / arm)
            if png is not None:
                png.replace(png.with_name(f"{t}.png"))
            out[f"{arm}/{t}"] = {k: a.get(k) for k in ("import_rejected", "audit_errors", "messages",
                                                       "entities_seen_by_autocad", "insunits")} | {
                "passed": not a.get("import_rejected") and a.get("audit_errors") == 0, "png": png is not None}
            print(arm, t, out[f"{arm}/{t}"], flush=True)
    (HERE / "acad_compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
