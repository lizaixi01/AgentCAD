"""Run prepared BenchCAD tasks through an external agent that builds the part with AgentCAD.

    python examples/benchcad/run.py v2c --agent claude [--jobs 3] [--effort high] [--ids id1 id2] [--limit N]

Each task gets a fresh workspace <ws>/<agent>/<suite>/<id>/ outside this repository (the MCP server's
AGENTCAD_ROOT) holding only the task's input/ files. The agent can call AgentCAD's MCP tools and look at the input
images (Claude Code: Read, run from the workspace; Codex: the images are attached to the prompt), and nothing
else. It must leave its part in submission.step. The reference stays under <data>, never inside a workspace.
Event streams go to examples/benchcad/runs/<agent>/<suite>/<id>.jsonl; run summaries to runs.jsonl beside them.
Set AGENTCAD_FREECAD for 3D parts (the MCP server inherits it).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "trials"))
from agents import agent_env, command  # noqa: E402

DATA = Path(os.environ.get("BENCHCAD_DATA", r"D:\Projects\bench-data"))
WS = Path(os.environ.get("BENCHCAD_WS", r"D:\Projects\bench-ws"))

V2C_PROMPT = """You are an expert CAD engineer. composite.png in your workspace is a 2x2 composite of 4 diagonal
views of a mechanical part. Build that part as a 3D AgentCAD part.

Views (cameras at, all looking at part center [0.5, 0.5, 0.5]):
- Top-left:     [-1, -1, -1]
- Top-right:    [ 1,  1,  1]
- Bottom-left:  [ 1, -1,  1]
- Bottom-right: [-1,  1, -1]

Renders are normalized: bbox centered at [0.5, 0.5, 0.5], longest side maps to [0,1]. Match orientation exactly:
world XYZ of your part must match world XYZ in the renders. Absolute size is not scored, proportions are.

Use only the AgentCAD tools: create the part with create_drawing("part.FCStd"), build it with apply_operations
(list_operations(category="part") gives the part operations), check it with read_drawing / validate_drawing, and
export it with export_drawing("part.FCStd", "submission.step", "step"). The part must be a single solid.
To compare your part with the target, export_drawing("part.FCStd", "preview.png", "png",
views=[[-1,-1,-1],[1,1,1],[1,-1,1],[-1,1,-1]]) renders the same four camera positions in the same 2x2 order
(a views vector is the camera position); look at it next to composite.png.
submission.step is scored by voxel IoU against the real part when you finish; there is no other output."""

T1_PROMPT = """You are an expert CAD engineer. drawing.png in your workspace is the engineering drawing of one
part, in millimetres, first-angle projection unless its header says third-angle. If the lettering is too small,
the sheet is also there as tiles drawing_tile_r<i>c<j>.png (row i from the top, column j from the left, 10 %
overlap); a further page, when there is one, is drawing_p2.png. Build the part as a 3D AgentCAD part, axis-aligned
to the drawing's views.

Use only the AgentCAD tools: create the part with create_drawing("part.FCStd"), build it with apply_operations
(list_operations(category="part") gives the part operations), check it with read_drawing / validate_drawing, and
export it with export_drawing("part.FCStd", "submission.step", "step"). The part must be a single solid.
export_drawing("part.FCStd", "preview.png", "png", views=["front", "top", "right", "iso"]) renders your part so
you can compare it with the drawing.
submission.step is scored against the real part (volume overlap and topology) when you finish; there is no other
output. Your workspace files: %FILES%"""


# Provider-side failures that say nothing about the agent: the run is repeated instead of scored 0.
TRANSIENT = ("Selected model is at capacity", "overloaded_error", "rate_limit", "Connection dropped",
             "ECONNRESET", "503 Service Unavailable")


def run_one(task: Path, agent: str, effort: str, timeout: int, attempts: int = 3) -> dict:
    for attempt in range(1, attempts + 1):
        row = _run_once(task, agent, effort, timeout)
        if not row["transient"] or attempt == attempts:
            row["attempt"] = attempt
            break
        time.sleep(60 * attempt)
    logs = HERE / "runs" / agent / row["suite"]
    with open(logs.parent / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
    return row


def _run_once(task: Path, agent: str, effort: str, timeout: int) -> dict:
    meta = json.loads((task / "task.json").read_text(encoding="utf-8"))
    suite, tid = meta["suite"], meta["id"]
    ws = WS / agent / suite / tid
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(task / "input", ws)
    images = sorted(p.name for p in ws.glob("*.png"))
    prompt = V2C_PROMPT if suite == "v2c" else T1_PROMPT.replace("%FILES%", ", ".join(images))
    logs = HERE / "runs" / agent / suite
    logs.mkdir(parents=True, exist_ok=True)
    cmd = command(agent, "mcp", ws.as_posix(), effort, logs / "_mcp", images=[(ws / i).as_posix() for i in images])
    t0 = time.time()
    status = "done"
    with open(logs / f"{tid}.jsonl", "wb") as out, open(logs / f"{tid}.stderr.log", "wb") as err:
        try:
            p = subprocess.run(cmd, input=prompt.encode("utf-8"), stdout=out, stderr=err, shell=False,
                               timeout=timeout, cwd=ws, env=agent_env())
            code = p.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
    log = (logs / f"{tid}.jsonl").read_text(encoding="utf-8", errors="replace")
    # The reference lives under DATA; an agent that names it has looked outside its workspace.
    leak = str(DATA).replace("\\", "/").lower() in log.replace("\\\\", "/").replace("\\", "/").lower()
    submitted = (ws / "submission.step").exists()
    tail = log[-4000:] + (logs / f"{tid}.stderr.log").read_text(encoding="utf-8", errors="replace")[-4000:]
    return {"suite": suite, "id": tid, "agent": agent, "effort": effort, "status": status, "exit": code,
            "seconds": round(time.time() - t0, 1), "submitted": submitted, "leak_suspect": leak,
            "transient": not submitted and any(t in tail for t in TRANSIENT)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["v2c", "t1"])
    ap.add_argument("--agent", choices=["claude", "codex"], required=True)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per task")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-done", action="store_true", help="skip tasks that already have a submission")
    a = ap.parse_args()
    if not os.environ.get("AGENTCAD_FREECAD") and not os.environ.get("FREECAD_LIB"):
        print("warning: AGENTCAD_FREECAD is not set; 3D parts need FreeCAD", file=sys.stderr)
    tasks = sorted(p for p in (DATA / a.suite).iterdir() if (p / "task.json").exists())
    if a.ids:
        tasks = [t for t in tasks if t.name in a.ids]
    if a.skip_done:
        tasks = [t for t in tasks if not (WS / a.agent / a.suite / t.name / "submission.step").exists()]
    tasks = tasks[:a.limit] if a.limit else tasks
    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(lambda t: run_one(t, a.agent, a.effort, a.timeout), tasks))


if __name__ == "__main__":
    main()
