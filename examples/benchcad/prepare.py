"""Prepare BenchCAD tasks for the AgentCAD pilot. Run with BenchCAD's own interpreter (it has cadquery, the
official renderer and the HF client):

    PYTHONUTF8=1 <BenchCAD-main>/.venv/Scripts/python examples/benchcad/prepare.py v2c [--num 100 --seed 42]
    (PYTHONUTF8=1: BenchCAD writes the reference code to a temp file in the locale encoding, GBK on a Chinese
    Windows, which cannot encode some characters in the codes.)
    <benchcad-2-main>/.venv/Scripts/python examples/benchcad/prepare.py t1 --cases <dir with case*/ folders>

Every task becomes <data>/<suite>/<task_id>/ with
    input/   what the agent sees (copied into its workspace)
    gt/      the reference, never copied anywhere the agent can read
    task.json

v2c (Vision2Code): all stems of the public code_gen split are sorted and `--num` are sampled with
random.Random(seed), like BenchCAD's own `--num N --seed S`. The reference STEP is made by executing the record's
code with BenchCAD's exec_cq, and the input is the official 2x2 composite (composite_for_step), so the agent sees
exactly what a BenchCAD model sees.
t1 (BenchCAD 2.0, drawing -> part): each case directory is used as is; input/ holds drawing.png (and tiles / pages),
gt/ is the case itself, which the official verify_case scores against.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path

DATA = Path(os.environ.get("BENCHCAD_DATA", r"D:\Projects\bench-data"))
SRC = Path(os.environ.get("BENCHCAD_SRC", r"D:\Projects\bench-src"))


def prepare_v2c(num: int, seed: int) -> None:
    import pandas as pd
    from huggingface_hub import snapshot_download
    sys.path.insert(0, str(SRC / "BenchCAD-main"))
    from benchcad_core.scoring import exec_cq
    from benchcad_core.scoring.exec_cq import execute_cq_to_step
    from benchcad_core.scoring.views import composite_for_step
    # exec_cq runs the reference code with only POSIX variables (HOME, TMPDIR...). On Windows Python finds the home
    # and temp directories through USERPROFILE / TEMP, so without them every reference fails to build.
    exec_cq._ENV_KEEP = (*exec_cq._ENV_KEEP, "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")

    snap = Path(snapshot_download(repo_id="BenchCAD/BenchCAD", repo_type="dataset",
                                  allow_patterns="code_gen/data/*.parquet", cache_dir=DATA / "hf"))
    shards = sorted((snap / "code_gen" / "data").glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p, columns=["stem", "family", "code"]) for p in shards], ignore_index=True)
    stems = sorted(df["stem"])
    picked = random.Random(seed).sample(stems, num)
    rows = df.set_index("stem")
    out = DATA / "v2c"
    done = 0
    for rid in picked:
        d = out / rid
        if (d / "task.json").exists():
            done += 1
            continue
        try:
            execute_cq_to_step(rows.loc[rid, "code"], d / "gt" / "gt.step")
            composite_for_step(d / "gt" / "gt.step", d / "input" / "composite.png")
        except Exception as exc:  # noqa: BLE001 - a reference that does not build is skipped, as BenchCAD does
            print(f"skip {rid}: {type(exc).__name__}: {exc}")
            shutil.rmtree(d, ignore_errors=True)
            continue
        (d / "task.json").write_text(json.dumps({"suite": "v2c", "id": rid, "family": rows.loc[rid, "family"],
                                                 "seed": seed, "num": num}), encoding="utf-8")
        done += 1
    (out / "selection.json").write_text(json.dumps({"seed": seed, "num": num, "of": len(stems),
                                                    "ids": picked}, indent=1), encoding="utf-8")
    print(f"v2c: {done} of {num} tasks ready under {out}")


def prepare_t1(cases: Path) -> None:
    out = DATA / "t1"
    n = 0
    for case in sorted(p for p in cases.iterdir() if (p / "gt" / "gt.step").exists()):
        d = out / f"{cases.parent.parent.name}-{case.name}" if cases.name == "cases" else out / case.name
        (d / "input").mkdir(parents=True, exist_ok=True)
        for f in (case / "input").iterdir():
            shutil.copy2(f, d / "input" / f.name)
        (d / "task.json").write_text(json.dumps({"suite": "t1", "id": d.name, "case_dir": str(case)}),
                                     encoding="utf-8")
        n += 1
    print(f"t1: {n} cases ready under {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["v2c", "t1"])
    ap.add_argument("--num", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cases", type=Path, help="t1: a directory of BenchCAD 2.0 T1 case folders")
    a = ap.parse_args()
    if a.suite == "v2c":
        prepare_v2c(a.num, a.seed)
    else:
        prepare_t1(a.cases)


if __name__ == "__main__":
    main()
