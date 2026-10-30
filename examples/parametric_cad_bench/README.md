# Parametric CAD Bench V3: local AgentCAD pilot

This adapter exercises AgentCAD's native FreeCAD operations on a fixed sample
from [Parametric CAD Bench V3](https://cadbench.ai/benchmark). It is a local
integration experiment, **not an official leaderboard submission**.

The [2026-10-30 pilot report](pilot-2026-10-30.md) covers six fixed tasks:
all six produced native editable parts, with mean task reward **55.43/100**.
The [machine-readable results](pilot-2026-10-30.json) include hashes and the
[generated CAD and previews](artifacts/2026-10-30/). No benchmark reference
models, solutions or input drawings are redistributed here.

The separate [drawing diagnosis and regression](drawing-diagnosis-2026-10-30.md)
preserves the original two drawing tasks and all attempts: that iteration's plate
scores **34.20** and tube **66.67**, for a **50.43** two-task mean. It also records
the intervening failed plate attempt and distinguishes manually repaired
diagnostic controls from fresh-agent results.

The next [face-measurement and view-correspondence iteration](section-evidence-2026-10-30.md)
fixes an inspection-filter defect and adds final-solid face-gap checks. Its
fresh scores are **30.77 / 66.89**, mean **48.83**: a regression from 50.43.
The plate still assigns a dimension to the wrong surfaces; the tube corrects
its handedness. The report preserves this outcome and the new native artifacts.

The [dimension-endpoint and raster-witness iteration](dimension-anchors-2026-10-30.md)
then adds general source-image anchors, linked dimension equations and external
arrow guidance. Its final fresh pair scores **67.21 / 66.89**, mean **67.05**;
the plate correctly associates the section dimensions and passes 37/37 specification
checks. The intermediate **32.44 / 66.89** attempt is also retained. These known-task
results do not establish reliability on unseen drawings or change the original pilot mean.

The [four previously unrun drawings](unseen-drawings-2026-10-30.md) then test the
merged workflow with the same model, effort and 900-second budget. Seed 42 fixes
the sample before viewing: wire lanyard **11.64**, LCD module **58.65**, valve
housing **99.83**, and stepped enclosure **15.66**, mean **46.45**. All four use
dimension endpoints before modeling and submit valid editable parts within time.
The spread shows uneven transfer; without an older-version run on the same four
tasks, it does not measure a causal improvement. Every attempt, low score,
native file, preview and scorer record is preserved.

V3 has 30 text-to-CAD creation tasks, 30 create-and-edit tasks and 40 tasks that
reconstruct a part from an engineering drawing. The last category evaluates
**3D reconstruction from a drawing**, rather than production of 2D drawings.
Edit tasks require both a newly constructed base and an edited target; their
scores are combined with a harmonic mean.

## What the adapter does

`pilot.py prepare` samples each category without replacement, using seed 42 by
default, before any agent runs. It records instruction, task metadata and public
input image hashes.
`run` copies only public instructions and input PNGs into separate workspaces.
Each task gets a fresh Codex process and an AgentCAD MCP server. Scripts, shell,
web search and other configured MCP servers are disabled. Only the selected CAD
tools are exposed. No reference models, solution scripts or grader results are
given to the agent. These are tool restrictions on a local machine, not the
benchmark's container isolation.

The agent builds `part.FCStd` through native operations. The small
`stage_server.py` adapter validates and copies its working file to the benchmark
filename. It performs no modeling. For edit tasks the agent saves the base,
edits the same working part, then saves the target. A saved stage cannot be
replaced by another call to the adapter.

`score` runs after modeling, outside the agent workspaces, using the selected
task's unmodified `tests/run_scorer.py` and `gnucleus-freecad-validator==0.6.0`.
Missing submissions, failed/timed-out agents and changed stage files count as
zero; a crashed scorer is an infrastructure error
and is not silently converted to a CAD failure. Raw trajectories, stderr,
native files, file hashes and score explanations remain in the external run
directories.

## Reproduce locally

Requirements: Python 3.11+, AgentCAD installed in this checkout's own virtual
environment, FreeCAD, Codex CLI with an existing login, and Harbor 0.23.0 for
downloading the tasks. Keep the task bundle, scorer environment, logs and
workspaces outside this repository. Do not put the grader inside a model's
workspace. The following PowerShell example uses placeholders for local paths:

```powershell
$env:PYTHONUTF8 = '1'
uvx --from harbor==0.23.0 harbor download gnucleus-ai/cad-bench@v3 --output-dir D:\bench\dataset
uv venv --python 3.11 D:\bench\scorer\.venv
uv pip install --python D:\bench\scorer\.venv\Scripts\python.exe 'gnucleus-freecad-validator[v2]==0.6.0'

$pilotArgs = @(
  '--dataset', 'D:\bench\dataset\cad-bench',
  '--output', 'D:\bench\run-01',
  '--workspaces', 'D:\bench\workspaces-01',
  '--freecad', 'D:\Tools\FreeCAD',
  '--model', 'gpt-6.1-sol', '--effort', 'xhigh',
  '--per-group', '2', '--seed', '42', '--timeout', '900', '--jobs', '2'
)
.venv\Scripts\python.exe examples\parametric_cad_bench\pilot.py prepare @pilotArgs
.venv\Scripts\python.exe examples\parametric_cad_bench\pilot.py run @pilotArgs
.venv\Scripts\python.exe examples\parametric_cad_bench\pilot.py score @pilotArgs `
  --scorer-python D:\bench\scorer\.venv\Scripts\python.exe
```

Use a new output/workspace pair for every attempt. Existing task runs and score
directories are not overwritten. `--ids` can run or score a subset of the frozen
selection. A subset summary describes only that subset. After scoring different
subsets, run `summarize` with the same arguments to combine all saved results
without running the scorers again. Do not choose a new
sample after seeing scores or present best-of-retry results as one attempt.

For an explicitly declared regression, reuse the original manifest and list
the original task IDs when preparing a **new** output/workspace pair:

```powershell
.venv\Scripts\python.exe examples\parametric_cad_bench\pilot.py prepare @pilotArgs `
  --baseline-manifest D:\bench\original-run\manifest.json `
  --ids freecad-6fd69bd0c4 freecad-686f17ce17
```

The adapter rejects changes to model, effort, time limit, concurrency, seed or
the selected tasks' recorded inputs. Older manifests without image hashes are
accepted, but cannot establish historical image identity on their own; compare
them with the baseline ledger. Run and score using the newly prepared paths.
The manifest labels this as a post-diagnostic regression, not a new blind sample.
AgentCAD's read-only `inspect_image` tool can magnify the public drawing's
dimensions and section views; it exposes neither the reference nor the grader.

## Differences from a leaderboard run

The official [frozen V3 protocol](https://cadbench.ai/benchmark) requires all
100 tasks, one attempt per task, no retries, a 9,000-second task limit, the
specified FreeCAD 1.1.0 environment and a public Harbor job with its config,
native artifacts and ATIF trajectory. The benchmark publishes a frozen dataset
digest; this pilot records that expected value but does not claim to have
independently verified the registry digest.

This pilot instead uses native MCP operations, a 900-second limit and a local
FreeCAD installation. It explicitly replaces the requested `answer.py` with
MCP stage saves. Thus a good local score would still leave work to package
AgentCAD into the official environment, satisfy the original output contract,
capture a complete ATIF trajectory and run the full public evaluation. The
exact local versions and measured results belong in the dated pilot report.
