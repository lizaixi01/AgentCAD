# Reproducing the source-capability review

The six weights come from U-C4N's source review, but its published scores do not
define per-point anchors. Our [frozen local rubric](../../docs/source-capability-rubric.md)
adds 20 explicit items and applies them to **both** pinned products. It does not
turn the v8 execution score into a source score, or establish an upstream listing.
The original Pro 93/100 self-review remains a separate historical measurement.

The [2026-10-30 result](results/2026-10-30/README.md) records AgentCAD **98** and
Pro **96** under this method, including item deductions, pinned source references,
complete regression/v8 records, native production examples and raw version timings.

The [2026-10-31 follow-up](results/2026-10-31/README.md) retains a superseded
100/93 assessment: final publication review found two additional false successes
at `6699109`, so this is no longer the current score. Its measurements and
performance baseline `69c1425` remain historical references; repair/recheck is pending.

## Environment and regression evidence

Check out the product commit named in a result, then install its dependency graph:

```powershell
uv sync --locked --extra dev
uv run --locked python scripts/gen_docs.py --check
uv run --locked python -m pytest -p no:cacheprovider --basetemp=D:/bench/tests --junitxml=D:/bench/tests.xml
```

Use your own empty temporary directory. Set `AGENTCAD_VIEWER=0` for unattended
verification. AutoCAD and FreeCAD are optional; missing dependencies are **skips**,
not passes. The local native lane also sets `AGENTCAD_FREECAD` to the installed
FreeCAD directory. Do not run other AutoCAD jobs concurrently: its registry profile
is shared. CI checks the same collected tests on Windows 3.11, Linux 3.10/3.12 and
macOS 3.12, while the native lane provides the additional local backend evidence.

For v8 use the [original evaluator reproduction instructions](../autocad_benchmark/README.md)
and then `python scripts/check_benchmark.py <output>/report.json`. The extra gate
requires every original task to pass; a runner's zero exit code alone is not proof.

## Production examples

```powershell
uv run --locked python examples/source_capability/showcase.py --out D:/bench/showcase --native
```

Omit `--native` for the portable DXF/PDF/SVG/JSON path. The script requires committed
product and harness files, binds imports to that checkout, checks all loaded
AgentCAD module paths and source hashes, and refuses an existing output directory.
Reports retain every operation/specification and result. No LLM or private drawing
input is used. These are original synthetic examples beyond the v8 inputs:

- A three-step sleeve and six-hole end cap, front/end/section views, five BOM rows,
  balloons, an A3 paper viewport at 1:1 and paper-space annotation.
- A distinct fractional-length sleeve and eight-hole flange, two BOM rows,
  supplied dimensions and hole placement, plus a separately sourced M14 detail.
- Two rooms with a partition, doors, window, dimension chains and schedules;
  independent expected room areas are 26.9048 and 44.4808 m².
- A pump, pneumatic control valve, panel instrument and vessel, with independently
  checked process-line numbers and an unnumbered signal connection.
- A 35 H7 bore using the sourced +0.025/0.000 deviations, saved native dimension
  variables and readable stacked text.

The native option saves each example as real DWG, imports it again and runs AUDIT.
It checks paper size, viewport scale/centres and paper-space text after conversion.
AutoCAD may write inactive layout viewports with id/status zero. A separate native
witness job activates the real A3 layout, regenerates and DXFOUTs it, then the
ordinary PDF exporter renders that saved layout. The job neither rewrites IDs nor
repairs geometry. Its input, script, output and console log remain in the evidence.
Raw inactive layouts may need activation before a headless renderer shows them.

Render the PDFs with a separate viewer (the recorded review uses Poppler) and
inspect clipping, legibility, section hatching, labels, page boundaries and the
tolerance text. `visual_review: pending separate inspection` in the harness report
is deliberate: structural success cannot certify visual readability. The published
review is a separate artifact. These examples demonstrate supported workflows;
they are not a complete manufacturing release or standards certification.

## Same-environment version comparison

```powershell
uv run --locked python examples/source_capability/compare.py --baseline a713426 --candidate <product-sha> --out D:/bench/comparison --counts 2000 10000 --repeats 5
```

Both git snapshots are extracted immutably and run with the **same interpreter and
dependencies**, in fresh child processes. The script verifies its actual import
path, creates uniquely positioned lines through public `Runtime`, exports/reopens
DXF and independently checks every endpoint, entity count, units and audit errors.
Order alternates; each version/count gets one excluded warm-up and five measured
trials. Raw observations, source hashes, dependency versions, medians and ratios
are retained. An assertion or failed child ends the run rather than granting credit.

Timing includes validation and saved DXF readback, but excludes process startup,
native CAD, MCP transport and model latency. It is a local version-regression
observation on lines, **not** a speed ranking against Pro or a general complexity
claim. Correctness and performance evidence must both be reported, including any
regression. Use a quiet machine and preserve interrupted/failed runs separately.

## Evidence policy

New results go in a new `results/` directory with hashes and pinned versions.
Historical trial files and scores are never overwritten. Archive only synthetic
drawings, reports, traces, reviewers' observations and environment metadata; source
standards PDFs and Autodesk sample drawings are not redistributed. GitHub's
short-lived CI artifacts need a permanent copy in the result archive. Public
headless results and local native results keep their separate scopes.
