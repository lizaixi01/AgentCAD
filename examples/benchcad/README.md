# BenchCAD pilot: Vision2Code with AgentCAD

A self-run pilot on [BenchCAD](https://arxiv.org/abs/2605.10865)'s Vision2Code task, comparing two coding agents
that build parts only through AgentCAD's MCP tools. **The harness is ours, not BenchCAD's, so these numbers are not
comparable to the leaderboard.** BenchCAD's leaderboard has models write CadQuery code directly. Here the agent
drives a CAD runtime: it can render previews, check its work and fix it.

## Setup

| | |
|---|---|
| Task | Vision2Code: one 2x2 composite of four diagonal views in, one solid out (`submission.step`) |
| Sample | 100 of the 17,900 tasks, drawn with `random.Random(42)` over the sorted ids (`prepare.py v2c --num 100 --seed 42`) |
| Score | BenchCAD's own `iou_step_vs_step`: voxel IoU at 64³ after both shapes are normalized by bounding box; a missing submission scores 0 |
| Agents | Claude Code + `claude-opus-5-5`; Codex CLI + `gpt-6.1-sol`. Both at reasoning effort `xhigh` |
| Tools | AgentCAD MCP, plus a way to view the input image (Claude: `Read`; Codex: the image attached to the prompt). Claude Code had no other tools. Codex ran with `-s read-only`, which still offers its shell, and loads the MCP servers from the user's `~/.codex` config; the logs show it used neither (no shell commands, every MCP call to agentcad) |
| Limits | 30 min per task, 3 tasks at a time per agent |
| Versions | AgentCAD `409c670`, BenchCAD `77fd16a` (see `pilot_meta.json`) |

Each task runs in a fresh workspace outside the repo that holds only the input composite. The reference STEP stays
in the data directory; no run log mentions that directory (`leak_suspect` is false for all 200 runs).

## Results (2026-10-29)

| | Claude Code + Opus 5.5 | Codex + gpt-6.1-sol |
|---|---|---|
| Submitted | 100 / 100 | 100 / 100 |
| **Mean IoU** | **0.766** | **0.872** |
| Median IoU | 0.800 | 0.957 |
| IoU ≥ 0.9 | 27 | 66 |
| IoU < 0.5 | 13 | 6 |
| Better on the same task (by > 0.02) | 10 | 69 |
| Median time per task | 187 s | 346 s |
| AgentCAD tool calls (median per task) | 7 | 10 |
| AgentCAD tool calls that returned an error | 43 / 870 | 97 / 1181 |
| Cost | $95.26 total, $0.63 median | not reported by Codex CLI |

Notes:

- 21 Claude tasks first failed with the account's usage limit (`429 usage_limit_reached`) before the model did any
  work. They were run again with the same settings once the limit reset (`runs.jsonl` keeps both rows; the scores
  use the last). One Codex task (`standoff_012834`) was retried once by the harness after a transient API error.
- Both agents miss most often on the same families: duct elbows, Gridfinity bins, connector faceplates, sprockets
  and impellers. Codex's lead comes mostly from parts it gets near-exact (IoU ≥ 0.95) where Claude scores 0.45–0.75,
  many of them simple: an L bracket, taper and clevis pins, a hollow tube, a tee nut. On these, Claude stopped with
  proportions or thicknesses estimated from pixels.
- The most common tool errors were `EXPORT_MISMATCH` (export check rejected a file, then the agent fixed it) and,
  for Codex, `FILE_EXISTS` from `export_drawing` refusing to overwrite an earlier `preview.png`.
- The pilot is one run per task. Run-to-run variance has not been measured.

## Control experiment: AgentCAD vs the same agent writing CadQuery (2026-10-29/30)

The pilot could not tell how much AgentCAD itself helps. So the same 100 tasks were run again, at reasoning effort
`medium` for both agents, in two arms that differ only in the tools:

- **AgentCAD arm** (`--arm mcp`): as in the pilot. AgentCAD MCP only, with PNG previews from `export_drawing`.
- **Code arm** (`--arm code`), the control: no AgentCAD. The agent writes a CadQuery program and runs it with
  BenchCAD's own interpreter (CadQuery 2.3). It checks its part with `render.py`, which draws the same four views
  with BenchCAD's renderer, the one that drew the input. Claude Code gets `Read`/`Write`/`Edit` and Bash limited to
  that interpreter; Codex runs `-s workspace-write`.

The AgentCAD arm was then run twice more after fixes the logs called for: #24 (`opt`) and #25 (`opt2`, Claude only;
see below). AgentCAD `d08d567` for the first runs (`control_meta.json`); the reruns ran `7f6fb16` (#24's head) and
`5116d41` (#25's first commit, the instructions change).
`summarize_control.py` writes every number below to `control_summary.json`.

| Medium effort, 100 tasks | Mean IoU | ≥ 0.9 | < 0.5 | Median time | Median input tokens | Cost |
|---|---|---|---|---|---|---|
| Claude Code + AgentCAD | 0.641 | 17 | 26 | 56 s | 179k | $29.0 |
| Claude Code + AgentCAD, after #24 | 0.640 | 14 | 26 | 53 s | 166k | $22.9 |
| Claude Code + AgentCAD, after #25 | 0.613 | 17 | 29 | 52 s | 157k | $21.8 |
| Claude Code writing CadQuery | **0.682** | 20 | 23 | 77 s | 75k | $15.6 |
| Codex + AgentCAD | 0.804 | 49 | 12 | 160 s | 303k | — |
| Codex + AgentCAD, after #24 | 0.811 | 45 | 11 | 148 s | 260k | — |
| Codex writing CadQuery | **0.918** | 73 | 1 | 294 s | 281k | — |

Paired by task, with 95% bootstrap intervals:

- **The code arm builds more accurate parts.** Codex + AgentCAD after #24 scores 0.107 below Codex writing CadQuery
  (−0.144 to −0.073); Claude after #25 scores 0.069 below (−0.110 to −0.027).
- **The AgentCAD arm is faster.** Its median time per task is 52 s vs 77 s for Claude and 148 s vs 294 s for Codex.
- **The fixes cut cost, not error.**
  - Cost and tokens dropped: Claude's cost fell 25% and its input tokens 12%; Codex's input tokens fell 14%.
  - IoU did not change measurably. Claude after #25 vs before: −0.027 (−0.062 to +0.006). Codex after #24 vs
    before: +0.007 (−0.018 to +0.035).
- **Why the code arm wins here:**
  - CadQuery is a full code-CAD language that models know well, and BenchCAD's reference parts are themselves
    CadQuery programs.
  - The code arm compares its part pixel for pixel with the input through the same renderer. AgentCAD's preview
    frames and colours parts differently, so thin features are hard to calibrate. For example, a dog bone got
    the right outline and the wrong thickness: IoU 0.08 against 0.84 for the code arm.
  - In 77 of 100 tasks, Codex in the code arm also read the renderer's source (`benchcad_core/scoring/views.py`)
    outside its workspace, despite the prompt. It held no reference data. But it told Codex the exact framing,
    which the AgentCAD arm could not see.
- **What the fixes found.**
  - #24: `list_operations(ops=[...])` looked only among 2D ops, so 37 Claude calls for real part ops failed. After
    #24 none did. The 13 `UNKNOWN_OPERATION` left (Codex) are guessed names that do not exist, such as
    `edit_feature` and `set_placement`; the op is `modify_feature`. A "did you mean" hint would help here.
  - At medium effort, Claude also calls tools by bare name (`list_operations` instead of
    `mcp__agentcad__list_operations`), and Claude Code rejects such calls. This happened in 46 of 100 tasks before
    #24, in 90 after it, and in 64 after #25, whose instructions name the prefix. It happened in 5 of 100 tasks in
    the xhigh pilot.
- **What this measures.** Vision2Code scores one solid built from nothing. It does not score what AgentCAD adds:
  checkpoints and undo, the journal, independent validation, an editable feature tree, the live viewer.

Next: make the 3D path agent-native. That means CadQuery scripts run as AgentCAD transactions, and previews
compared with a reference image, aligned per view with a match score. Then rerun this experiment.

## Files

- `prepare.py`: draws the sample and writes each task's input composite and reference STEP into the data directory
  (default `D:\Projects\bench-data`, or `BENCHCAD_DATA`). Run with BenchCAD's own venv.
- `run.py`: runs the tasks through an agent (`examples/trials/agents.py`), with retries for transient API errors.
  `--arm code` is the CadQuery control; `--label` names the run directory.
- `render.py`: copied into each code-arm workspace; renders a STEP with BenchCAD's own four-view renderer.
- `score.py`: scores the submissions with BenchCAD's scorer (BenchCAD's venv) into `runs/<label>/<suite>.scores.jsonl`.
- `summarize_control.py`: the control experiment's numbers and paired intervals, into `control_summary.json`.
- `strip_logs.py`: replaces the inline preview images in the run logs with a placeholder, to keep the logs small.
- `runs/<agent>/v2c/<id>.jsonl`: each task's event stream (images stripped); `<id>.stderr.log`: its stderr. Claude's `Read` calls
  (187 in all, all inside the task's own workspace) are not counted as AgentCAD tool calls above.

BenchCAD's data and reference STEP files are not in this repository. `examples/trials/summarize_run.py` summarizes
any run log (tool calls, errors, tokens, cost).

The drawing-to-part task (T1) is not run yet. Its data needs access approval on Hugging Face, and its scorer only
runs on Linux.
