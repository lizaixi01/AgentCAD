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
  with BenchCAD's renderer, the one that drew the input. Claude Code gets `Read`/`Write`/`Edit`/`Glob`/`Grep` and
  Bash under `acceptEdits`. Its permission rules allow that interpreter, and in-workspace edits also ran:
  `cat > part.py` 227 times and `sed -i` 43 times. Everything stayed in the workspace. Codex runs
  `-s workspace-write`.

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

- **Codex builds clearly more accurate parts by writing CadQuery.** Codex + AgentCAD scores 0.114 below the code arm
  (−0.156 to −0.074), and 0.107 below after #24 (−0.144 to −0.073).
- **For Claude the gap is not established.** The code arm is ahead of all three AgentCAD runs: by 0.041, 0.042 and
  0.069. But only the #25 run's interval excludes 0: −0.088 to +0.003, −0.084 to +0.002, and −0.110 to −0.027.
- **The AgentCAD arm is faster.** Its median time per task is 52 s vs 77 s for Claude and 148 s vs 294 s for Codex.
- **The fixes cut cost, not error.**
  - Cost and tokens dropped: Claude's cost fell 25% and its input tokens 12%; Codex's input tokens fell 14%.
  - IoU did not change measurably. Claude after #25 vs before: −0.027 (−0.062 to +0.006). Codex after #24 vs
    before: +0.007 (−0.018 to +0.035).
- **Why the code arm may win here.** The first two points are hypotheses; the last two are what the logs show:
  - CadQuery is a full code-CAD language that models know well, and BenchCAD's reference parts are themselves
    CadQuery programs.
  - The code arm compares its part pixel for pixel with the input through the same renderer, while AgentCAD's
    preview frames and colours parts differently. How much this matters is not measured here. The next section
    adds a reference comparison to AgentCAD.
  - Not every miss is about tools. Claude + AgentCAD built the dog bone lying flat (thin along Z) where the reference
    stands in the YZ plane, a 90° orientation error its preview did not catch: IoU 0.08 against 0.84 for Claude
    writing code. Codex + AgentCAD built it upright: 0.92, and 0.99 after #24.
  - In 77 of 100 tasks, Codex in the code arm also read the renderer's source (`benchcad_core/scoring/views.py`)
    outside its workspace, despite the prompt. It held no reference data, but it told Codex the exact framing, which
    the AgentCAD arm could not see. It does not explain the gap on its own: in the 23 tasks where Codex did not read
    it, the code arm still led the #24 AgentCAD run by 0.074 on average, and by 0.116 in the 77 where it did.
- **What the fixes found.**
  - #24: `list_operations(ops=[...])` looked only among 2D ops, so 37 Claude calls for real part ops failed. After
    #24 none did. The 13 `UNKNOWN_OPERATION` left (Codex) are guessed names that do not exist, such as
    `edit_feature` and `set_placement`; the op is `modify_feature`. A "did you mean" hint would help here.
  - Claude guesses too. After #24 it called `apply_operations` with nonexistent ops 16 times (`edit_feature`,
    `edit_sketch`). Its `UNKNOWN_PARAM` errors grew from 10 to 18 to 46, mostly on `modify_feature`'s parameters.
    Changing an existing feature is the interface Claude trips over most.
  - At medium effort, Claude also calls tools by bare name (`list_operations` instead of
    `mcp__agentcad__list_operations`), and Claude Code rejects such calls. This happened in 46 of 100 tasks before
    #24, in 90 after it, and in 64 after #25, whose instructions name the prefix. It happened in 5 of 100 tasks in
    the xhigh pilot.
- **What this measures.** Vision2Code scores one solid built from nothing. It does not score what AgentCAD adds:
  checkpoints and undo, the journal, independent validation, an editable feature tree, the live viewer.

## AgentCAD with scripts and a reference comparison (2026-10-30)

