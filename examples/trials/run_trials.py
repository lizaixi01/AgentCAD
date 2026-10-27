"""Run classic drafting tasks through a real external agent (Codex CLI) that can only use the AgentCAD MCP server.

Usage:  python examples/trials/run_trials.py [T1 T2 ...] [--jobs 3] [--effort high]

Each task gets a fresh workspace examples/trials/ws/<task>/ (the MCP server's AGENTCAD_ROOT). Codex runs with
`-s read-only`, so it cannot write files through the shell; every change has to go through MCP tools.
Raw event streams are kept in examples/trials/runs/<task>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
SAMPLE_DWG = Path(r"D:\Apps\AutoCAD\AutoCAD 2027\Sample\Mechanical Sample\Mechanical - Multileaders.dwg")


def setup(task: str, ws: Path) -> None:
    """Task-specific input files, made without the agent."""
    if task.startswith("T6"):
        # A flange drawn "by someone else": plain operations, no semantic tags.
        sys.path.insert(0, str(REPO / "src"))
        from agentcad.policy import Policy
        from agentcad.service import Runtime
        rt = Runtime(Policy(root=str(ws)))
        rt.create_drawing("flange.dxf", units="mm")
        ops = [
            {"op": "add_circle", "center": [0, 0], "diameter": 150, "layer": "OUTLINE"},
            {"op": "add_circle", "center": [0, 0], "diameter": 60, "layer": "OUTLINE"},
            {"op": "add_circle", "center": [0, 0], "diameter": 110, "layer": "CENTER", "linetype": "CENTER"},
            {"op": "add_line", "start": [-85, 0], "end": [85, 0], "layer": "CENTER", "linetype": "CENTER"},
            {"op": "add_line", "start": [0, -85], "end": [0, 85], "layer": "CENTER", "linetype": "CENTER"},
            {"op": "add_circle", "center": [0, 55], "diameter": 12, "layer": "HOLES"},
            {"op": "array_polar", "target": "$5", "center": [0, 0], "count": 6},
            {"op": "add_diameter_dim", "target": "$0", "angle": 30, "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "$1", "angle": 210, "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "$5", "angle": 45, "text": "6×Ø12", "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "$2", "angle": 150, "layer": "DIM"},
        ]
        r = rt.apply_operations("flange.dxf", ops)
        assert r["ok"], r
        # Hide the history so the agent sees only the file, like a drawing received from elsewhere.
        shutil.rmtree(ws / ".agentcad")
    if task.startswith("T7"):
        shutil.copyfile(SAMPLE_DWG, ws / "sample.dwg")


def run(task: str, effort: str) -> dict:
    prompt = (HERE / "tasks" / "_preamble.md").read_text(encoding="utf-8") + \
        (HERE / "tasks" / f"{task}.md").read_text(encoding="utf-8")
    ws = HERE / "ws" / task
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    setup(task, ws)
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    root = ws.as_posix()
    cmd = [
        "codex", "exec", "--skip-git-repo-check", "-s", "read-only", "--json",
        "-C", root,
        "-c", f'model_reasoning_effort="{effort}"',
        "-c", f'mcp_servers.agentcad.command="{PY.as_posix()}"',
        "-c", 'mcp_servers.agentcad.args=["-m","agentcad.mcp_server"]',
        "-c", f'mcp_servers.agentcad.env={{AGENTCAD_ROOT="{root}"}}',
        "-c", "mcp_servers.agentcad.default_tools_approval_mode=\"approve\"",
        "-c", "mcp_servers.agentcad.tool_timeout_sec=300",
        "-",
    ]
    t0 = time.time()
    with open(runs / f"{task}.jsonl", "wb") as out, open(runs / f"{task}.stderr.log", "wb") as err:
        p = subprocess.run(cmd, input=prompt.encode("utf-8"), stdout=out, stderr=err,
                           shell=False, timeout=3600)
    return {"task": task, "exit": p.returncode, "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="*")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--effort", default="high")
    a = ap.parse_args()
    names = a.tasks or sorted(p.stem for p in (HERE / "tasks").glob("T*.md"))
    names = [n for t in names for n in sorted(p.stem for p in (HERE / "tasks").glob(f"{t}*.md"))]
    with ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(lambda t: run(t, a.effort), names):
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
