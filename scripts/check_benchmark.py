"""Fail a release lane unless the complete, unchanged v8 task set passed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "examples/autocad_benchmark/results/2026-10-30-v8/reference.json"


def check(report: dict) -> None:
    reference = json.loads(REFERENCE.read_text("utf-8"))
    expected = {r["task_id"] for r in reference["results"]}
    results = report["results"]
    if len(expected) != 31 or len(results) != 31 or {r["task_id"] for r in results} != expected:
        raise ValueError("Release gate requires exactly the 31 original v8 tasks")
    if any(r["status"] != "pass" or r["score"] != 100 for r in results):
        raise ValueError("Every v8 task must pass at 100; partial/blocked/failed tasks cannot release")
    summary = report["summary"]
    if any(summary[k] != reference["summary"][k] for k in reference["summary"]):
        raise ValueError("v8 summary differs from the complete 31/31 result")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        check(json.loads(args.report.read_text("utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"BENCHMARK_GATE_FAILED: {exc}")
        return 1
    print("v8 release gate: 31/31 passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
