"""Run prepared BenchCAD tasks through an external agent that builds the part with AgentCAD.

    python examples/benchcad/run.py v2c --agent claude [--arm mcp|code|hybrid] [--label NAME] [--jobs 3]
                                        [--effort high] [--ids id1 id2] [--limit N]

Each task gets a fresh workspace <ws>/<label>/<suite>/<id>/ outside this repository (the MCP server's
AGENTCAD_ROOT) holding only the task's input/ files (plus render.py in the code arm). In the AgentCAD arm the agent
can call AgentCAD's MCP tools and look at the input images (Claude Code: Read, run from the workspace; Codex: the
images are attached to the prompt), and nothing else. The code arm's agent gets file tools and a shell (see
agents.py); neither sandbox stops reads outside the workspace, so the logs are checked for the data directory
(leak_suspect). It must leave its part in submission.step. The reference stays under <data>, never inside a
workspace.
Event streams go to examples/benchcad/runs/<label>/<suite>/<id>.jsonl (label defaults to the agent); run summaries
to runs.jsonl beside them. Set AGENTCAD_FREECAD for 3D parts (the MCP server inherits it).

Arm "code" is the control: no AgentCAD. The agent writes CadQuery and runs it with BenchCAD's own interpreter
(BENCH_PY), and checks its part with render.py, which draws the same four views with BenchCAD's renderer.

Arm "hybrid" is the AgentCAD arm with scripts turned on (AGENTCAD_ALLOW_SCRIPTS): run_script on the part runs
CadQuery in the MCP server's interpreter, the repository's .venv, which needs agentcad-runtime[cadquery]. Its
prompt asks for the reference comparison (export_drawing(..., reference="composite.png")).
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
from agents import PY, agent_env, command  # noqa: E402

DATA = Path(os.environ.get("BENCHCAD_DATA", r"D:\Projects\bench-data"))
WS = Path(os.environ.get("BENCHCAD_WS", r"D:\Projects\bench-ws"))
BENCH_PY = Path(os.environ.get("BENCH_PY", r"D:\Projects\bench-src\BenchCAD-main\.venv\Scripts\python.exe"))

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

V2C_CODE_PROMPT = """You are an expert CAD engineer. composite.png in your workspace is a 2x2 composite of 4
diagonal views of a mechanical part. Build that part with CadQuery.

Views (cameras at, all looking at part center [0.5, 0.5, 0.5]):
- Top-left:     [-1, -1, -1]
- Top-right:    [ 1,  1,  1]
- Bottom-left:  [ 1, -1,  1]
- Bottom-right: [-1,  1, -1]

Renders are normalized: bbox centered at [0.5, 0.5, 0.5], longest side maps to [0,1]. Match orientation exactly:
world XYZ of your part must match world XYZ in the renders. Absolute size is not scored, proportions are.

Write your CadQuery program in part.py in your workspace and run it with %PY% (it has CadQuery 2.3); it must
export the part to submission.step (cadquery.exporters.export(result, "submission.step")). The part must be a
single solid. Work only in your workspace; it is already your working directory, so run commands without cd
(e.g. `%PY% part.py`).
To compare your part with the target, run `%PY% render.py submission.step preview.png`: it renders the same four
camera positions in the same 2x2 order with the renderer that drew composite.png. %LOOK%
submission.step is scored by voxel IoU against the real part when you finish; there is no other output."""

V2C_HYBRID_PROMPT = """You are an expert CAD engineer. composite.png in your workspace is a 2x2 composite of 4
diagonal views of a mechanical part. Build that part as a 3D AgentCAD part.

Views (cameras at, all looking at part center [0.5, 0.5, 0.5]):
- Top-left:     [-1, -1, -1]
- Top-right:    [ 1,  1,  1]
- Bottom-left:  [ 1, -1,  1]
- Bottom-right: [-1,  1, -1]

Renders are normalized: bbox centered at [0.5, 0.5, 0.5], longest side maps to [0,1]. Match orientation exactly:
world XYZ of your part must match world XYZ in the renders. Absolute size is not scored, proportions are.

