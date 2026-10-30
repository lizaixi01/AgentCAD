# Drawing reconstruction: measured face gaps and view correspondence — 2026-10-30

This is the next development iteration after the
[drawing diagnosis](drawing-diagnosis-2026-10-30.md), on the same two public
drawing tasks. It adds checks on the final solid and fixes a concrete inspection
interface defect. Previous runs, manual controls and their scores are preserved.

**The tool changes pass regression, but this fresh pair does not improve the
score.** The mean falls from 50.43 to **48.83/100**. The plate still assigns a
dimension to the wrong surfaces; the tube corrects its handedness.

| Task | Original pilot | Previous upright run | This run |
|---|---:|---:|---:|
| Perforated plate `freecad-6fd69bd0c4` | 29.20 | 34.20 | **30.77** |
| Tube `freecad-686f17ce17` | 52.55 | 66.67 | **66.89** |
| Two-task mean | 40.87 | 50.43 | **48.83** |

Scores are canonical `reward.json` rewards multiplied by 100. Both agents
submitted valid editable native parts within the 900-second limit: plate
468.97 seconds / 29 tool calls, tube 358.26 seconds / 21 calls. No manual repair,
additional attempt or best-of selection is used. Both generated
[native parts and previews](artifacts/section-evidence-2026-10-30/) are archived.

## What the new attempt actually checked

The plate initially used 4.1 mm main thickness and 1.5 mm boss projection, but
read 2 mm as the remaining floor. After more image inspection, it changed to
3.5 mm main thickness, 1.5 mm floor and 2.1 mm boss projection. That reproduces
the previous run's incorrect final layer assignment. The measured plane levels
changed from `[-1.5, 0, 2, 4.1]` to `[-2.1, 0, 1.5, 3.5]` mm.

Unlike the earlier runs, it correctly inspected final faces, measured their
gaps, and used three `face_distance` requirements. Those requirements passed
because the agent assigned **1.5 mm to the wrong face pair**. The measurements
are correct; their drawing-derived interpretation is not. Geometry is 0.18557,
specification 0.9 (36/37), and volume differs by 18.791%. The correct bounding
box still masks the local error. This is evidence against claiming that a
measurement tool alone resolves drawing interpretation.

The tube used the reported view frames and previews, identified an opposite
bend direction, and edited its native sketches before submission. Its final
three views match the drawing's layout. A separate
[post-run probe](artifacts/section-evidence-2026-10-30/tube_latest_probe.json)
now finds the close match under a proper transform rather than a reflection:
maximum sampled boundary discrepancy 0.0284 mm, with volume preserved.
Its official geometry component is still only 0.50252, specification 1.0
(12/12), and the face-center alignment subscore is 0.005. Its final volume
requirement copied an already measured volume, so that particular passing
check supplies no independent evidence of drawing accuracy.

Recovered call errors remain in the ledger: the plate requested an image
larger than the allowed maximum; the tube requested an unknown operation and
mixed two sketch-placement modes. It also corrected an initially invalid
feature-count requirement. There were no unexpected tools or changed stages.

The next accuracy step needs evidence for dimension-line endpoints and their
surface assignments, especially when an agent revises a previously plausible
interpretation. More checks against its own chosen numbers do not supply that
evidence. No task-specific correct numbers have been inserted into the solver.

## A real tool defect in the earlier trajectories

Both earlier plate agents called `inspect_entities` with
`filter={"type":"face"}`. For an FCStd part, the interface silently ignored
`type` and returned feature history: 16 entries in the crop/zoom run and 14 in
the upright run. Those are modeling steps, not the final solid's faces. The
[saved call evidence](artifacts/section-evidence-2026-10-30/filter-misuse.json)
identifies both trajectory hashes and calls.

Unknown FCStd filter keys now fail explicitly with the correct
`filter={"kind":"faces"}` syntax. This corrects misleading inspection behavior;
it does not overturn the earlier finding that successful pads and pockets
executed the requested geometry correctly.

## Measurements that do not trust the construction plan

The existing `measure_entities` interface now also measures native 3D geometry:

- `planar_levels` lists parallel planar faces, their signed positions and gaps.
  It deliberately does not assign meanings such as floor, boss or recess.
- `face_distance` measures perpendicular spacing between two parallel planes.
  Several coplanar faces are allowed, so a family of boss ends can be checked
  together. Noncoplanar or nonparallel selections fail explicitly.
- A `face_distance` validation requirement measures the final Body. It does not
  read a nominal parameter or an intermediate feature's construction history.

A synthetic regression demonstrates why this matters: two different layer
stacks can share the same overall height and nominal boss parameter. Those
checks pass on the wrong stack, while the final-face gap fails. Other tests
cover rotated construction planes, read-only file identity, ambiguous
selections, CLI and real MCP calls, filter errors and preview camera directions.

