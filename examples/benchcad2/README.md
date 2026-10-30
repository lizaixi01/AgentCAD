# BenchCAD 2 development samples: GPT-6.1 Sol at max

This experiment runs the **nine public development samples**, covering all six
tasks, through Codex CLI and AgentCAD. It is a custom MCP agent harness, **not
BenchCAD's provider harness, the gated 100-case Core set, or a leaderboard result**.
The development samples check integration and are too small to estimate general
performance. The user chose them because Core access was unavailable.

[2026-10-30 report (Chinese)](report-2026-10-30.md) ·
[metrics and provenance](results-2026-10-30.json): **9/9 explicit submissions,
53.45/100 mean of the six task means**. The measured AgentCAD snapshot is
`2583516`; check out that commit in an isolated worktree to reproduce the
historical run. Later main-branch features belong to a new experiment.
After integration, the reusable runner pins the full tool profile and describes
reference comparison without the historical silhouette-only limitation. Those
compatibility edits did not participate in the recorded model episodes.

## Protocol

- Model explicitly pinned to `gpt-6.1-sol`, reasoning effort `max`, using the
  existing Codex ChatGPT login. No OpenAI API key is needed by this runner.
- BenchCAD release `v2.1`, commit `70b7aaeb3a031851d058252e4ebe4ed30ca41f77`.
  Scoring uses that checkout's `envs.common.score_case.score_case`, including its
  task-specific submission and orientation rules. It is not the older
  Vision2Code-only voxel IoU experiment in `../benchcad/`.
- Official input staging: copy only `input/`; use BenchCAD's PDF rasterization,
  tiles, high-resolution drawing masters, BOM item mapping, task brief selection,
  and initial image selection. `gt/`, `case.json` and scorers never enter the
  model's workspace or MCP process. No reference-renderer code is exposed.
  All 144 input/reference files are checked against their manifest SHA-256 values.
  On Windows use `core.autocrlf=false` for the BenchCAD checkout: otherwise Git
  converts text STEP/JSON line endings and breaks the published file hashes.
- Codex receives only the AgentCAD MCP server, with its normal CAD tools and the
  benchmark adapters below. User MCP configuration, plugins, shell, web search,
  user/project instruction files and multi-agent tools are disabled for the run.
- New geometry must go through AgentCAD's `run_script` or operations, its
  validation, checkpoints and STEP export. CadQuery 2.8 is installed in the
  worktree's own environment; FreeCAD 1.1.4 handles AgentCAD's parts.
- A benchmark adapter reads/crops input images and text, inspects supplied STEP
  files and provides a simple independent four-view preview. The adapter does
  not generate new geometry. Its assembly submission copies supplied STEP files
  unchanged and saves the model's rigid placement matrices. The official scorer
  checks the supplied geometry and rebuilds the assembly from parts and matrices.
- T2 tests assembly reasoning with supplied parts; AgentCAD has no native assembly
  engine. T4/T5 use AgentCAD for newly modelled parts and the adapter for placements.
  **T6 is model-only visual graph reasoning**, submitted through a JSON adapter;
  AgentCAD has no schematic engine. A six-task aggregate must not be described as
  AgentCAD CAD-engine performance alone.
- Limit: 3,600 seconds and 100 MCP calls per case. An explicit
  `submit_answer` call is required; failed or interrupted episodes do not promote
  an earlier STEP to an answer. The first final answer is copied into reserved
  runtime state and sealed; later workspace edits/submissions cannot replace it.
  These are not the official 60-round/500k-output-
  token limits. Codex manages its own reasoning context and compaction. Dollar
  cost and a mid-episode reasoning-token budget are unavailable from this CLI.
- Standard-answer checks must score 1.0 for all nine cases before interpreting
  results. On this Windows host, BenchCAD's POSIX pipe-based mesh worker fails
  with `WinError 10038`, so scoring uses its documented
  `BENCHCAD_MESH_GUARD=0` in-process mode. The geometry metric is unchanged, but
  CPU-time isolation and the worker's BREP serialization round trip are absent;
  the whole scoring process retains a wall-time limit. BLAS/OpenMP threads are
  pinned to one in all child processes to limit memory pressure. This is another reason
  these numbers are not a formal benchmark submission.
- Scoring happens offline, after submission; no reference scores are returned to
  the model. Resume retains every attempt and skips completed, timed-out and
  call-limited episodes. Infrastructure errors require an explicit `--retry-infra`
  to retry; all attempts remain in the summary.
  Scores of zero for absent answers are distinct from evaluator failures (`null`).
  Overall score is the mean of the six task means, only when all nine are scored.
  Scoring must match the model run's recorded protocol and all nine passing
  standard answers. Mixed or uniformly changed revisions never produce a
  complete aggregate.

## Reproduce

Create a worktree with `scripts/new-worktree.ps1`, install the `cadquery` extra in
that worktree, and provide a clean BenchCAD `v2.1` checkout with its dependencies.
The runner accepts `--bench-source` and `--bench-python` for other locations.

```powershell
$env:AGENTCAD_FREECAD = '<your FreeCAD 1.1.4 folder>'
$env:AGENTCAD_VIEWER = '0'
$env:PYTHONIOENCODING = 'utf-8'
$env:BENCHCAD_MESH_GUARD = '0'  # Windows; see the protocol above
$benchSource = '<BenchCAD v2.1 checkout with canonical file bytes>'
$benchPython = '<BenchCAD environment python.exe>'

.venv\Scripts\python examples/benchcad2/run.py oracle --bench-source $benchSource --bench-python $benchPython --out '<output directory>'
.venv\Scripts\python examples/benchcad2/run.py run --bench-source $benchSource --bench-python $benchPython --out '<output directory>' --resume
.venv\Scripts\python examples/benchcad2/run.py score --bench-source $benchSource --bench-python $benchPython --out '<output directory>' --resume
```

`--cases task3_case2` selects one case. `--jobs` defaults to two model episodes or
one offline scorer. This host uses two model episodes after limiting numerical
library threads to one, and one offline scorer.
All nine standard-answer checks must pass with the current scoring protocol before
any model run. An initial integration trial was aborted after CAD imports/previews
failed under memory pressure; its logs remain outside the final nine-case run,
without a score. `--resume` never resets an exhausted time or tool-call budget.
Failed attempts are retained in `attempt-N/` directories. A second integration
batch (`benchcad2-sol-max-20261030-dev9`) was stopped before either active case
submitted: CadQuery rejected exact rigid JSON matrices in the preview adapter's
`transformShape` call. This was reproduced locally and fixed by applying the
unchanged matrix with the general transform for preview only. Both integration
batches remain outside the final run and have no assigned performance scores.
Real MCP preview tests now cover exact and oblique rotations, including unchanged
source STEP bytes. The final run uses a new output directory and the fixed adapter.
Do not use this script on Core: it is deliberately restricted to `examples/`.

The external output directory holds `metadata.json`, each case's `run.json`,
`oracle.json`, `score.json`, prompts, command lines, raw events and workspaces.
Run metadata pins both source revisions, the adapter/runner hashes, CLI version
and limits. Raw events contain inline images and can be large. Inputs, STEP
answers and raw image-bearing logs remain outside the AgentCAD repository;
only evaluation code and aggregate/diagnostic metrics belong in the report.

Sources: [leaderboard](https://benchcad.com/leaderboard),
[Core access](https://benchcad.com/access),
[BenchCAD v2.1](https://github.com/BenchCAD-org/benchcad-2-main/releases/tag/v2.1),
[development samples](https://github.com/BenchCAD-org/benchcad-2-main/tree/v2.1/examples),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
