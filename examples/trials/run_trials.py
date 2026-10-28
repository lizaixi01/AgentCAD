"""Run classic drafting tasks through a real external agent (Codex CLI).

Usage:  python examples/trials/run_trials.py [T1 T2 ...] [--jobs 3] [--effort high] [--arm mcp|code]

--arm mcp (default): each task gets a fresh workspace examples/trials/ws/<task>/ (the MCP server's AGENTCAD_ROOT).
  Codex runs with `-s read-only`, so it cannot write files through the shell; every change goes through MCP tools.
  Raw event streams are kept in examples/trials/runs/<task>.jsonl.
--arm code: the comparison arm. Codex writes and runs Python with plain ezdxf (an env without AgentCAD, given by
  --python), in a workspace outside the repository (--code-root) so it cannot find AgentCAD either. Streams go to
  examples/trials/runs_code/<task>.jsonl.
--agent claude: Claude Code instead of Codex (see agents.py); workspaces ws_cc/, logs runs_cc/ and runs_cc_code/.
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
sys.path.insert(0, str(HERE))
from agents import agent_env, command  # noqa: E402

REPO = HERE.parents[1]
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


def run(task: str, effort: str, arm: str = "mcp", code_root: Path | None = None, python: str = "",
        agent: str = "codex") -> dict:
    sfx = "_cc" if agent == "claude" else ""
    pre = "_preamble.md" if arm == "mcp" else "_preamble_code.md"
    prompt = (HERE / "tasks" / pre).read_text(encoding="utf-8").replace("%PYTHON%", python) + \
        (HERE / "tasks" / f"{task}.md").read_text(encoding="utf-8")
    ws = (HERE / f"ws{sfx}" / task) if arm == "mcp" else (code_root / task)
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    setup(task, ws)
    runs = HERE / (f"runs{sfx}" if arm == "mcp" else f"runs{sfx}_code")
    runs.mkdir(exist_ok=True)
    cmd = command(agent, arm, ws.as_posix(), effort, runs / "_mcp", python)
    t0 = time.time()
    with open(runs / f"{task}.jsonl", "wb") as out, open(runs / f"{task}.stderr.log", "wb") as err:
        p = subprocess.run(cmd, input=prompt.encode("utf-8"), stdout=out, stderr=err,
                           shell=False, timeout=3600, cwd=ws, env=agent_env())
    return {"task": task, "arm": arm, "exit": p.returncode, "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="*")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--arm", choices=["mcp", "code"], default="mcp")
    ap.add_argument("--code-root", type=Path, help="Workspace parent for --arm code (outside the repository)")
    ap.add_argument("--python", default="", help="Interpreter with plain ezdxf for --arm code")
    ap.add_argument("--agent", choices=["codex", "claude"], default="codex")
    a = ap.parse_args()
    if a.arm == "code" and (a.code_root is None or not a.python):
        ap.error("--arm code needs --code-root and --python")
    names = a.tasks or sorted(p.stem for p in (HERE / "tasks").glob("T*.md"))
    names = [n for t in names for n in sorted(p.stem for p in (HERE / "tasks").glob(f"{t}*.md"))]
    with ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(lambda t: run(t, a.effort, a.arm, a.code_root, a.python, a.agent), names):
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