The new measurement was also applied read-only to the previous plate. Its boss
projection is **2.1 mm**; a **1.5 mm** requirement fails by **0.6 mm**, despite
the correct overall 5.6 mm height. The
[post-run record](artifacts/section-evidence-2026-10-30/plate-local-measurement.json)
contains actual face IDs and the unchanged native hash. This is diagnostic
evidence, not a repaired model or a fresh model score.

General modeling instructions now ask for both surfaces of each dimension,
their extension lines and source view, and a drawing-derived check before
building. Preview results also expose camera direction and screen-right/up
vectors, so an agent can keep one consistent orientation across views. These
instructions contain no benchmark identifiers, dimensions or hidden geometry.

## Tube diagnosis: handedness and a metric limitation

The earlier upright tube's dimensional checks passed, but it was mirrored.
Under the axis correspondence derived from its bend planes, a proper rigid
transform leaves sampled point-to-surface discrepancies around **72.7 mm**.
Allowing a reflection reduces the maximum sampled discrepancy to **0.0284 mm**.
The preceding crop/zoom tube has the opposite result: the proper transform
matches closely and reflection does not.

The [probe and results](artifacts/section-evidence-2026-10-30/tube_surface_probe.json)
are parent-side, post-run diagnostics. The
[script](artifacts/section-evidence-2026-10-30/tube_surface_probe.py) samples five
points per B-rep edge, deduplicates them, and measures distances in both
directions. It uses shape transforms that preserve volume. These are sampled
boundary distances, **not a complete Hausdorff distance, an official score or
proof of identical geometry**.

Even the closely matching crop/zoom tube scores only 66.89. The official v2
comparator aligns face-center point clouds, which depend on how the same
surface is split into faces. The reference has 16 faces and these candidates
have 14. This helps explain why a near match under the diagnostic transform
can still receive a low spatial component; small taper differences also remain.
The official scorer is unchanged, and its reported score is retained. No
reference-specific feature decomposition is prescribed to the fresh agent.

## Protocol and reproducibility

The new product/harness version is
`d9b1f0b68a4ba2a269d26c458063be56371de55f`, based on main
`c85277689b66b5e82e7363096202ca8a1effe0f7`. The base also includes PR #36's
workflow integration, so this experiment does not isolate the causal effect
of each change or model sampling variation. The pilot pins the full tool
profile and explicitly allows the existing measurement tool.

The fixed task IDs, original PNG hashes and prompt adaptation are unchanged.
Each task gets one fresh attempt with Codex CLI 0.163.0, gpt-6.1-sol, requested
xhigh effort, 900 seconds and concurrency two. Runtime versions remain
Python 3.11.16, FreeCAD 1.1.4 / OCCT 7.8.1 and validator 0.6.0's unmodified v2
scorer. Only the public drawing and instructions enter each model workspace;
scripts, shell, web and other MCP servers are disabled. Reference files,
diagnostics, earlier submissions and score feedback stay outside them.

Raw run evidence is in
`D:\Projects\bench-data\cadbench-v3-section-retest-20261030`, with matching
workspace directories under `D:\Projects\bench-ws`. Parent-side diagnostics
are in `D:\Projects\bench-data\cadbench-v3-section-evidence-20261030`.
The [ledger](section-evidence-2026-10-30.json) records the frozen manifest,
tool calls/errors, actual geometry checks, rewards and artifact hashes.
Submitted stages are neither repaired nor replaced after scoring.

These are two known development tasks, not unseen evaluation or an official
leaderboard submission. The original six-task mean is not recomputed by
substituting later attempts. Full protocol work remains as described in the
[adapter README](README.md#differences-from-a-leaderboard-run).

Verification: **504 tests passed, 6 optional CadQuery tests skipped**, excluding
the unrelated AutoCAD live integration tests. The focused geometry/harness
suite also passed (137 passed, 6 skipped). Both archived native hashes match
their immutable stage records, source PNG hashes match the frozen baseline,
and both final previews were visually inspected. Earlier reports and artifact
files remain unchanged.
An empty-face-selector error guard was added after the benchmark; all seven
measurement tests, including that case, passed. It does not change the recorded
run version or any submission.

The first integrated-main suite had 503 passes, 6 skips and one failure in the
unchanged viewer concurrency test, `test_commits_succeed_while_the_viewer_reads`:
a cached DXF could not be read during concurrent viewer requests. The isolated
rerun passed (1 passed, 15.21 seconds). The failure remains recorded; its
intermittent cause has not been established. No viewer code was changed here.
The subsequent complete integrated-main rerun passed: **504 passed, 6 skipped
in 446.34 seconds**, with the viewer test included. Independent PR review also
passed 42 focused measurement, harness and compatibility tests.
