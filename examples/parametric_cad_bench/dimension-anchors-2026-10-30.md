# Drawing reconstruction: dimension endpoints and raster witnesses — 2026-10-30

This continues the [face-measurement iteration](section-evidence-2026-10-30.md)
on the **same two drawing tasks**. It tests a general way to associate dimensions
with physical surfaces, without putting either task's answer in AgentCAD.

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
