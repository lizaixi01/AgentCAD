"""Compare Claude Code arm-A runs across versions: per task median minutes, cost, input tokens, tool errors and
tool-result characters (what the AgentCAD tools put into the context).

    python examples/trials/compare_cc_runs.py v1=runs_cc/v1,hard/runs_cc/v1/A v2=... v3=runs_cc,hard/runs_cc/A

Paths are relative to examples/trials. Times come from each session's own result event (duration_ms); an H1 run
is the sum of its five rounds. T1-T6 rows average the six tasks; H rows give the median time and mean costs.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from summarize_run import summarize

HERE = Path(__file__).resolve().parent


def session(path: Path) -> dict:
    out = {"seconds": 0.0, "cost": 0.0, "input": 0, "output": 0, "errors": 0, "calls": 0, "result_chars": 0}
    names = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            u = ev.get("usage") or {}
            out["seconds"] = ev.get("duration_ms", 0) / 1000
            out["cost"] = ev.get("total_cost_usd", 0.0)
            out["input"] = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                            + u.get("cache_creation_input_tokens", 0))
            out["output"] = u.get("output_tokens", 0)
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if c.get("type") == "tool_use":
                names[c["id"]] = c["name"]
                out["calls"] += 1
            elif c.get("type") == "tool_result":
                body = c.get("content")
                text = body if isinstance(body, str) else "".join(x.get("text", "") for x in body or [])
                out["result_chars"] += len(text)
    out["errors"] = summarize(path)["n_errors"]  # same error count as the earlier reports
    return out


def runs(dirs: list[Path]) -> dict[str, list[dict]]:
    """task -> list of runs (an H1 run merges its rounds)."""
    by: dict[str, dict[str, dict]] = defaultdict(dict)
    for d in dirs:
        for f in sorted(d.glob("*.jsonl")):
            m = re.match(r"(T\d|H\d)(?:_r(\d))?", f.name)
            if not m:
                continue
            task, key = ("T", f.stem) if m.group(1).startswith("T") else (m.group(1), m.group(2))
            s = session(f)
            acc = by[task].setdefault(key, defaultdict(float))
            for k, v in s.items():
                acc[k] += v
    return {t: list(v.values()) for t, v in by.items()}


def main() -> None:
    versions = {}
    for arg in sys.argv[1:]:
        name, paths = arg.split("=", 1)
        versions[name] = runs([HERE / p for p in paths.split(",")])
    tasks = ["T", "H1", "H2", "H3", "H4", "H5", "H6"]
    cols = [("n", None), ("min", "seconds"), ("$", "cost"), ("input k", "input"), ("errors", "errors"),
            ("result kchars", "result_chars")]
    print("task  version  " + "  ".join(f"{c:>13s}" for c, _ in cols))
    for t in tasks:
        for name, data in versions.items():
            rs = data.get(t, [])
            if not rs:
                continue
            vals = []
            for c, k in cols:
                if k is None:
                    vals.append(f"{len(rs):13d}")
                    continue
                xs = [r[k] for r in rs]
                if k == "seconds" and t == "T":  # six different tasks, one run each: the earlier reports average
                    vals.append(f"{statistics.mean(xs) / 60:9.1f} avg")
                elif k == "seconds":
                    vals.append(f"{statistics.median(xs) / 60:9.1f} med")
                elif k == "cost":
                    vals.append(f"{statistics.mean(xs):13.2f}")
                elif k in ("input", "result_chars"):
                    vals.append(f"{statistics.mean(xs) / 1000:13.0f}")
                else:
                    vals.append(f"{statistics.mean(xs):13.1f}")
            print(f"{t:5s} {name:8s} " + "  ".join(vals))


if __name__ == "__main__":
    main()
