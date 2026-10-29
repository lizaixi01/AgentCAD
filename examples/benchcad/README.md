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

## Files

- `prepare.py`: draws the sample and writes each task's input composite and reference STEP into the data directory
  (default `D:\Projects\bench-data`, or `BENCHCAD_DATA`). Run with BenchCAD's own venv.
- `run.py`: runs the tasks through an agent (`examples/trials/agents.py`), with retries for transient API errors.
- `score.py`: scores the submissions with BenchCAD's scorer (BenchCAD's venv) into `runs/<agent>/<suite>.scores.jsonl`.
- `strip_logs.py`: replaces the inline preview images in the run logs with a placeholder, to keep the logs small.
- `runs/<agent>/v2c/<id>.jsonl`: each task's event stream (images stripped); `<id>.stderr.log`: its stderr. Claude's `Read` calls
  (187 in all, all inside the task's own workspace) are not counted as AgentCAD tool calls above.

BenchCAD's data and reference STEP files are not in this repository. `examples/trials/summarize_run.py` summarizes
any run log (tool calls, errors, tokens, cost).

The drawing-to-part task (T1) is not run yet. Its data needs access approval on Hugging Face, and its scorer only
runs on Linux.
