"""Score the agents' submissions with BenchCAD's own scorers. Run with the matching BenchCAD interpreter:

    <BenchCAD-main>/.venv/Scripts/python examples/benchcad/score.py v2c --agent claude
    <benchcad-2-main>/.venv/bin/python   examples/benchcad/score.py t1  --agent claude   (Linux / WSL only: its
                                                                                      mesh worker uses select())

v2c: benchcad_core.scoring.iou.iou_step_vs_step(submission, gt), voxel IoU at 64^3 on normalized shapes.
t1:  envs.common.score_case.score_case(case_dir, submission), the part_v1 score verify_case.py prints.
A task without submission.step scores 0, as an episode that never submits does in BenchCAD.
Writes examples/benchcad/runs/<agent>/<suite>.scores.jsonl and prints the mean.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BENCHCAD_DATA", r"D:\Projects\bench-data"))
WS = Path(os.environ.get("BENCHCAD_WS", r"D:\Projects\bench-ws"))
SRC = Path(os.environ.get("BENCHCAD_SRC", r"D:\Projects\bench-src"))


def scorer(suite: str):
    if suite == "v2c":
        sys.path.insert(0, str(SRC / "BenchCAD-main"))
        from benchcad_core.scoring.iou import iou_step_vs_step
        return lambda task, sub: {"score": iou_step_vs_step(sub, task / "gt" / "gt.step")}
    sys.path.insert(0, str(SRC / "benchcad-2-main"))
    from envs.common.score_case import score_case

    def t1(task: Path, sub: Path) -> dict:
        case = Path(json.loads((task / "task.json").read_text(encoding="utf-8"))["case_dir"])
        r = score_case(case, sub)
        return {"score": float(r["score"]), "detail": {k: v for k, v in r.items() if k != "score"}}
    return t1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["v2c", "t1"])
    ap.add_argument("--agent", choices=["claude", "codex"], required=True)
    a = ap.parse_args()
    score = scorer(a.suite)
    tasks = sorted(p for p in (DATA / a.suite).iterdir() if (p / "task.json").exists())
    rows = []
    for task in tasks:
        sub = WS / a.agent / a.suite / task.name / "submission.step"
        if not (WS / a.agent / a.suite / task.name).exists():
            continue  # not run
        row = {"id": task.name, "submitted": sub.exists(), "score": 0.0}
        if sub.exists():
            try:
                row.update(score(task, sub))
            except Exception as exc:  # noqa: BLE001 - a submission the scorer cannot read scores 0
                row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        rows.append(row)
    out = HERE / "runs" / a.agent / f"{a.suite}.scores.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")
    if rows:
        s = [r["score"] for r in rows]
        print(f"{a.agent} {a.suite}: n={len(rows)} mean={statistics.mean(s):.4f} "
              f"submitted={sum(r['submitted'] for r in rows)}/{len(rows)} -> {out}")


if __name__ == "__main__":
    main()
