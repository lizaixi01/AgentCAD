"""Rerun a pair after an infrastructure interruption, preserving the original evidence."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

source = Path(__file__).with_name("run.py")
spec = importlib.util.spec_from_file_location("pro_comparison_run", source)
bench = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(bench)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pro", type=Path, required=True)
    parser.add_argument("--task", choices=sorted(bench.MAKERS), required=True)
    parser.add_argument("--rep", type=int, required=True)
    parser.add_argument("--timeout-sec", type=int, default=360)
    args = parser.parse_args()
    if args.rep < 1 or args.timeout_sec < 1:
        parser.error("--rep and --timeout-sec must be positive")
    previous, out, pro = args.source.resolve(), args.out.resolve(), args.pro.resolve()
    bench.SESSION_TIMEOUT_SECONDS = args.timeout_sec
    manifest = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    fixture = previous / "fixtures" / (args.task + ".dxf")
    if bench.sha(fixture) != manifest["fixtures"][args.task]:
        raise RuntimeError("Original fixture no longer matches its manifest")
    if bench.version(bench.REPO) != manifest["agentcad_commit"] or bench.version(pro) != manifest["pro_commit"]:
        raise RuntimeError("A repository revision changed since the interrupted run")
    out.mkdir(parents=True, exist_ok=False)
    (out / "fixtures").mkdir()
    shutil.copyfile(fixture, out / "fixtures" / fixture.name)
    manifest["retry"] = {"task": args.task, "rep": args.rep, "both_arms": True, "session_timeout_seconds": args.timeout_sec}
    manifest["tasks"] = [args.task]
    manifest["fixtures"] = {args.task: manifest["fixtures"][args.task]}
    manifest["repetitions"] = 1
    check = "import importlib.util; print(int(bool(importlib.util.find_spec('PIL')) and bool(importlib.util.find_spec('matplotlib'))))"
    manifest["pro_config"]["png_renderer_available"] = subprocess.check_output(
        [str(pro / ".venv" / "Scripts" / "python.exe"), "-c", check], text=True, timeout=30
    ).strip() == "1"
    bench.write_json(out / "manifest.json", manifest)
    bench.event(out, {"event": "pair_started", "task": args.task, "rep": args.rep, "retry": True})
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(bench.run_unit, out, pro, args.task, args.rep, arm) for arm in ("A", "B")]
        for future in futures:
            future.result()
    bench.grade(out)
    bench.event(out, {"event": "pair_finished", "task": args.task, "rep": args.rep, "retry": True})


if __name__ == "__main__":
    main()
