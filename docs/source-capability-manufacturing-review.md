# Source-capability manufacturing follow-up, 2026-10-31

**Repaired-source result:** see the [290ced3 reassessment](source-capability-recheck.md). The older record below remains superseded.

**Superseded during publication review.** The final review reproduced two further
false successes at `6699109`: fully transparent dimension text was certified as
visible, and scientific notation below one used an excessively wide display
tolerance. Under the frozen rubric C2 is capped at 2 until fixed and retested;
the stored 100 below is no longer a valid current conclusion. The original
assessment and archive remain unchanged. The repaired-version reassessment is linked above.
See the [independent findings](https://github.com/lizaixi01/AgentCAD/pull/44#issuecomment-6531147172).

**AgentCAD 100/100; AutoCAD MCP Pro 93/100**, assessed by a separate AI reviewer
under the unchanged [local rubric v1](source-capability-rubric.md). AgentCAD requested
and publishes this assessment. It is a comparison of two pinned sources, not an
official upstream rank or external certification. The source score is separate
from the original v8 execution result of **31/31, 100/100**.

| Category | Weight | AgentCAD | AutoCAD MCP Pro |
|---|---:|---:|---:|
| Functional CAD coverage | 25 | 25 | 24 |
| Correctness and delivery | 20 | 20 | 17 |
| Backends and platforms | 15 | 15 | 15 |
| Engineering production | 15 | 15 | 15 |
| Tests and maintenance | 15 | 15 | 14 |
| Security and operations | 10 | 10 | 8 |
| **Total** | **100** | **100** | **93** |

The [unaltered independent assessment](../examples/source_capability/results/2026-10-31/assessment.json)
contains 20 item judgments for each product, source references, counterexamples,
evidence hashes and limitations. A score of 100 means every bounded item met the
rubric's highest evidence anchor; it is not a percentage of all CAD features,
proof of universal correctness or permission to manufacture an unchecked drawing.

## Fixed versions and the change from 98 / 96

- AgentCAD: [`6699109`](https://github.com/lizaixi01/AgentCAD/tree/66991092973496b148da45b1f847ddb1a8b4999d).
- Pro and the unmodified upstream evaluator: `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`.
- Version-performance baseline: `69c1425a2dd7465f6f8c092033447b608554a8a3`.
- [Independent product review](https://github.com/lizaixi01/AgentCAD/pull/44#issuecomment-6529726990):
  278 related tests and original counterexample/control replays passed at this source.

The [2026-10-30 assessment](source-capability-review.md) remains unchanged at 98 / 96.
AgentCAD's former E1 and E2 gaps now have a checked M14 nominal row and saved,
readable manufacturing annotations. The new review also exposed a previously
missed correctness problem in **both** products: a 6.4 diameter initially rendered
with DIMDEC=0 prints 6, while verification claimed the displayed value was 6.4.
The same original DXF bytes and a valid precision control were replayed against
both pinned products. AgentCAD now reads the saved visible text and rejects this
case. At the unchanged Pro source it remains a false success, so the frozen rubric
caps C2 at 2 (previously 5). Its other deductions remain F3 −1, T3 −1 and S1 −2.

Pro's resulting local 93 is a **new assessment**, even if numerically equal
to its separately published **93/100 v1.6.0 self-review, 2026-09-24**. The old 96
was not a newer Pro release being downgraded by performance; additional evidence
changed the local judgment. These scores cannot be combined with the eight other
upstream projects, which were not re-assessed, to claim an official overall first.

## M14 and mechanical production

M14 uses the washer-free hexagon-socket-head **24 mm counterbore diameter and
15 mm depth** in GOST 12876-67, amendment 4 (1983), figure 4 / table 4. New output
replaces the previously unverified 14.6 mm depth. The 15.5 mm through hole retains
its separate ISO 273 medium-series source. This is an explicitly mixed-reference
nominal drawing; the source's full tolerance, corner and chamfer requirements are
not certified. See the [source audit and scan fingerprint](standard-tables.md#m14-interpretation-and-limits).
Downloaded standards and Autodesk sample drawings are not redistributed.

Mechanical assemblies now annotate supplied segment/overall lengths, every distinct
outer/bore diameter, and hole quantity, diameter, pitch circle, spacing and starting
angle. Front/end/section readback checks actual source geometry, native DIMENSION
definitions, visible text, ownership and required roles. Missing or altered
annotations block strict delivery. Large records use owned XRECORD storage and
DXF parity follows their contents; a 100-hole case survives real DWG roundtrip/AUDIT.
Binary DXF backend intermediates retain double precision at large coordinates.

The generic dimension path also reads actual saved display values. Missing,
hidden or ambiguous text does not become a verified value by inference from
geometry. Numeric suffixes and nominal stacked fractions are distinguished from
deviation stacks. Zero DIMRND preserves DIMDEC precision after redraw. Two-line
angles use the arc-selected sector and ignore linear scale/format variables;
AutoCAD independently regenerated all four sector controls. Non-decimal angular
formats without a unit-aware reader remain explicitly unverified.

No unspecified hole depth, machining process, surface finish or tolerance is
invented. Caller-provided view positions still matter; this is not universal
automatic sheet arrangement or a complete manufacturing release.

## Verification and production evidence

All five lanes collected the same **823 test IDs**, without failures or errors.
The eight local skips require unavailable CadQuery; skips never count as passes.

| Environment | Passed | Skipped |
|---|---:|---:|
| Local Windows 3.11; AutoCAD 2027 / FreeCAD 1.1.4 | 815 | 8 |
| macos-latest-py3.12 | 673 | 150 |
| ubuntu-latest-py3.10 | 652 | 171 |
| ubuntu-latest-py3.12 | 673 | 150 |
| windows-latest-py3.11 | 724 | 99 |

The [completed CI run](https://github.com/lizaixi01/AgentCAD/actions/runs/41101708770) and
[verification summary](../examples/source_capability/results/2026-10-31/verification-summary.json)
retain per-test status and skip reasons. The archive matches local raw source
hashes and CI's LF sources to the pinned Git blobs, recording CI's merge checkout
separately. Both local public-MCP and Linux 3.12 CI runs pass the untouched original
v8 matrix and its additional all-31-must-pass gate.

The [production report](../examples/source_capability/results/2026-10-31/showcase-report.json)
uses two structurally different mechanical assemblies, architecture, P&ID and a
toleranced bore. Seven saved PDFs were separately rendered and visually inspected;
the report retains exact input specs, calls, outputs, native jobs and hashes.
Mechanical, mechanical-variant and tolerance delivery quality is **94**, with two
undefined-VIEWPORTS-layer warnings each; architecture/P&ID quality is **100**.
Those drawing-quality numbers are neither the source score nor the v8 score.

The native mechanical witness activates the actual A3 layout with CTAB/REGENALL;
raw inactive viewport id/status 0/0 is retained alongside the active 2/2 witness.
PDFs are produced by AgentCAD's exporter, not an Autodesk PDF driver. Visual
inspection and structural checks have separate scopes. Windows native evidence
does not establish native AutoCAD or FreeCAD behavior on Linux/macOS.

## Same-environment version comparison

One excluded warm-up and five measured trials per version/count ran in alternating
order in fresh processes. All **24 observations** independently verified endpoints,
entity counts, units and DXF audit. Total create/export/reopen/check medians:

| Synthetic lines | Baseline `69c1425` | Candidate `6699109` | Candidate / baseline |
|---|---:|---:|---:|
| 2,000 | 2.824 s | 2.869 s | 1.016 |
| 10,000 | 53.718 s | 48.622 s | 0.905 |

[Raw timings](../examples/source_capability/results/2026-10-31/performance.json) measure
these line workflows within AgentCAD. They do not establish statistical significance,
general CAD speed or a speed advantage over Pro.

## Retained failures and reproduction

The [new evidence archive](../examples/source_capability/results/2026-10-31/README.md)
preserves earlier failures and superseded passes, including FreeCAD's lost final
progress event, XRECORD/native precision failures, altered geometry and annotation
counterexamples, the completed `760a2c2` run preceding discovery of the generic
verification defect, `fd6d45f`'s 755 passed / 8 skipped / 1 failed regression, and
`953c3f0`'s 30/31 v8 result with its intentionally interrupted native regression.
The final version fixes the underlying contracts; old test expectations and
original evaluator inputs/scoring were not weakened to erase failures.

The new main-line legacy-lock deletion race was separately reproduced and removed:
old non-cooperating markers require offline manual handling, while modern OS locks
and transaction crash recovery remain automatic. A Windows test-launcher exit race
is retained with actual writer PID evidence; the lock correctly remained held until
the writer itself exited.

Follow the [reproduction commands](../examples/source_capability/README.md) using
the exact product and evaluator commits above. Earlier published archives, figures
and measurements remain accessible unchanged. Later publication/main-line changes
are not silently relabeled as this pinned source measurement.

Later [main-line integration regression](../examples/source_capability/results/2026-10-31/integration-1041de9/summary.json) at `1041de9`: **823 passed / 8 skipped**, with no failures or errors. This check includes subsequent installer/viewer changes and does not relabel the scored `6699109` measurement.