The control pointed at two gaps in AgentCAD's 3D path, and #26 filled both:

- `run_script` on a part runs a CadQuery program (or FreeCAD Part code) as one AgentCAD transaction. Its solid
  becomes the body's base and is validated and checkpointed like any operation.
- `export_drawing(..., reference=...)` renders the part from the reference's camera positions and aligns each view
  to the reference silhouette. It returns a match score per view (silhouette IoU) and a diff image.

The **hybrid arm** (`--arm hybrid`) ran the same 100 tasks at medium effort. It used AgentCAD `8f1eeb7` (main after
#26) with CadQuery 2.8, and had the AgentCAD arm's tools with scripts turned on. Its prompt (`V2C_HYBRID_PROMPT`
in `run.py`) names scripts first and operations as an alternative. AgentCAD's instructions suggest a script when
only the solid counts, as it does here.

| Medium effort, 100 tasks | Mean IoU | ≥ 0.9 | < 0.5 | Median time | Median input tokens | Cost |
|---|---|---|---|---|---|---|
| Claude Code + AgentCAD, after #25 | 0.613 | 17 | 29 | 52 s | 157k | $21.8 |
| Claude Code + AgentCAD with scripts and compare | **0.754** | 29 | 11 | 84 s | 209k | $36.2 |
| Claude Code writing CadQuery | 0.682 | 20 | 23 | 77 s | 75k | $15.6 |
| Codex + AgentCAD, after #24 | 0.811 | 45 | 11 | 148 s | 260k | — |
| Codex + AgentCAD with scripts and compare | 0.857 | 60 | 6 | 180 s | 289k | — |
| Codex writing CadQuery | **0.918** | 73 | 1 | 294 s | 281k | — |

Paired by task, with 95% bootstrap intervals:

- **Claude now builds better parts through AgentCAD than by writing CadQuery itself.** The hybrid arm leads the
  code arm by 0.072 (+0.032 to +0.112). It is better by more than 0.02 on 52 tasks and worse by more than 0.02 on
  28. It leads the operations-only run after #25 by 0.141 (+0.096 to +0.187).
- **Codex closes 43% of its gap, and is still behind.** It trails the code arm by 0.061 (−0.092 to −0.033), where
  it trailed by 0.107 before. It leads the operations-only run after #24 by 0.046 (+0.023 to +0.067). It takes 39%
  less time than writing CadQuery: 180 s vs 294 s median.
- **Claude pays for it.**
  - Time: its median was 84 s against 77 s. Paired by task it took 1.22× as long (median ratio), and 34% more time
    in total.
  - Cost: $36.2 for 100 tasks, 2.3× the code arm's $15.6. Fitting Claude Code's reported costs to its token counts
    gives $4 per million input tokens, $8 for cache writes, $0.20 for cache reads and $20 for output, with no
    residual.
  - At those prices, the $20.6 gap splits into cache writes $12.5, output $4.8 and cache reads $3.3. Cache writes
    are each turn's new content, such as compare images and tool results. AgentCAD's tool definitions and
    instructions (about 33k characters) are read back from the cache, so they are part of the $3.3.
  - It also took more turns: 14 vs 12.5 median.
- **This arm cannot split the gain.** It adds scripts and the comparison together.

What the logs show:

- **Both agents built every part with a script.** `run_script` ran in all 100 tasks for both agents, while
  `apply_operations` built a part in only one (Claude). That follows the prompt and AgentCAD's instructions, so it
  does not show what agents choose unprompted. Operations remain AgentCAD's way to edit a feature tree, which this
  task does not test.
- **Both compared with the target in every task, but not every submission.**
  - Compares ran on request: a median of 5 per task for Claude and 4 for Codex (548 compares for 573 scripts, and
    513 for 551).
  - 7 of Claude's and 11 of Codex's submitted parts were never compared. A compare counts for a submission when the
    compared part had the same volume.
