"""Harder, work-like tasks for the AgentCAD-vs-plain-code comparison (Codex CLI as the agent).

    python examples/trials/hard/run_hard.py --reps 3 --jobs 6 --b-root <dir outside the repo> --b-python <ezdxf-only python>

Units of work = (arm, task, rep):
  H1  five revision rounds on a colleague's drawing, each round a fresh Codex session; round 4 undoes round 2.
      After each round the drawing is copied to snapshots/ (outside the workspace, invisible to the agent).
  H2  edit a real AutoCAD sample DWG (VW252-02-0142) and deliver a DWG.
  H3  batch: 12 flange drawings from a table, two rows geometrically invalid.
  H4  clean up a messy drawing onto a layer standard; H5 dimension an undimensioned part;
  H6  make an A3 print sheet with a 1:2 viewport (bases in bases2.py).
Arm A ("agentcad"): Codex with only the AgentCAD MCP server, read-only sandbox.
Arm B ("code"): Codex writing Python with plain ezdxf, workspace outside the repo, workspace-write sandbox.
  AutoCAD does not start inside that sandbox, so for H2 the runner converts the DWG to DXF with AutoCAD before
  the run and converts B's part_rev.dxf back to DWG after it (the user chose this over granting full access).
Logs: examples/trials/hard/runs/<arm>/<task>_r<rep>[_round<n>].jsonl
--agent claude runs Claude Code instead of Codex (see ../agents.py); its logs, snapshots and arm-A workspaces go
to runs_cc/, snapshots_cc/ and ws_cc/ so the Codex results stay as they are.
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

import ezdxf

HERE = Path(__file__).resolve().parent
TRIALS = HERE.parent
REPO = TRIALS.parents[1]
SAMPLE = Path(r"D:\Apps\AutoCAD\AutoCAD 2027\Sample\Sheet Sets\Manufacturing\VW252-02-0142.dwg")
TASKS = HERE / "tasks"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(TRIALS))
from agents import command  # noqa: E402
from bases2 import make_h4_base, make_h5_base, make_h6_base  # noqa: E402

SINGLE = {"H4": ("H4_cleanup.md", make_h4_base), "H5": ("H5_dimension.md", make_h5_base),
          "H6": ("H6_sheet.md", make_h6_base)}
ALLOW_SCRIPTS = False   # --allow-scripts: arm A's runtime gets AGENTCAD_ALLOW_SCRIPTS=1 (run_script on)
AGENT = "codex"         # --agent
RUNS, SNAPS = HERE / "runs", HERE / "snapshots"


def make_h1_base(path: Path) -> None:
    """The colleague's drawing: plate 120x80 R5, 4xØ10, real dimensions, plus content that must survive."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, color, lt in (("OUTLINE", 7, "Continuous"), ("HOLES", 7, "Continuous"), ("CENTER", 1, "CENTER"),
                            ("DIM", 3, "Continuous"), ("NOTES", 7, "Continuous"), ("LOGO", 5, "Continuous"),
                            ("TITLE", 7, "Continuous")):
        doc.layers.add(name, color=color, linetype=lt)
    st = doc.styles.get("Standard")
    st.dxf.font, st.dxf.bigfont = "gbenor.shx", "gbcbig.shx"
    ds = doc.dimstyles.get("EZDXF")
    for k, v in {"dimtxt": 3.5, "dimasz": 2.5, "dimexo": 0.625, "dimexe": 1.25, "dimgap": 0.625, "dimtad": 1,
                 "dimdec": 0, "dimtxsty": "Standard", "dimlfac": 1.0, "dimtsz": 0.0, "dimblk": ""}.items():
        ds.dxf.set(k, v)
    msp = doc.modelspace()
    b = 0.41421356237  # tan(22.5°): 90° fillet
    msp.add_lwpolyline([(5, 0, 0), (115, 0, b), (120, 5, 0), (120, 75, b), (115, 80, 0), (5, 80, b), (0, 75, 0),
                        (0, 5, b)], format="xyb", close=True, dxfattribs={"layer": "OUTLINE"})
    for c in ((12, 12), (108, 12), (12, 68), (108, 68)):
        msp.add_circle(c, 5, dxfattribs={"layer": "HOLES"})
    msp.add_linear_dim(base=(0, -15), p1=(0, 5), p2=(120, 5), dimstyle="EZDXF",
                       dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(-15, 0), p1=(5, 0), p2=(5, 80), angle=90, dimstyle="EZDXF",
                       dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(0, -7), p1=(0, 5), p2=(12, 12), dimstyle="EZDXF", dxfattribs={"layer": "DIM"}).render()
    msp.add_linear_dim(base=(-7, 0), p1=(5, 0), p2=(12, 12), angle=90, dimstyle="EZDXF",
                       dxfattribs={"layer": "DIM"}).render()
    d = msp.add_diameter_dim(center=(108, 68), radius=5, angle=45, dimstyle="EZDXF", override={"dimtoh": 1},
                             dxfattribs={"layer": "DIM"})
    d.dimension.dxf.text = "4X <>"
    d.render()
    msp.add_mtext("技术要求\\P1. 未注圆角 R5\\P2. 去毛刺，锐边倒钝", dxfattribs={"layer": "NOTES", "char_height": 3.5,
                                                               "insert": (0, -30)})
    logo = msp.add_lwpolyline([(135, 60), (155, 60), (155, 75), (135, 75)], close=True, dxfattribs={"layer": "LOGO"})
    hatch = msp.add_hatch(color=5, dxfattribs={"layer": "LOGO"})
    hatch.set_pattern_fill("ANSI31", scale=0.5)
    hatch.paths.add_polyline_path([(135, 60), (155, 60), (155, 75), (135, 75)], is_closed=True)
    msp.add_text("ACME", height=3, dxfattribs={"layer": "LOGO", "insert": (138, 55)})
    tb = doc.blocks.new("TB")
    tb.add_lwpolyline([(0, 0), (80, 0), (80, 20), (0, 20)], close=True)
    tb.add_line((0, 10), (80, 10))
    tb.add_text("图号", height=3, dxfattribs={"insert": (2, 13)})
    tb.add_text("版本", height=3, dxfattribs={"insert": (2, 3)})
    tb.add_attdef("PART_NO", insert=(25, 13), height=3)
    tb.add_attdef("REV", insert=(25, 3), height=3)
    ins = msp.add_blockref("TB", (130, -45), dxfattribs={"layer": "TITLE"})
    ins.add_auto_attribs({"PART_NO": "BP-120", "REV": "A"})
    doc.saveas(path)


