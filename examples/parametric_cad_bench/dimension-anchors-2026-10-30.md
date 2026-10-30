# Drawing reconstruction: dimension endpoints and raster witnesses — 2026-10-30

This continues the [face-measurement iteration](section-evidence-2026-10-30.md)
on the **same two drawing tasks**. It tests a general way to associate dimensions
with physical surfaces, without putting either task's answer in AgentCAD.

**The final fresh run fixes the plate's section assignment and raises its
score to 67.21/100.** The tube remains at 66.89; the two-task mean rises from
48.83 to **67.05**. An intermediate version still misread the plate; its
complete result is retained below, not replaced by the better attempt.

| Task | Previous face-measurement run | Anchors only (`08a4ef1`) | Raster witnesses + arrow guidance (`a6c673b`) |
|---|---:|---:|---:|
| Plate `freecad-6fd69bd0c4` | 30.77 | 32.44 | **67.21** |
| Tube `freecad-686f17ce17` | 66.89 | 66.89 | **66.89** |
| Two-task mean | 48.83 | 49.67 | **67.05** |

All scores are canonical `reward.json` rewards multiplied by 100. The original
pilot's plate score was 29.20; its six-task mean remains the original 55.43.

## Final attempt: the section relationship survives construction

The new plate agent maps the short dimension to the plate underside and boss
bottom before building, then derives 4.1 mm main thickness and 2.1 mm remaining
floor from the linked 5.6 mm overall, 1.5 mm boss and 2 mm recess callouts.
These are readings made by the fresh model, not constants supplied by the tool.
Its final measured plane levels are `[-1.5, 0, 2.1, 4.1]` mm. The native
parameter tree also preserves main thickness as `TotalThickness - BossProjection`.
Both the pre-build interpretation and final solid retain the correct association.

The canonical reward is **0.672149**, with geometry **0.50619** and specification
**1.0 (37/37)**. Volume difference falls from the previous run's 18.791% to
**1.155%**; surface-area difference is 0.562% and principal-moment difference
0.276%. Geometry is still imperfect. The scorer's volume component is zero at
this difference, and the spatial component is 0.636; neither the thresholds nor
the official reward were adjusted to make this result look better.

The tube again checks and corrects its projection orientation. Its reward is
**0.668902**, geometry **0.50252**, specification **1.0 (12/12)** and volume
difference **0.091%**. The spatial component remains 0.005. The previous report's
discussion of face-center alignment remains relevant, but this iteration does
not replace the official metric with a custom score.

Both agents submit one valid, editable PartDesign Body/solid: plate in
350.45 seconds / 24 tool calls, tube in 406.45 seconds / 22 calls. The plate
contains seven sketches, two Pads and five Pockets; the tube contains seven
sketches, three Pads, two Revolutions and two Grooves. The final plate's three
local face-distance checks pass. The tube recovers from a failed revolve request;
both agents also recover from requesting an image above the size limit, and
the plate from an unknown operation. Both correct failed feature-count
requirements that used the wrong type spelling. The tube's passing volume
requirement copies its measured volume, so it is not independent drawing
evidence. These errors and validation calls remain in the ledger.

The [final-attempt ledger](dimension-witnesses-2026-10-30.json) and
[native files/previews](artifacts/dimension-witnesses-2026-10-30/) preserve the
submissions and actual image evidence. There is no manual model repair or
selection of scores across versions. One attempt on each of two known tasks
cannot establish reliability or separate the effects of the new raster probe,
arrow guidance and model sampling. It demonstrates a successful reading and
construction in this run, not general recognition of dimension semantics.

## First attempt: consistent coordinates are not enough

Product `08a4ef1cc2da570ebeb9ef5f667da331725277b4` adds source-coordinate
anchors and a linked dimension graph. The fresh plate scores **32.44/100**,
the tube **66.89**, mean **49.67**. Both submitted within 900 seconds:
375.53 seconds for the plate and 425.30 for the tube. These are unmodified
canonical task rewards, not manually repaired models.

The plate supplied section callouts before modeling, including both proposed
dimension endpoints and named surfaces. It still attached 1.5 mm to the floor,
derived 3.5 mm main thickness and 2.1 mm boss projection, and built exactly
that interpretation. Its final plane levels are `[0, 2.1, 3.6, 5.6]` mm.
The three equations and every supplied projected endpoint agree, so the graph
passes. It explicitly returns `semantics_verified=false`; no calculation can
establish that these self-supplied coordinates are actual arrow tips.

The geometric component is 0.19789, specification 0.9 (36/37), and volume
differs by 18.454%. This small score increase over 30.77 does **not** resolve
the dimension assignment. The tube again corrects its handedness during the
run and receives 0.668902, with geometry 0.50252 and specification 1.0 (12/12).
Its face-center alignment component remains 0.005, as in the previous report.

The [first-attempt ledger](dimension-anchors-2026-10-30.json) preserves every
image call and its evidence metadata, agent messages, measurements, scorer
details and artifact hashes. Both [native parts and previews](artifacts/dimension-anchors-2026-10-30/)
are retained. The tube recovered from an unknown operation and a request to
measure a nonplanar face; those errors are included. Neither task used an
unexpected tool, changed an immutable stage or received a manual repair.