Use only the AgentCAD tools. Build the part in part.FCStd with run_script("part.FCStd", code), a CadQuery program
(`cq` imported) that sets `result` to the solid, and/or with apply_operations (list_operations(category="part")
gives the part operations). Export it with export_drawing("part.FCStd", "submission.step", "step"). The part must
be a single solid.
To compare your part with the target, export_drawing("part.FCStd", "compare.png", "png",
views=[[-1,-1,-1],[1,1,1],[1,-1,1],[-1,1,-1]], reference="composite.png", overwrite=true) renders the same four
camera positions in the same 2x2 order (a views vector is the camera position), aligned to the target's
silhouettes, and returns a match score (compare.score; per view, compare.views[]: outline and edges inside it)
with a diff image.
submission.step is scored by voxel IoU against the real part when you finish; there is no other output."""

LOOK = {"claude": "Look at preview.png next to composite.png with the Read tool.",
        "codex": "Look at preview.png next to composite.png with your view_image tool."}

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
             "ECONNRESET", "503 Service Unavailable", "usage_limit_reached")


def run_one(task: Path, agent: str, arm: str, label: str, effort: str, timeout: int, attempts: int = 3) -> dict:
    for attempt in range(1, attempts + 1):
        row = _run_once(task, agent, arm, label, effort, timeout)
        if not row["transient"] or attempt == attempts:
            row["attempt"] = attempt
            break
        time.sleep(60 * attempt)
    logs = HERE / "runs" / label / row["suite"]
    with open(logs.parent / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
    return row


def _run_once(task: Path, agent: str, arm: str, label: str, effort: str, timeout: int) -> dict:
    meta = json.loads((task / "task.json").read_text(encoding="utf-8"))
    suite, tid = meta["suite"], meta["id"]
    ws = WS / label / suite / tid
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(task / "input", ws)
    images = sorted(p.name for p in ws.glob("*.png"))
    if arm == "code":
        if suite != "v2c":
            raise SystemExit("the code arm is set up for v2c only")
        shutil.copy(HERE / "render.py", ws / "render.py")
        prompt = V2C_CODE_PROMPT.replace("%PY%", BENCH_PY.as_posix()).replace("%LOOK%", LOOK[agent])
    elif arm == "hybrid":
        if suite != "v2c":
            raise SystemExit("the hybrid arm is set up for v2c only")
        prompt = V2C_HYBRID_PROMPT
    else:
        prompt = V2C_PROMPT if suite == "v2c" else T1_PROMPT.replace("%FILES%", ", ".join(images))
    logs = HERE / "runs" / label / suite
    logs.mkdir(parents=True, exist_ok=True)
    # the hybrid arm is the AgentCAD arm with scripts enabled (CadQuery in AgentCAD's venv: the [cadquery] extra)
    cmd = command(agent, "mcp" if arm == "hybrid" else arm, ws.as_posix(), effort, logs / "_mcp",
                  python=str(BENCH_PY), scripts=arm == "hybrid", images=[(ws / i).as_posix() for i in images])
    if (logs / f"{tid}.jsonl").exists():  # run again: keep the earlier attempt's logs, in a folder the summaries skip
        n = 1 + len(list((logs / "replaced").glob(f"{tid}.*.jsonl")))
        (logs / "replaced").mkdir(exist_ok=True)
        for ext in (".jsonl", ".stderr.log"):
            if (logs / f"{tid}{ext}").exists():
                (logs / f"{tid}{ext}").replace(logs / "replaced" / f"{tid}.{n}{ext}")
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
    # The reference lives under DATA; an agent that names it has looked outside its workspace. A pinned AgentCAD copy
    # (AGENTCAD_SRC) may sit under DATA too: its paths, in tracebacks, are not the reference.
    seen = log.replace("\\\\", "/").replace("\\", "/").lower()
    if os.environ.get("AGENTCAD_SRC"):
        seen = seen.replace(Path(os.environ["AGENTCAD_SRC"]).as_posix().lower(), "")
    leak = str(DATA).replace("\\", "/").lower() in seen
    submitted = (ws / "submission.step").exists()
    tail = log[-4000:] + (logs / f"{tid}.stderr.log").read_text(encoding="utf-8", errors="replace")[-4000:]
    return {"suite": suite, "id": tid, "agent": agent, "arm": arm, "effort": effort, "status": status, "exit": code,
            "seconds": round(time.time() - t0, 1), "submitted": submitted, "leak_suspect": leak,
            "transient": not submitted and any(t in tail for t in TRANSIENT)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["v2c", "t1"])
    ap.add_argument("--agent", choices=["claude", "codex"], required=True)
    ap.add_argument("--arm", choices=["mcp", "code", "hybrid"], default="mcp",
                    help="code: CadQuery without AgentCAD; hybrid: AgentCAD with CadQuery scripts and reference "
                         "comparison")
    ap.add_argument("--label", help="run directory name (default: the agent)")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per task")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-done", action="store_true", help="skip tasks that already have a submission")
    a = ap.parse_args()
    label = a.label or a.agent
    if not os.environ.get("AGENTCAD_FREECAD") and not os.environ.get("FREECAD_LIB"):
        print("warning: AGENTCAD_FREECAD is not set; 3D parts need FreeCAD", file=sys.stderr)
    if a.arm == "hybrid" and subprocess.run([str(PY), "-c", "import cadquery"], capture_output=True).returncode:
        raise SystemExit(f"the hybrid arm needs CadQuery in {PY}: install agentcad-runtime[cadquery] there")
    tasks = sorted(p for p in (DATA / a.suite).iterdir() if (p / "task.json").exists())
    if a.ids:
        tasks = [t for t in tasks if t.name in a.ids]
    if a.skip_done:
        tasks = [t for t in tasks if not (WS / label / a.suite / t.name / "submission.step").exists()]
    tasks = tasks[:a.limit] if a.limit else tasks
    with ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(lambda t: run_one(t, a.agent, a.arm, label, a.effort, a.timeout), tasks))


if __name__ == "__main__":
    main()
