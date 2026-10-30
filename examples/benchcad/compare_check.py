"""Check the reference comparison's score against BenchCAD's graded voxel IoU, offline, on every submitted part.

    <FreeCAD python> -I examples/benchcad/compare_check.py render [--jobs 8]   renders (FreeCAD's own interpreter)
    python examples/benchcad/compare_check.py score [--old <commit>]           scores and metrics (AgentCAD's venv)

``render`` draws each submission.step of every run in runs/ (and each task's reference part) from the four
Vision2Code cameras, with the renderer export_drawing(..., reference=...) uses: the image, the silhouette and the
seam lines, at the reference's cell size. They go to a cache (BENCHCAD_COMPARE_CACHE, default
<data>/compare_cache), one .npz per part; a part that takes longer than 10 minutes is skipped.
``score`` compares them with the task's composite.png twice: with this checkout's compare.py and with the one at
``--old`` (default 945e6c6, before the comparison looked inside the outline), and writes compare_check.json. Metrics:
how often two parts of the same task whose grades differ by 0.1 or more are ranked the grader's way (with a
bootstrap interval over tasks for the difference), the correlation with the grade, how many parts score 0.9 or
more although graded below 0.7, and what each task's reference part scores against its own picture.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import types
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BENCHCAD_DATA", r"D:\Projects\bench-data"))
WS = Path(os.environ.get("BENCHCAD_WS", r"D:\Projects\bench-ws"))
CACHE = Path(os.environ.get("BENCHCAD_COMPARE_CACHE", DATA / "compare_cache"))
VIEWS = [[-1, -1, -1], [1, 1, 1], [1, -1, 1], [-1, 1, -1]]
NAMES = ["[-1,-1,-1]", "[1,1,1]", "[1,-1,1]", "[-1,1,-1]"]
SIZE = 262  # a 524 px composite has 262 px cells (4 px gutters round 256 px views)


# --- render: runs under FreeCAD's interpreter ------------------------------------------------------------------

def render_one(step: str, out: str) -> None:
    import importlib.util

    import numpy as np
    spec = importlib.util.spec_from_file_location("fcr", HERE.parents[1] / "src" / "agentcad" / "part" / "_fc_runner.py")
    fcr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fcr)
    import Part
    sh = Part.read(step)
    arrays = {}
    for i, v in enumerate(VIEWS):  # as action_render does for a comparison
        _, d = fcr._view(v, "v")
        img, mask, seams = fcr.render_view(sh, d, SIZE, "view", with_mask=True)
        arrays[f"img{i}"] = np.clip(fcr._downsample(img, 2), 0, 255).astype("uint8")
        arrays[f"mask{i}"] = mask.astype(float).reshape(SIZE, 2, SIZE, 2).mean(axis=(1, 3)) >= 0.5
        arrays[f"seam{i}"] = seams.reshape(SIZE, 2, SIZE, 2).any(axis=(1, 3))
    tmp = Path(out).with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(out)


def parts() -> list[tuple[str, str, Path]]:
    """(label, task id, STEP) of every submission in runs/, plus each task's reference part (label 'gt')."""
    out = [("gt", t.name, t / "gt" / "gt.step") for t in sorted((DATA / "v2c").iterdir()) if (t / "gt").is_dir()]
    for scores in sorted(HERE.glob("runs/*/v2c.scores.jsonl")):
        label = scores.parent.name
        for line in open(scores, encoding="utf-8"):
            tid = json.loads(line)["id"]
            step = WS / label / "v2c" / tid / "submission.step"
            if step.is_file() and step.stat().st_size:
                out.append((label, tid, step))
    return out


def render(jobs: int) -> None:
    todo = [(label, tid, step) for label, tid, step in parts() if not (CACHE / label / f"{tid}.npz").exists()]
    print(len(todo), "parts to render", flush=True)

    def one(p):
        label, tid, step = p
        (CACHE / label).mkdir(parents=True, exist_ok=True)
        try:  # one FreeCAD process per part: a part that never finishes only costs its own time
            r = subprocess.run([sys.executable, "-I", __file__, "render-one", str(step), str(CACHE / label / f"{tid}.npz")],
                               capture_output=True, text=True, timeout=600)
            return f"{label}/{tid}: " + ("ok" if r.returncode == 0 else r.stderr.strip()[-200:])
        except subprocess.TimeoutExpired:
            return f"{label}/{tid}: timeout"

    with ThreadPoolExecutor(jobs) as ex:
        for i, msg in enumerate(ex.map(one, todo)):
            if not msg.endswith("ok") or i % 100 == 0:
                print(i, msg, flush=True)


# --- score: runs in AgentCAD's venv ----------------------------------------------------------------------------

