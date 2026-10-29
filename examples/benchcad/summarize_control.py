"""Summarize the Vision2Code control runs into control_summary.json (the numbers README.md cites).

    python examples/benchcad/summarize_control.py

Per run label: mean / median IoU, counts at IoU >= 0.9 and < 0.5, median seconds, median input tokens, Claude's
cost, and AgentCAD tool calls that failed. Contrasts are paired by task, with a 95% bootstrap interval (4000
resamples, seed 0).
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "trials"))
from summarize_run import summarize  # noqa: E402

LABELS = ["claude-mcp-medium", "claude-mcp-opt-medium", "claude-mcp-opt2-medium", "claude-code-medium",
          "codex-mcp-medium", "codex-mcp-opt-medium", "codex-code-medium"]
CONTRASTS = [("claude-mcp-opt2-medium", "claude-mcp-medium"), ("claude-mcp-opt2-medium", "claude-code-medium"),
             ("claude-mcp-medium", "claude-code-medium"), ("claude-mcp-opt-medium", "claude-code-medium"),
             ("codex-mcp-opt-medium", "codex-mcp-medium"),
             ("codex-mcp-opt-medium", "codex-code-medium"), ("codex-mcp-medium", "codex-code-medium")]


def scores(label: str) -> dict[str, float]:
    return {(r := json.loads(x))["id"]: r["score"] for x in open(HERE / "runs" / label / "v2c.scores.jsonl")}


def run(label: str) -> dict:
    v = list(scores(label).values())
    last = {}
    for x in open(HERE / "runs" / label / "runs.jsonl"):
        r = json.loads(x)
        last[r["id"]] = r
    tokens, cost, calls, failed = [], 0.0, 0, 0
    for f in sorted((HERE / "runs" / label / "v2c").glob("*.jsonl")):
        s = summarize(f)
        tokens.append((s.get("usage") or {}).get("input_tokens", 0))
        cost += s.get("cost_usd") or 0
        own = [c for c in s["calls"] if not str(c.get("tool", "")).startswith(("FILE:", "SHELL"))]
        calls += len(own)
        failed += sum(1 for c in own if c.get("ok") is False)
    return {"n": len(v), "submitted": sum(r["submitted"] for r in last.values()),
            "iou_mean": round(st.mean(v), 4), "iou_median": round(st.median(v), 4),
            "iou_ge_0_9": sum(x >= 0.9 for x in v), "iou_lt_0_5": sum(x < 0.5 for x in v),
            "seconds_median": round(st.median(r["seconds"] for r in last.values()), 1),
            "input_tokens_median": int(st.median(tokens)), "cost_usd": round(cost, 2) if cost else None,
            "tool_calls": calls, "tool_calls_failed": failed,
            "leak_suspect": sum(r["leak_suspect"] for r in last.values())}


def contrast(a: str, b: str) -> dict:
    sa, sb = scores(a), scores(b)
    d = [sa[i] - sb[i] for i in sa]
    rnd = random.Random(0)
    boots = sorted(st.mean(rnd.choice(d) for _ in d) for _ in range(4000))
    return {"a": a, "b": b, "mean_diff": round(st.mean(d), 4), "ci95": [round(boots[100], 4), round(boots[3899], 4)],
            "a_better": sum(x > 0.02 for x in d), "b_better": sum(x < -0.02 for x in d)}


if __name__ == "__main__":
    out = {"runs": {label: run(label) for label in LABELS}, "contrasts": [contrast(a, b) for a, b in CONTRASTS]}
    (HERE / "control_summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for label, r in out["runs"].items():
        print(f"{label:24} {r}")
    for c in out["contrasts"]:
        print(c)