## The general workflow

`inspect_image` now accepts optional dimension readings: a callout ID, view,
explicit number/unit, two dimension-line endpoints, and the corresponding
named surface points. Source coordinates stay fixed when a crop is rotated.
The output keeps the unmarked original beside the proposed points; an empty
list produces a coordinate guide. The shared Runtime, CLI and MCP paths
preserve the original behavior when this option is omitted.

The checks cover projected endpoint alignment, inconsistent surface labels,
incompatible drawing scales and contradictory dimension cycles. Connected
callouts solve relative levels from their explicit numbers; disconnected
components keep separate origins. Pixel distances never become CAD dimensions.
Agreement is conditional on the readings, and is never presented as recognition
of text, arrows or surface meaning.

The first attempt motivated a further change in
`a6c673b69ca1160f9f2f30284efea629b1a55ad9`: scan the original raster near
the dimension shaft for candidate crossing lines and return a small source
region to inspect. This evidence is independent of the proposed surface
coordinates. It does not classify arrows, pick a witness, correct a number or
alter the graph. Other dimensions, edges, text and hatching can also create
crossings. Low contrast, no detected crossing and an overlong scan are explicit
states, not successful endpoint verification.

General guidance now distinguishes a short dimension's external arrow **tip**
from its broad base and extended shaft. It asks for an unmarked, horizontally
rotated close-up, tracing both tips to their witness lines before accepting the
surface association. These instructions and the implementation contain no
benchmark IDs, answers, known dimensions, surface coordinates or reference
geometry. Test fixtures use unrelated synthetic dimensions and cover both
black-and-white and colored external arrows in both orientations.

## Protocol and evidence boundaries

Both versions use gpt-6.1-sol through Codex CLI 0.163.0, requested xhigh effort,
900 seconds per task, concurrency two, and the same public PNG hashes and
prompt adaptation. FreeCAD is 1.1.4 / OCCT 7.8.1; the validator is 0.6.0 with
the unmodified v2 task scorer. `pilot.py` and `stage_server.py` are unchanged.
The two product SHAs are frozen before their respective runs.

Only original public images and instructions enter each fresh model workspace.
Scripts, shell, web and other MCP servers are disabled. Previous attempts,
grader/reference models, scores and parent-side diagnosis remain outside it.
No benchmark input images or annotated copies are redistributed in this PR.
Generated native CAD files and their previews are our outputs.

Raw first-attempt evidence is at
`D:\Projects\bench-data\cadbench-v3-anchor-retest-20261030`;
the second run uses `D:\Projects\bench-data\cadbench-v3-witness-retest-20261030`.
Their workspaces are under the matching names in `D:\Projects\bench-ws`.
Parent-only inspection material stays in
`D:\Projects\bench-data\cadbench-v3-dimension-anchors-20261030`.

These are known development tasks, not unseen evaluation or an official
leaderboard submission. Each product version gets one fresh attempt per task;
both versions' results must be reported, without selecting the best task from
different runs. The original six-task mean and all earlier reports remain
unchanged. Official packaging and protocol gaps remain as listed in the
[adapter README](README.md#differences-from-a-leaderboard-run).

## Verification

The final product passes **529 tests, 6 optional CadQuery tests skipped** in
422.67 seconds, excluding unrelated AutoCAD live integration tests. The earlier
anchor-only product passed 524 tests with the same six skips. Focused image,
anchor and harness checks passed; the final 21 anchor tests include inconsistent
surface assignments, derived gaps, cycles, units, rotations, independent raster
crossings, unreadable scans, resource bounds, malformed inputs and real CLI/MCP
round trips. No benchmark drawing or answer is used as a test fixture.

For all four submissions, the archived native bytes match the immutable saved
stages, the public images match the frozen baseline hashes, and read-only final
validation leaves the native files unchanged. All four final previews were
visually inspected. Earlier reports and artifacts remain unchanged.

Main subsequently advanced to `bced013` with the independent BenchCAD 2 runner
and tests. Integration preserves both appended memory entries; it changes none
of this experiment's product code, harness, scores or submitted files. On the
integrated branch, all affected image, dimension, CADBench pilot and new
BenchCAD 2 checks pass: **82 passed, 2 optional CadQuery tests skipped** in
16.07 seconds. The 529-test full-suite result above precedes this main update;
it is not represented as a full run of the newly expanded suite.

Independent review then found that a global fifth-percentile ink estimate can
discard clear one-pixel lines occupying under 5% of the probe. Commit
`2bdc67593fff85641b8f0affaa25e9241757c725` falls back to the darkest sample
only when that estimate reports insufficient contrast; continuous crossing
runs still reject isolated speckles. Four new synthetic cases cover black and
gray lines in both orientations. The integrated focused suite now passes
**86 tests, 2 optional CadQuery skips** in 14.32 seconds.

This robustness fix is after the model attempts and does not change their
recorded product pins. A [read-only replay](sparse-raster-replay-2026-10-30.json)
of all **20 successful image calls** from the final attempt returns identical
recorded source, crop, dimension and panel metadata, including the plate's
section graph. Source and submitted native hashes remain unchanged. This is
a tool-output regression, not another model attempt or a new benchmark score.