def _old_compare(commit: str):
    src = subprocess.run(["git", "-C", str(HERE), "show", f"{commit}:src/agentcad/part/compare.py"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    mod = types.ModuleType("old_compare")
    exec(compile(src.replace("from ..errors import", "from agentcad.errors import"), "old_compare.py", "exec"),
         mod.__dict__)
    return mod


def _score_one(args) -> dict:
    import numpy as np

    from agentcad.part import compare
    label, tid, graded, old_commit = args
    old = _old_compare(old_commit)
    with np.load(CACHE / label / f"{tid}.npz") as z:
        renders = [(z[f"img{i}"], z[f"mask{i}"], z[f"seam{i}"]) for i in range(4)]
    cells = compare.load_reference(DATA / "v2c" / tid / "input" / "composite.png", 4)
    o = old.compare_views(cells, NAMES, [r[:2] for r in renders])[0]
    n = compare.compare_views(cells, NAMES, renders)[0]

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 4) if xs else 0.0
    return {"label": label, "id": tid, "graded": graded, "old": mean([v["iou"] for v in o]),
            "score": mean([v["score"] for v in n]), "outline": mean([v["outline"] for v in n]),
            "edges": mean([v["edges"] for v in n])}


def _ranked(rows: list[dict], key: str) -> dict[str, tuple[float, int]]:
    """Per task: (pairs ranked the grader's way, ties counting half; pairs) over pairs graded 0.1 or more apart."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    out = {}
    for tid, rs in by.items():
        ok, n = 0.0, 0
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                dy = a["graded"] - b["graded"]
                if abs(dy) >= 0.1:
                    ds = a[key] - b[key]
                    n += 1
                    ok += 1.0 if ds * dy > 0 else 0.5 if ds == 0 else 0.0
        if n:
            out[tid] = (ok, n)
    return out


def metrics(rows: list[dict]) -> dict:
    import numpy as np
    sub = [r for r in rows if r["label"] != "gt"]
    gt = [r for r in rows if r["label"] == "gt"]
    y = np.array([r["graded"] for r in sub])
    out = {"parts": len(sub), "tasks": len({r["id"] for r in sub}), "reference_parts": len(gt)}
    for key in ("old", "score", "outline", "edges"):
        s = np.array([r[key] for r in sub])
        ranked = _ranked(sub, key)
        hi = s >= 0.9
        g = np.array([r[key] for r in gt])
        out[key] = {"same_task_pairs_ranked": round(sum(a for a, _ in ranked.values()) / sum(n for _, n in ranked.values()), 4),
                    "pairs": sum(n for _, n in ranked.values()),
                    "pearson": round(float(np.corrcoef(y, s)[0, 1]), 3),
                    "score_ge_0_9": int(hi.sum()), "score_ge_0_9_graded_lt_0_7": int((hi & (y < 0.7)).sum()),
                    "reference_part_mean": round(float(g.mean()), 4) if len(g) else None,
                    "reference_part_p10": round(float(np.percentile(g, 10)), 4) if len(g) else None}
    a, b = _ranked(sub, "score"), _ranked(sub, "old")
    tids = sorted(set(a) & set(b))
    rng = np.random.default_rng(0)
    diffs = []
    for _ in range(4000):
        pick = [tids[i] for i in rng.integers(0, len(tids), len(tids))]
        diffs.append(sum(a[t][0] for t in pick) / sum(a[t][1] for t in pick)
                     - sum(b[t][0] for t in pick) / sum(b[t][1] for t in pick))
    out["ranked_difference_ci95"] = [round(float(np.percentile(diffs, 2.5)), 4),
                                     round(float(np.percentile(diffs, 97.5)), 4)]
    return out


def score(old_commit: str, jobs: int) -> None:
    graded = {}
    for f in HERE.glob("runs/*/v2c.scores.jsonl"):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            graded[(f.parent.name, r["id"])] = float(r["score"] or 0.0)
    todo = [(label, tid, 1.0 if label == "gt" else graded[(label, tid)], old_commit) for label, tid, _ in parts()
            if (CACHE / label / f"{tid}.npz").exists()]
    with ProcessPoolExecutor(jobs) as ex:
        rows = list(ex.map(_score_one, todo, chunksize=4))
    out = {"old": old_commit, "metrics": metrics(rows), "parts": rows}
    (HERE / "compare_check.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["metrics"], indent=1))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "render-one":
        render_one(sys.argv[2], sys.argv[3])
        sys.exit()
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["render", "score"])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--old", default="945e6c6")
    a = ap.parse_args()
    if a.mode == "render":
        render(a.jobs)
    else:
        score(a.old, a.jobs)
