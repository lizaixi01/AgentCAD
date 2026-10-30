# U-C4N AutoCAD MCP benchmark: AgentCAD adapter

This is an independent local adapter for the task matrix published by
[U-C4N/Autocad-MCP](https://github.com/U-C4N/Autocad-MCP/tree/main/benchmarks),
pinned at `58a05ddfc34a9832c626e82cd88ecdce8e16a62a` (v1.7.0, evaluator v8.1).
It is not an upstream leaderboard submission. The [report](../../docs/comparison-upstream-benchmark.md)
explains the measured baseline and the remaining capability gaps.

## Method

- The adapter imports the original task definitions, result contract, runner and
  weighted scoring. It does not edit the upstream checkout. AgentCAD performs
  all credited CAD work through the official MCP stdio client and its own venv.
  No model, API key, Claude process, live AutoCAD session or enabled script tool
  is involved in the benchmark.
- A new server process runs each implemented task. The evaluator stages foreign,
  damaged and adversarial DXFs, as the reference adapter does, and independently
  reopens files. Core geometry, editing, dimensions and roundtrips must survive
  file readback rather than merely returning a successful tool response.
- The adapter translates contracts to AgentCAD's public API. For example,
  `requirements_roundtrip` draws the native plate spec and checks three native
  constraints plus one native hole-count requirement, including the moved bore
  in a second server process. TABLE/MLEADER accepts composite representations,
  as the reference adapter does; this does not assert native TABLE/MLEADER entities.
- The adapter covers the **current baseline**, not every hypothetical future
  implementation. Seven domain/preflight tasks are explicit capability assessments
  against the retrieved tools, operation schemas and library index; they do not
  claim a domain drawing was executed. Additional gaps are probed by relevant
  public tools. Extend the playbooks and gates when the missing contracts ship.
- Every incomplete gate is zero, including `partial`. This is conservative:
  upstream's result contract permits a partial score, but its reference adapter
  uses all-or-nothing gates. `unsupported` remains in the denominator.
  `cancel_safety` is `not_run`: the upstream deterministic held-worker trace
  requires internal instrumentation without an equivalent public-interface
  fixture here. That is missing evidence, not a measured product failure.
- The report includes both the upstream attempted-task score and the percentage
  of the full fixed matrix that passed. It includes a separate v2 summary so
  older public competitor rows are not compared with a different denominator.
- Timings are diagnostic only. The Pro reference mostly calls backend methods
  in process, whereas this adapter pays stdio, disk transactions and process
  startup costs. These runs cannot establish a cross-server speed ranking.

## Reproduce

Use an isolated AgentCAD worktree with its own editable venv, following the
repository's `AGENTS.md`. The measured AgentCAD product code is `945e6c6`;
the report records every product Python source hash. A newer checkout measures
the newer product and must not be labelled a reproduction of that baseline.

Prepare the upstream evaluator in a separate directory. Commands below assume
PowerShell and an existing parent output directory:

```powershell
git clone https://github.com/U-C4N/Autocad-MCP.git D:/bench/autocad-mcp
git -C D:/bench/autocad-mcp checkout 58a05ddfc34a9832c626e82cd88ecdce8e16a62a
Push-Location D:/bench/autocad-mcp
uv sync --locked --extra pdf --extra office
uv pip install --python .venv/Scripts/python.exe pypdf==6.21.4
Pop-Location
```

The evaluator runs in the upstream venv (its runner imports FastMCP). The server
runs in AgentCAD's venv. The adapter checks that this interpreter actually imports
the current worktree's `src/agentcad`, preventing a shared editable venv from
silently measuring another checkout. The baseline server used Python 3.11.16,
ezdxf 1.4.5, mcp 1.30.0 and pypdf 6.21.4; evaluator versions are recorded separately.

From the AgentCAD worktree, choose a new output directory:

```powershell
D:/bench/autocad-mcp/.venv/Scripts/python.exe examples/autocad_benchmark/run.py `
  --upstream D:/bench/autocad-mcp `
  --python .venv/Scripts/python.exe --out D:/bench/agentcad-run
```

Run the unchanged reference with its headless backend explicitly selected:

```powershell
Push-Location D:/bench/autocad-mcp
$env:AUTOCAD_MCP_BACKEND = "ezdxf"
$env:PYTHONUTF8 = "1"
.venv/Scripts/python.exe -m benchmarks.run_competitors `
  --server autocad-mcp-pro --backend ezdxf --matrix v8 --timeout 180 `
  --artifact-dir D:/bench/pro-run/artifacts --publish D:/bench/pro-run/report.json `
  --json > D:/bench/pro-run.stdout.json
Pop-Location
```

The adapter refuses a nonempty output directory and a modified/unpinned evaluator.
`artifacts/events.jsonl` records calls and responses; `progress.json` is updated
after completed tasks; stderr and drawings are retained. The original runner
records per-task failures/timeouts and continues. If interrupted, retain that
directory and restart in a new one; there is no automatic overwrite/resume.
`--task requirements_roundtrip` selects an individual task. Do not compare a
selected-task score with a full-matrix score.

## Recorded evidence

`results/2026-10-30/` holds the product and reference reports, plus an evidence
archive and its external SHA256 manifest. The archive includes the exact adapter
used, transcripts, MCP catalog, evaluator source hashes, synthetic drawings and
the reference artifacts. It excludes environments and third-party source trees.
The adapter's report hash identifies the archived script. Product source hashes
and the upstream pinned SHA identify the code needed to reproduce it.

These are deterministic baseline runs, with earlier adapter-development runs
retained locally rather than mixed into the final report. No existing trial
results or README measurements are replaced.
