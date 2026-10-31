# Source-capability repair and reassessment, 2026-10-31

**AgentCAD 100/100 · AutoCAD MCP Pro 93/100**, under the unchanged [local rubric v1](source-capability-rubric.md).
A separate AI reviewer assessed both pinned sources; AgentCAD requested and
publishes the review. This is a local comparison of two products, not an official
upstream leaderboard or external certification. The original v8 execution score
is a separate result: **31/31**, tied with Pro.

| Category | Weight | AgentCAD | AutoCAD MCP Pro |
|---|---:|---:|---:|
| Functional CAD coverage | 25 | 25 | 24 |
| Correctness and delivery | 20 | 20 | 17 |
| Backends and platforms | 15 | 15 | 15 |
| Engineering production | 15 | 15 | 15 |
| Tests and maintenance | 15 | 15 | 14 |
| Security and operations | 10 | 10 | 8 |
| **Total** | **100** | **100** | **93** |

The [original independent assessment](../examples/source_capability/results/2026-10-31-recheck/assessment.json)
records every item, source pin, evidence hash and limitation. A score of 100 means
the 20 bounded items met this rubric's highest evidence anchor. It is not a claim
that every CAD feature exists, that all inputs are correct, or that a drawing is
authorized for manufacture.

## Fixed sources and correction history

