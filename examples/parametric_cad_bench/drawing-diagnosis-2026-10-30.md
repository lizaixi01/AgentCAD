# Drawing reconstruction diagnosis and regression — 2026-10-30

The perforated plate's original **29.20/100** primarily reflects a wrong
interpretation of the section view: the recess and mounting bosses were built
on the same side, and a 2 mm recess depth was treated as a 2 mm remaining web.
Native pad/pocket operations executed those requested dimensions correctly.
The baseline's bounding-box and hole-count checks did not detect the mistake.

This investigation and its new measurements are separate from the unchanged
[original six-task pilot](pilot-2026-10-30.md). Both drawing tasks are known
development cases, not an unseen test set or an official leaderboard run.

## All fresh-agent results

Scores are the canonical `reward.json` multiplied by 100. Every cell below
comes from its own fresh model attempt, without manual repair. The latest
version improves the two-task mean by **9.56 points**, but the plate's gain is
only **5.00 points** and its section interpretation remains wrong.

| Task | Original baseline | Version 1: crop/zoom | Version 2: upright dimensions + independent checks |
|---|---:|---:|---:|
| Perforated plate `freecad-6fd69bd0c4` | 29.20 | 0.00 | **34.20** |
| Tube `freecad-686f17ce17` | 52.55 | 66.89 | **66.67** |
| Two-task mean | 40.87 | 33.45 | **50.43** |

Both versions completed 2/2 native submissions, without timeouts or
out-of-protocol tools. Latest runtimes were 355.09 s for the plate and 364.00 s
for the tube. This is not a best-of-two table; the latest tube score is retained
even though version 1 was slightly higher. The original six-task mean is not
recomputed by mixing new attempts into the old cohort.

The [machine-readable ledger](drawing-diagnosis-2026-10-30.json) records both
manifests, hashes, rewards, components, tool failures and native checks.
All four new [native parts and previews](artifacts/drawing-diagnosis-2026-10-30/)
are retained, including the zero-score plate.

## Evidence and controlled diagnosis

The old native feature tree, successful operation batches, public drawing and
post-run reference inspection agree on the following distinction. Coordinates
below use the original candidate's Z frame; the reference uses a different
global orientation, so it is the relative face placement that matters.

| Feature | Original candidate | Drawing interpretation confirmed after scoring |
|---|---|---|
| Main plate | Z = 1.5 to 5.6; thickness 4.1 mm | Same thickness |
| Recess | Cut upward from Z = 1.5 by 2.1 mm | Cut downward from Z = 5.6 by 2.0 mm |
| Four bosses | Start at Z = 3.6, extend downward 3.6 mm | Start at Z = 1.5, extend downward 1.5 mm |
| Consequence | Bosses extend through the recess on the same side | Recess and projecting bosses occupy opposite sides |

The original candidate had 12 holes and a valid solid. Its oriented bounding
box differed by only 0.007% and volume by 1.498%, yet its geometry score was
0.1786. The scorer could not find final-geometry witnesses for the 3 mm interior
holes and 8 mm bosses, despite those numbers appearing in the construction.
Both models have analytic planes and cylinders: the faceted PNG appearance is
preview tessellation, not evidence that native arcs became polygons.

Three deterministic controls replayed the original model's successful batches
through the unchanged CAD operations, altering only section-related settings.
They were scored with the same unmodified task scorer. These controls used
post-run diagnosis, including the reference, and are **manual repairs, not
agent attempts**:

| Control | Score / 100 | Geometry | Specification |
|---|---:|---:|---:|
| Original unmodified submission | 29.20 | 0.1786 | 0.8 |
| Correct cut depth only | 25.13 | 0.1490 | 0.8 |
| Correct sides and boss extension only | 46.41 | 0.3127 | 0.9 |
| Correct sides, boss extension and cut depth | 69.41 | 0.5315 | 1.0 |

The [control recipes and exact rewards](artifacts/drawing-diagnosis-2026-10-30/controls.json)
are archived separately from agent submissions.

Changing depth alone makes the still-wrong construction worse. Correcting the
whole section relationship restores all 37 specification checks. This is
strong evidence for a reading/model-planning error in this case, rather than
a pad/pocket direction or length implementation defect. A separate synthetic
FreeCAD test checks opposite-face pads, cut depth, bounding box and exact
volume without using this task's dimensions.

The remaining geometry deficit is consistent with local profile differences.
The original plan associated outer edge endpoints with the nearby 30.5 mm hole
pitch instead of the 25 mm edge dimension. Some contour coordinates were
estimated. The side-slot corner radius is not explicitly dimensioned in the
public drawing or the 37 nominal checks, so the reference's exact value cannot
be treated as a directly readable input. Hidden coordinates and radii were
not added to tool instructions or to the new agent prompts.

## General changes

- `inspect_image` returns an enlarged crop and its source coordinates/hash,
  as an inline MCP image; CLI, HTTP and Python share the same implementation.
  It also rotates a crop by 90, 180 or 270 degrees to read vertical dimensions.
  It reads only PNG/JPEG/WebP within the workspace, supports read-only mode,
  enforces image/preview budgets, and never rewrites the source drawing.
- General tool instructions ask the agent to trace dimension extension lines,
  distinguish cut depth from remaining wall thickness, record signed face
  levels, and check opposite faces. They contain no task identifiers, dimensions
  or reference geometry. CAD modeling operations are unchanged.