- **The match score is optimistic.**
  - On the 93 Claude and 89 Codex submissions that were compared, the score averaged 0.93 and 0.95, against graded
    IoU of 0.74 and 0.87.
  - Per task, the two correlate weakly: r = 0.39 and 0.34.
  - Silhouettes see neither depth nor interior features. The four diagonal views are two pairs of opposite
    cameras whose silhouettes mirror each other, so the score rests on two silhouettes.
  - Codex's submitted connector faceplate scored 0.97 on compare and 0.32 graded; its U-channel 0.996 and 0.59.
- **A false export error cost points and features.**
  - The STEP export check refused 20 exports in 3 tasks, 5 runs (`EXPORT_MISMATCH`): a pin with two cross holes, a
    knob and the coil spring. The parts were fine. The check held volumes to 1e-6, below OCC's integration noise, and
    compared FreeCAD's quick bounding boxes, which follow B-spline control points.
  - On the coil spring, both agents spent the rest of the task working around the error and submitted simpler
    springs. BenchCAD's scorer gives the refused parts 0.39 (Codex) and 0.33 (Claude), and the submissions 0.18 and
    0.11. Codex's refused part had matched the target at 0.72. Even without the error, Codex would have trailed the
    code arm's 0.91 on this task.
  - On the clevis pin, Claude got the export through by leaving out the cross holes, and said so. At 64³ voxels the
    holes barely count: it still scored 0.995.
  - The same loose box made AgentCAD report sizes more than 1% off for 33 of the 200 final parts: up to 85% for a
    twisted drill, 57% for a coil spring, 51% for a threaded bolt.
  - #29 fixes both.
- **Claude called tools by bare name in 51 of 100 tasks.** These were 101 calls (`run_script`, `export_drawing`),
  which Claude Code rejects before they reach AgentCAD.

Caveats: CadQuery is 2.8 in AgentCAD and 2.3 in the code arm. Test suites ran on the same machine during this run,
so the times are noisy. As before, each task ran once.

Next:

- A comparison that sees inside the outline (shading or depth), so the score tracks the shape and not just its
  silhouettes.
- Smaller compare results, to cut Claude's cost. The images and tool results each turn writes to its cache are
  most of the extra cost.

## Files

- `prepare.py`: draws the sample and writes each task's input composite and reference STEP into the data directory
  (default `D:\Projects\bench-data`, or `BENCHCAD_DATA`). Run with BenchCAD's own venv.
- `run.py`: runs the tasks through an agent (`examples/trials/agents.py`), with retries for transient API errors.
  `--arm code` is the CadQuery control, `--arm hybrid` AgentCAD with scripts and the reference comparison (it needs
  `agentcad-runtime[cadquery]`); `--label` names the run directory.
- `render.py`: copied into each code-arm workspace; renders a STEP with BenchCAD's own four-view renderer.
- `score.py`: scores the submissions with BenchCAD's scorer (BenchCAD's venv) into `runs/<label>/<suite>.scores.jsonl`.
- `summarize_control.py`: the control experiment's numbers and paired intervals, into `control_summary.json`.
- `strip_logs.py`: replaces the inline preview images in the run logs with a placeholder, to keep the logs small.
- `runs/<label>/v2c/<id>.jsonl`: each task's event stream (images stripped); `<id>.stderr.log`: its stderr. In the
  pilot, Claude's `Read` calls (187 in all, all inside the task's own workspace) are not counted as AgentCAD tool
  calls.

BenchCAD's data and reference STEP files are not in this repository. Codex's code-arm logs quote BenchCAD's
`benchcad_core/scoring/views.py` (MIT License, © the BenchCAD authors), because Codex read that file while
working. `examples/trials/summarize_run.py` summarizes
any run log (tool calls, errors, tokens, cost).

The drawing-to-part task (T1) is not run yet. Its data needs access approval on Hugging Face, and its scorer only
runs on Linux.