- AgentCAD: [`290ced3`](https://github.com/lizaixi01/AgentCAD/tree/290ced3033f85e1fc97611cf1c920d922524bc3a).
- Pro and the unchanged original v8 evaluator: `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`.
- Version-performance baseline: `69c1425a2dd7465f6f8c092033447b608554a8a3`.
- [Independent code re-review](https://github.com/lizaixi01/AgentCAD/pull/44#issuecomment-6531683436)
  passed the repaired source; the separately retained scoring review evaluates the
  complete evidence and is not substituted by that code verdict.

The earlier [98 / 96 review](source-capability-review.md) remains historical.
The first manufacturing follow-up at `6699109` assigned 100 / 93, but final
publication review demonstrated further false successes. Its assessment, archive
and measurements are [retained with a superseded notice](source-capability-manufacturing-review.md).
Those old passing runs do not establish the correctness of the repaired version.

The new review replays the actual failing files and normal controls, including:

- Fully transparent dimension text: generic verification, manufacturing readback
  and strict delivery now reject it. Entity, layer and block transparency are
  resolved with the parent dimension; explicit opaque child overrides remain valid.
- Renderer inheritance: SVG export, the viewer and PDF drawing share a dimension
  context, so layer-zero child text inherits the actual parent layer. Tests inspect
  actual rendered text paths, and the reviewer checked PDF content and pixels.
- Small scientific values: display precision follows physical magnitude and
  DIMDEC, without a decimal-format floor or a tolerance enlarged by forged text.
  Physical zero receives no fabricated nonzero magnitude; explicit DIMRND retains
  its declared role. Ordinary validation and strict delivery reject the retained
  bad-value cases; normal controls remain accepted.

Independent targeted validation retains its initial temporary-path test failure:
`test_demo_icon` matched the substring `viewer` in the review directory name.
The product and test were unchanged; rerunning that one case under a neutral
temporary root passed. Initial fixture mistakes, the interrupted `f1eb298` native
run and all original counterexamples are retained, not counted as successful runs.

Pro's local 93 is assessed at the same fixed `58a05dd` source under
the same rubric. The previously reproduced first-rendering precision false success
still caps C2; the local deductions remain F3 −1, C2 −3, T3 −1 and S1 −2. Pro's
separate **93/100 v1.6.0 self-review (2026-09-24)** uses different scoring detail.
Equal numbers do not make the two assessments interchangeable, and neither is
combined with unreviewed upstream projects to claim an official overall first.
The seven other public servers were later scored under this rubric in a separate
[field review](../examples/source_capability/results/2026-10-31-field/README.md),
from source, committed results and CI, without running their code.

## M14 and manufacturing annotations

M14's **24 mm counterbore diameter and 15 mm depth** are checked against GOST
12876-67 amendment 4, figure 4 / table 4. The through-hole diameter **15.5 mm**
uses the separate ISO 273 medium series. The output explicitly identifies these
mixed nominal references; full source tolerances, corner radii and chamfers are
not certified. [Reference audit and scan fingerprint](standard-tables.md#m14-interpretation-and-limits)
document the evidence without redistributing standards PDFs.

Mechanical drawings annotate supplied segment and overall lengths, distinct
outside/bore diameters, hole count and diameter, pitch circle, spacing and start
angle. Saved front/end/section geometry, native dimensions, actual visible text,
ownership and required annotation roles are checked together. Missing, altered
or fully hidden required annotations block strict delivery. Large annotation
records use owned XRECORDs; recorded 100-hole/native and precision-boundary cases
remain available through traced historical evidence.

Unspecified hole depth, machining process, surface finish and tolerances are not
invented. Callers still place views and notes. This is a useful checked drawing
contract, not universal automatic arrangement or complete manufacturing release.

## Verification and production evidence

All five lanes collected the same **893 test IDs**, with
zero failures or errors. Local native testing ran in an isolated checkout with
AutoCAD 2027 and FreeCAD 1.1.4 enabled; its 8 skips require unavailable
CadQuery. Skips never count as passes.

| Environment | Passed | Skipped |
|---|---:|---:|
| Local Windows 3.11; AutoCAD 2027 / FreeCAD 1.1.4 | 885 | 8 |
| macos-latest-py3.12 | 741 | 152 |
| ubuntu-latest-py3.10 | 720 | 173 |
| ubuntu-latest-py3.12 | 741 | 152 |
| windows-latest-py3.11 | 792 | 101 |

[Completed CI](https://github.com/lizaixi01/AgentCAD/actions/runs/41114528669) ·
[Per-test statuses and reasons](../examples/source_capability/results/2026-10-31-recheck/verification-summary.json).
Four original Actions ZIP digests match GitHub's recorded digests. CI's merge
checkout `884ac93` has exactly the same Git tree as `290ced3`; local raw source
hashes and CI LF blobs are checked separately. Local public-MCP and Linux 3.12 CI
runs both passed the untouched v8 matrix and its explicit all-31-must-pass gate.

The [fresh production report](../examples/source_capability/results/2026-10-31-recheck/showcase-report.json)
retains 40 Runtime calls, seven passed checks, five real DWG/readback/AUDIT workflows
and two A3 activation witnesses. Two distinct mechanical assemblies, architecture,
P&ID and a toleranced bore produce seven one-page PDFs, independently rendered
and [visually inspected](../examples/source_capability/results/2026-10-31-recheck/visual-review.md).
The native witness uses actual CTAB/REGENALL/DXFOUT; inactive viewport 0/0 and
active 2/2 records remain raw, without ID patching.

Mechanical, mechanical-variant and tolerance delivery quality is **94**, retaining
two undefined-VIEWPORTS-layer warnings each; architecture/P&ID quality is **100**.
These drawing-quality values are separate from source and v8 scores. PDFs use
AgentCAD's exporter, not Autodesk's PDF driver. The appearance checks establish
visible text and the tested inheritance behavior, not exact intermediate opacity
intensity across every output format. Native Windows results do not establish
AutoCAD/FreeCAD execution on Linux or macOS.

## Same-environment version comparison

One excluded warm-up and five measured observations per version/count ran in
alternating order, in fresh processes with the same interpreter and dependencies.
All **24 observations** independently passed endpoint, count, unit and DXF-audit
checks. Total create/export/reopen/check medians:

| Synthetic lines | Baseline `69c1425` | Candidate `290ced3` | Candidate / baseline |
|---|---:|---:|---:|
| 2,000 | 2.634 s | 2.625 s | 0.997 |
| 10,000 | 46.057 s | 45.748 s | 0.993 |

These are narrow synthetic version measurements on this machine, not a speed
comparison with Pro or a general speed claim. [Raw observations and environment](../examples/source_capability/results/2026-10-31-recheck/performance.json)
preserve every sample, including the excluded warm-ups.

## Reproduce and inspect

[Reproduction commands](../examples/source_capability/README.md) apply after
checking out the fixed product source above. Use separate empty output directories
and run AutoCAD serially. The [new evidence directory](../examples/source_capability/results/2026-10-31-recheck/README.md)
provides the unchanged independent assessment, raw evidence, previews and full
SHA-256 manifest. Its two sealed companion archives supply explicitly indexed
historical evidence; no previous measurement is overwritten or relabeled.
