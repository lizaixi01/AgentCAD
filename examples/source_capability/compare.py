"""Compare two immutable product snapshots under one interpreter/dependency graph.

No model, network or native CAD calls. Both versions must produce identical line
geometry through the public Runtime and a reopened exported DXF. Times are local
version regression observations, not a cross-product speed ranking.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from zipfile import ZipFile


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", "utf-8")


def worker(source: Path, folder: Path, count: int) -> dict:
    sys.path.insert(0, str(source))
    import agentcad
    import ezdxf
    from agentcad.policy import Policy
    from agentcad.service import Runtime

    assert Path(agentcad.__file__).resolve().is_relative_to(source.resolve())
    folder.mkdir(parents=True, exist_ok=False)
    runtime = Runtime(Policy(root=folder, max_ops_per_batch=10000))
    operations = [{"op": "add_line", "start": [i * 2, 0], "end": [i * 2 + 1, 1]} for i in range(count)]
    started = time.perf_counter()
    created = runtime.apply_operations("lines.dxf", operations, create={"units": "mm"})
    creation = time.perf_counter() - started
    assert created["ok"] and created["validation"]["passed"], created
    started = time.perf_counter()
    exported = runtime.export_drawing("lines.dxf", "reopened.dxf", "dxf")
    assert exported["ok"], exported
    drawing = ezdxf.readfile(folder / "reopened.dxf")
    geometry = [(list(e.dxf.start), list(e.dxf.end)) for e in drawing.modelspace() if e.dxftype() == "LINE"]
    expected = [([i * 2.0, 0.0, 0.0], [i * 2.0 + 1, 1.0, 0.0]) for i in range(count)]
    assert geometry == expected and len(drawing.modelspace()) == count
    assert not drawing.audit().errors and drawing.header["$INSUNITS"] == 4
    roundtrip = time.perf_counter() - started
    return {"count": count, "passed": True, "create_s": creation, "export_reopen_check_s": roundtrip,
            "total_s": creation + roundtrip, "geometry_sha256": hashlib.sha256(json.dumps(geometry).encode()).hexdigest(),
            "imported_from": str(agentcad.__file__)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--counts", type=int, nargs="+", default=[2000, 10000])
    parser.add_argument("--worker-source", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_source:
        print(json.dumps(worker(args.worker_source, args.out, args.counts[0])))
        return
    if not args.baseline or not args.candidate or args.repeats < 3 or any(n < 1 or n > 10000 for n in args.counts):
        parser.error("Two git refs, >=3 repetitions and counts in 1..10000 required")
    args.out = args.out.absolute()
    args.out.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    def git(*cmd):
        return subprocess.check_output(["git", "-C", str(repo), *cmd])
    snapshots = {}
    for label, ref in (("baseline", args.baseline), ("candidate", args.candidate)):
        sha = git("rev-parse", ref + "^{commit}").decode().strip()
        target = args.out / label
        with ZipFile(BytesIO(git("archive", "--format=zip", sha, "src"))) as archive:
            for name in archive.namelist():
                if not (target / name).resolve().is_relative_to(target.resolve()):
                    raise ValueError("Unsafe archive member")
            archive.extractall(target)
        files = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted((target / "src").rglob("*.py"))}
        snapshots[label] = {"commit": sha, "source_sha256": files}
    report = {"schema_version": 1, "platform": platform.platform(), "python": sys.version,
              "dependencies": {name: importlib.metadata.version(name) for name in ("ezdxf", "mcp", "pypdf", "numpy")},
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "snapshots": snapshots, "warmups_excluded": 1, "repetitions": args.repeats,
              "measurements": [], "summary": [],
              "scope": "Direct Runtime, 2D lines only; includes saved validation and DXF roundtrip; no native CAD, MCP or model latency"}
    env = {**os.environ, "AGENTCAD_VIEWER": "0", "PYTHONUTF8": "1"}
    for count in args.counts:
        for repeat in range(-1, args.repeats):
            # Alternate order to reduce systematic cache/load bias; each process is fresh.
            labels = ["baseline", "candidate"] if repeat % 2 == 0 else ["candidate", "baseline"]
            for label in labels:
                folder = args.out / "runs" / f"{label}-{count}-{repeat}"
                run = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--worker-source",
                                      str(args.out / label / "src"), "--out", str(folder), "--counts", str(count)],
                                     env=env, text=True, encoding="utf-8", capture_output=True, timeout=300)
                (args.out / f"{label}-{count}-{repeat}.log").write_text(run.stdout + run.stderr, "utf-8")
                run.check_returncode()
                result = json.loads(run.stdout)
                report["measurements"].append({"version": label, "repeat": repeat, **result})
                write(args.out / "report.json", report)
                print(f"{label} {count} lines repetition {repeat}: {result['total_s']:.3f}s", flush=True)
        for metric in ("create_s", "export_reopen_check_s", "total_s"):
            values = {label: [r[metric] for r in report["measurements"]
                              if r["version"] == label and r["count"] == count and r["repeat"] >= 0]
                      for label in ("baseline", "candidate")}
            medians = {label: statistics.median(v) for label, v in values.items()}
            report["summary"].append({"count": count, "metric": metric, "median": medians,
                                      "candidate_over_baseline": medians["candidate"] / medians["baseline"]})
    report["correctness_passed"] = all(r["passed"] for r in report["measurements"])
    write(args.out / "report.json", report)


if __name__ == "__main__":
    main()