- The pilot can freeze a declared subset of an existing manifest, preserving
  model, effort, budget, seed and concurrency. New manifests pin input PNG
  hashes before modeling. A separate audit fix also counts plain-text MCP
  schema failures, which the older JSON-only error counter missed.

## First fresh regression: enlargement alone was insufficient

The first version at `6f8286025913b27e4241851e53d34feca4522bbb` added crop/zoom
and section guidance. Its fresh plate scored **0.00**, while the tube improved
from **52.55 to 66.89**. Both files were valid native single solids.

The plate now put the recess and bosses on opposite sides, but read the
vertical annotations as two boss levels, 7.5 and 3.6 mm below the recessed
face. It chose a 4 mm main plate and 5.5/1.6 mm boss extensions. The resulting
9.5 mm overall thickness triggered the scorer's bounding-box gate (41.053%
maximum relative error), zeroing geometry. Its validation request repeated
the constructed 9.5 mm height, so that self-check passed despite contradicting
the 5.6 mm drawing dimension. This first failure remains in the report and
artifact set; it is not replaced by a later attempt.

The second version adds upright image rotation and explicitly asks for a
drawing-derived dimension ledger and independent validation targets. Both
original tasks were run afresh again with that version. Neither agent received
the earlier geometry, diagnosis, scores or task-specific corrections.

## Latest result and remaining gap

Both agents used upright image rotation. The plate now has the correct total
height and opposite-side arrangement, but assigns 1.5 mm to remaining floor
thickness rather than boss projection: its main plate is 3.5 mm, floor 1.5 mm
and bosses extend 2.1 mm. The reference-confirmed relationship is main plate
4.1 mm, floor 2.1 mm and bosses projecting 1.5 mm. The overall 5.6 mm check
cannot distinguish those two constructions.

The latest plate's geometry component is **0.2111**, specification component
**0.9** (36/37 checks), and volume differs by **17.416%**. A post-run spec check
still cannot find the required final-geometry witness for the interior 3 mm
mounting holes; this does not mean that diameter is absent. The floor/boss
assignment and local profiles remain the accuracy bottleneck. Its 34.20 score
must not be described as the manually repaired control's 69.41.

The latest tube passes 12/12 specification checks and its bulk-property
subscores match, but the scorer's face-centre spatial alignment component is
zero. Geometry is 0.5, so the combined score is 66.67. That spatial discrepancy
is still unresolved; matching dimensions and volume do not certify the full
reconstruction.

Recovered tool errors also remain visible: the latest plate requested an
oversized image and an unsupported `measure` operation; the tube requested
unsupported operation names and a `deg` parameter unit. Both recovered. These
are interface-discovery/input errors, not evidence that a successful pad or
pocket executed the wrong requested geometry.

The next accuracy step is to associate each dimension with both measured
surfaces and cross-check the resulting layer stack across views, using public
input evidence. More enlargement alone has not solved that association. This
is a development finding from two known tasks, not proof of a general accuracy
gain or a reason to encode reference dimensions into the solver.

## Reproduction and scope

Each version uses the two original IDs, `freecad-6fd69bd0c4` and
`freecad-686f17ce17`, with one fresh process/workspace and one attempt per task.
Source instruction/task hashes match the original manifest; both PNG hashes
were checked against the published baseline ledger before preparing the run.

Model/runtime conditions match the baseline: Codex CLI 0.163.0, gpt-6.1-sol,
requested xhigh effort, existing ChatGPT login, 900 seconds per task, two
concurrent tasks, Python 3.11.16, FreeCAD 1.1.4 / OCCT 7.8.1 and validator
0.6.0's v2 scorer. Version 1 is pinned at
`6f8286025913b27e4241851e53d34feca4522bbb`; version 2 at
`ae244f778c52aa7b1893d41692e1e0ade085b04b`. The ledger recomputes tool-error
counts from saved trajectories using the corrected auditor, without modifying
the original run records, files or scores.

Only public instructions and original input PNGs enter the model workspaces.
The models have native CAD tools, including image inspection; scripts, shell,
web and other MCP servers remain disabled. Parent-side diagnostic files,
reference models, specification files and scorer results stay outside those
workspaces. The original prompt adaptation is unchanged. No manual control
model is used as a starting point, and no task-specific geometry hint is
passed to either fresh agent.

The diagnostic directory is
`D:\Projects\bench-data\cadbench-v3-drawing-fix-20261030\diagnostic`;
new run evidence is in
`D:\Projects\bench-data\cadbench-v3-drawing-retest-20261030` and
`D:\Projects\bench-data\cadbench-v3-drawing-retest2-20261030`, with matching
workspace directory names under `D:\Projects\bench-ws`.
These local traces are not a public Harbor/ATIF job. The same original
leaderboard-protocol gaps remain. Two known tasks and one attempt per version cannot
establish statistical reliability or separate the individual effects of image
inspection, general instructions and model sampling variation.

Verification: **477 tests passed, 6 optional CadQuery tests skipped**, with the
unrelated AutoCAD live integration tests excluded. Tests include real MCP/CLI
image crops and rotations, read-only/path/budget handling, fixed-cohort input
integrity, MCP failure accounting, and a real FreeCAD opposite-face pad/pocket
case. All four archived native hashes match their immutable stage records;
both latest previews were visually inspected. Original pilot reports and
artifacts remain unchanged.