def preamble(arm: str, task: str, b_python: str) -> str:
    if arm == "A":
        return (TRIALS / "tasks" / "_preamble.md").read_text(encoding="utf-8")
    return (TRIALS / "tasks" / "_preamble_code.md").read_text(encoding="utf-8").replace("%PYTHON%", b_python)


def codex(arm: str, task: str, ws: Path, prompt: str, log: Path, b_python: str = "") -> dict:
    """One agent session (Codex or Claude Code, see AGENT) in workspace ws."""
    cmd = command(AGENT, "mcp" if arm == "A" else "code", ws.as_posix(), "high", RUNS / "_mcp", b_python,
                  ALLOW_SCRIPTS)
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(log, "wb") as out, open(log.with_suffix(".stderr.log"), "wb") as err:
        p = subprocess.run(cmd, input=prompt.encode("utf-8"), stdout=out, stderr=err, shell=False, timeout=5400,
                           cwd=ws)
    return {"exit": p.returncode, "seconds": round(time.time() - t0, 1)}


def unit(arm: str, task: str, rep: int, a_root: Path, b_root: Path, b_python: str) -> dict:
    ws = (a_root if arm == "A" else b_root) / f"{task}_r{rep}"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    logs = RUNS / arm
    res: dict = {"arm": arm, "task": task, "rep": rep, "rounds": []}
    pre = preamble(arm, task, b_python)
    if task == "H1":
        make_h1_base(ws / "part.dxf")
        snaps = SNAPS / arm / f"H1_r{rep}"
        if snaps.exists():
            shutil.rmtree(snaps)
        snaps.mkdir(parents=True)
        shutil.copyfile(ws / "part.dxf", snaps / "round0.dxf")
        ctx = (TASKS / "H1_context.md").read_text(encoding="utf-8")
        for n in range(1, 6):
            prompt = pre + ctx.replace("%ROUND%", str(n)) + (TASKS / f"H1_round{n}.md").read_text(encoding="utf-8")
            r = codex(arm, task, ws, prompt, logs / f"H1_r{rep}_round{n}.jsonl", b_python)
            if (ws / "part.dxf").is_file():
                shutil.copyfile(ws / "part.dxf", snaps / f"round{n}.dxf")
            res["rounds"].append(r)
    elif task in SINGLE:
        name, make = SINGLE[task]
        make(ws / "part.dxf")
        res["rounds"].append(codex(arm, task, ws, pre + (TASKS / name).read_text(encoding="utf-8"),
                                   logs / f"{task}_r{rep}.jsonl", b_python))
    else:
        name = "H3_batch.md"
        if task == "H2" and arm == "A":
            shutil.copyfile(SAMPLE, ws / "part.dwg")
            name = "H2_real_dwg.md"
        elif task == "H2":
            # Arm B cannot start AutoCAD inside its sandbox: AutoCAD converts the DWG to DXF for it here and
            # converts its part_rev.dxf back to DWG afterwards; that DWG is graded like arm A's.
            from agentcad.backends import autocad
            jobs = SNAPS / "B" / f"H2_r{rep}"
            jobs.mkdir(parents=True, exist_ok=True)
            autocad.dwg_to_dxf(SAMPLE, ws / "part.dxf", jobs, "2018")
            shutil.copyfile(ws / "part.dxf", jobs / "part_given.dxf")
            name = "H2_real_dxf.md"
        res["rounds"].append(codex(arm, task, ws, pre + (TASKS / name).read_text(encoding="utf-8"),
                                   logs / f"{task}_r{rep}.jsonl", b_python))
        if task == "H2" and arm == "B" and (ws / "part_rev.dxf").is_file():
            try:
                autocad.dxf_to_dwg(ws / "part_rev.dxf", ws / "part_rev.dwg", jobs)
                res["converted_back"] = True
            except Exception as exc:
                res["converted_back"] = f"failed: {exc}"
    res["seconds"] = round(sum(r["seconds"] for r in res["rounds"]), 1)
    print(json.dumps(res, ensure_ascii=False), flush=True)
    with open(RUNS / "progress.jsonl", "a", encoding="utf-8") as f:  # survives an interrupted batch
        f.write(json.dumps(res, ensure_ascii=False) + "\n")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--rep-list", type=int, nargs="*", help="Run only these reps (resume after an interruption)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--tasks", nargs="*", default=["H1", "H2", "H3"])
    ap.add_argument("--arms", nargs="*", default=["A", "B"])
    ap.add_argument("--a-root", type=Path, help="Arm A workspaces (default ws/A, or ws_cc/A with --agent claude)")
    ap.add_argument("--agent", choices=["codex", "claude"], default="codex")
    ap.add_argument("--b-root", type=Path, required=True, help="Arm B workspaces, outside the repository")
    ap.add_argument("--b-python", required=True, help="Python with plain ezdxf only")
    ap.add_argument("--allow-scripts", action="store_true", help="enable run_script for arm A")
    a = ap.parse_args()
    global ALLOW_SCRIPTS, AGENT, RUNS, SNAPS
    ALLOW_SCRIPTS = a.allow_scripts
    AGENT = a.agent
    sfx = "_cc" if a.agent == "claude" else ""
    RUNS, SNAPS = HERE / f"runs{sfx}", HERE / f"snapshots{sfx}"
    a.a_root = a.a_root or HERE / f"ws{sfx}" / "A"
    reps = a.rep_list or range(1, a.reps + 1)
    units = [(arm, t, r) for r in reps for t in a.tasks for arm in a.arms]
    # H1 units are the longest (five sessions each): start them first
    units.sort(key=lambda u: u[1] != "H1")
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda u: unit(*u, a.a_root, a.b_root, a.b_python), units))
    name = f"summary_{'-'.join(a.tasks)}_{'-'.join(a.arms)}.json"
    (RUNS / name).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
