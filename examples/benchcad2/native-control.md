# BenchCAD native-tool control for AgentCAD + Astra

[Completed 2026-10-31 comparison](comparison-native-astra-2026-10-31.md): native
71.77 vs AgentCAD 56.79 overall, and 66.63 vs 58.15 on T1–T5. The original eight
valid AgentCAD submissions were rescored without changes; nine fresh oracle checks
passed. The fixed design below preceded the model requests.

This experiment holds GPT-6 Astra / max, Codex CLI 0.163.0 and its existing
ChatGPT login, the nine development cases, initial images, task briefs, evaluator,
3,600-second / 100-tool-call per-case limits and maximum two model episodes fixed.
The reference is the original nine AgentCAD + Astra attempts at AgentCAD `2583516`,
including the T6/case2 connection failure/no-submission zero. Its separate failed
recovery does not replace that first attempt. The original sealed answers are
regraded with the same frozen interpreter as the native answers; historical scores
are preserved alongside those matched-environment scores.

The changed treatment is the complete tool workflow. `native_run.py` exposes one
MCP transport tool, `execute_python(code, submit=False)`, to the same Codex client.
Each call counts once, whether it inspects files, crops an image, models a part,
fails or submits. Python operations inside one program are not separately counted.
The model's shell, web, plugins, other MCP servers and project instructions remain
disabled, as in the reference. This is not the official provider/API harness or
the Core leaderboard protocol.

## Native workbench

- `tools.py` and `sitecustomize.py` are staged byte-for-byte from BenchCAD v2.1,
  commit `70b7aaeb3a031851d058252e4ebe4ed30ca41f77`. They are not vendored here.
  Native export, crop, supplied-part copying and assembly submission functions
  retain their original behavior. No reference renderer or scoring source is staged.
- Python runs in fresh offline Docker containers with persistent workbench files,
  2 GiB, one CPU, read-only root and the workbench as its only host mount.
  These are the native sandbox's isolation/resource settings. Programs have a
  300-second execution limit within the unchanged episode deadline.
- Python 3.11.16, CadQuery 2.8.0/OCP 7.9.3.1.1 and the common numerical/image
  package versions match the measured AgentCAD interpreter. The supplied Dockerfile
  deliberately aligns these versions instead of using upstream's older CadQuery
  2.3 image. Linux versus Windows and the native container caps remain differences.
- New/modified top-level PNGs are returned after each program. Images use the same
  RGB/2000-pixel-side encoding as the AgentCAD input adapter. Native validity checks
  exclude malformed or sub-512-pixel images. Streams use the native 10,000-byte
  first/last observation limit. Initial image files and ordering match the reference.
- `submit=True` appends the native `tools.finish(globals())`, executes once and ends
  the episode, including when that final program fails. A failed final program
  never promotes an older intermediate STEP. Native artifact precedence is retained.
- Answers are copied outside the container mount before the episode finishes.
  Session markers are also outside that mount. The model cannot fabricate a host
  submission marker or change the sealed answer by editing its workbench.
- The host MCP transport uses Python isolated mode; workbench Python modules are
  usable inside the container and cannot shadow host transport imports. AgentCAD
  is not installed in the model's container and no AgentCAD CAD tool is exposed.

## Analysis fixed before model requests

Primary: mean of six task means, using each workflow's original first attempt on
all nine cases, both graded in the frozen scoring environment. No submission is zero; evaluator failures are null and must be
resolved offline before a complete aggregate. No best-attempt selection or hidden
submission fallback. Internal Codex connection retries consume the wall budget.

Secondary: mean of T1-T5 task means. T6 uses no AgentCAD CAD capability and its
reference failure prevents judging the missing graph's accuracy. Descriptive
part-geometry (T1/T3) and assembly-workflow (T2/T4/T5) task means are also retained.
Differences are AgentCAD minus native; positive favors AgentCAD. Resource totals,
coverage, failure reasons and known/missing token usage are reported separately.

The task brief and input bytes are fixed; tool-specific instructions and interfaces
necessarily differ. This measures net behavior of these complete workflows under
the stated caps, not the isolated causal effect of one validation/preview/kernel
component, and nine samples with one attempt each do not establish general ranking.

## Run

Create an isolated AgentCAD worktree with its own environment; native model code
does not import the installed AgentCAD package. Build the aligned native image:

```powershell
docker --context desktop-linux build -t agentcad-benchcad-native:20261031 examples/benchcad2/native_runtime

$nativeOut = '<new absolute output directory>'
$benchSource = '<canonical BenchCAD v2.1 checkout>'
$benchPython = '<dedicated staging/scoring interpreter with the original pinned dependencies>'
$agentcadAstra = '<the recorded AgentCAD + Astra output directory>'

.venv\Scripts\python examples/benchcad2/native_run.py prepare --bench-source $benchSource --bench-python $benchPython --reference $agentcadAstra --out $nativeOut
.venv\Scripts\python examples/benchcad2/native_run.py run --bench-source $benchSource --bench-python $benchPython --out $nativeOut --resume
.venv\Scripts\python examples/benchcad2/native_run.py score --bench-source $benchSource --bench-python $benchPython --out $nativeOut --resume
```

Preparation checks the original metadata, all case hashes, staged input bytes,
initial image order, task briefs and aligned packages. It reruns nine 1.0 oracle
checks and grades every original first-attempt AgentCAD answer after verifying its
published sealed-file hashes. A changed historical score is disclosed, never
written over the original measurement.

The source commit, runner/helper hashes, immutable image ID and scoring environment
are frozen before any model request. The grader fingerprint covers its exact
interpreter path, executable/base-executable hashes, Python/platform, distribution
versions, METADATA/RECORD hashes and relevant environment settings. Staging/scoring
use isolated UTF-8 interpreter mode; both the model and scoring entry points reject
a changed grader. Every fresh oracle and score carries the same fingerprint, and
mixed-environment results cannot produce a complete aggregate.

`run` refuses changed source/settings and never replaces a prior attempt.
Scoring stays on the original host, pinned source, numerical threads and
`BENCHCAD_MESH_GUARD=0` protocol, outside model workbenches. Workbench input edits
are allowed by native Python and recorded; initial staged hashes remain the control.
