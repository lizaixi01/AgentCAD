# Six-category source-capability review, 2026-10-30

This review assesses AgentCAD's source and reproducible behavior against the same
six categories used by U-C4N's source-capability chart. It is a **local independent
AI review**, requested and published by the AgentCAD project, not an upstream
certification or official leaderboard entry.

The upstream chart's **93/100** is Pro's published v1.6.0 self-review dated
2026-09-24. It publishes six category totals and narrative grounds, but no unique
per-point calculation. Our [rubric v1](source-capability-rubric.md) therefore freezes
20 explicit cumulative anchors before scoring and applies them to both products.
Neither a v8 score of 100 nor a different assessor's total can be substituted for
the upstream 93. This comparison names the method and pinned revisions.

## Scores and deductions

| Category | Weight | AgentCAD `b4c0466` | Pro `58a05dd` |
|---|---:|---:|---:|
| Functional CAD coverage | 25 | 25 | 24 |
| Correctness and delivery | 20 | 20 | 20 |
| Backends and platforms | 15 | 15 | 15 |
| Engineering production | 15 | 13 | 15 |
| Tests and maintenance | 15 | 15 | 14 |
| Security and operations | 10 | 10 | 8 |
| **Total** | **100** | **98** | **96** |

The [independent assessment](../examples/source_capability/results/2026-10-30/assessment.json)
records all 40 item scores, fixed-source references, evidence paths and limits.
AgentCAD leads these two fixed products by two points under rubric v1. This does
not establish an official upstream rank or a five-point improvement over Pro's
historical 93: that result used another version, assessor and scoring detail.

AgentCAD's deductions are **E1 −1** for the offered M14 counterbore whose legacy
dimensions remain unverified against a normative row, and **E2 −1** because the
mechanical template does not automatically annotate its specified OD, bore, pitch
circle and hole pattern completely. Honest disclosure preserves useful behavior
but does not earn the missing evidence or production point.

Pro's deductions are **F3 −1** because headless `dimstyle_modify` leaves existing
rendered dimension blocks unchanged until an additional redraw; **T3 −1** because
the published version-performance comparison predates changes to relevant product
paths and no comparison at the final source boundary was found; and **S1 −2** for
incomplete default path/operation restriction and lack of retained real-request
HTTP refusal/no-write evidence. These are the review's scoped findings, not an
assertion of an exploit. Its floating-dependency CI failure checked the recorded
ezdxf version, so it is not counted as a geometry regression. Historical native
results were credited after tracing the unchanged product-code boundary.

## Fixed products and evidence

- AgentCAD product: `b4c04669238e771a0888114f1af3260d7c371834`.
- AutoCAD MCP Pro source: `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`.
- Original v8 evaluator: the same Pro repository commit; original task IDs, inputs,
  scoring and runner unchanged. AgentCAD executes through the real public MCP.
- Same-environment version comparison: AgentCAD main `a713426` versus `b4c0466`;
  this measures regressions within AgentCAD, not speed against Pro.
- [Independent product/script review](https://github.com/lizaixi01/AgentCAD/pull/41#issuecomment-6521845577)
  found no remaining blocker after fixes and 172 targeted tests. Final score and
  archive review are separately recorded.

## Verification

All five regression lanes collected the **same 693 test IDs**, with no failures
or errors. Their differing optional dependencies explain the separate skip counts:

| Environment | Passed | Skipped | Scope |
|---|---:|---:|---|
| Local Windows, Python 3.11 | 685 | 8 | AutoCAD 2027 and FreeCAD 1.1.4 enabled; eight CadQuery-dependent cases skipped |
| Windows CI, Python 3.11 | 600 | 93 | Portable/headless CI |
| Linux CI, Python 3.10 | 528 | 165 | Portable/headless CI |
| Linux CI, Python 3.12 | 549 | 144 | Portable/headless CI |
| macOS CI, Python 3.12 | 549 | 144 | Portable/headless CI |

The [completed CI run](https://github.com/lizaixi01/AgentCAD/actions/runs/41049567713)
is bound to PR head `b4c0466`. CI tests its merge with base `a713426`; the product
source was independently matched to the pinned head. Local native tests took
544.92 seconds. The [verification summary](../examples/source_capability/results/2026-10-30/verification-summary.json)
retains per-test skip reasons and raw JUnit hashes. Skips are never credited as passes.

The untouched upstream v8 evaluator completed **31/31, 100/100** both locally
through the public MCP and in Linux Python 3.12 CI. Reports record clean source
state and all 67 product-file hashes. This is execution evidence, separate from
the source-capability score.

The same-environment version comparison used one excluded warm-up and five
measured trials per version/count, alternating order in fresh processes. All
**24 observations** passed independent endpoint, entity-count, units and DXF-audit
checks. Median create + export/reopen/verify times were:

| Synthetic lines | Main `a713426` | Candidate `b4c0466` | Candidate / baseline |
|---|---:|---:|---:|
| 2,000 | 2.777 s | 2.597 s | 0.935 |
| 10,000 | 45.657 s | 45.314 s | 0.992 |

These [raw observations and medians](../examples/source_capability/results/2026-10-30/performance.json)
show no observed median regression in these cases. They do not establish
statistical significance, general CAD performance or speed relative to Pro.

## Concrete gaps repaired

Strict delivery now restores stored requirements and combines domain critique with
all-layout integrity checks. A changed bore, false room-area label, stale BOM or
broken balloon link cannot pass by bypassing the relevant reader. Native domain
records outside Model are rejected as unsupported. Format-specific artifact
checks compare DXF semantics and tabular cells/relationships; PDF/SVG checks retain
their explicit structural scope. The manifest binds outputs to the source hash.

Numeric tolerances use native DIMENSION variables, retain precision after edits,
and are checked in nested, unused and paper-space blocks. Non-finite factors are
refused in both limits and deviations modes. Stacked text has readable spacing.
H7/h6/g6 fit values have a sourced, tested range; the rest of the dimensional library
now carries [audited provenance and exceptions](standard-tables.md).

Foreign plant takeoff now uses actual finite arcs for junctions and nearby labels.
The independent review's chord false-junction example no longer merges disjoint
networks. Unassigned electrical callouts retain explicit unknown lengths instead
of raising an internal error. Preliminary routing estimates keep their uncertainty.

Writable HTTP defaults to loopback and requires authentication for remote binding,
validates request boundaries and rejects browser Origin requests. OS-held writer
locks survive long jobs without age-based lock stealing and release on process
exit. Cross-platform dependencies are locked; regressions and generated-doc checks
run in four completed CI lanes. The Ubuntu 3.12 lane additionally runs the original
full v8 gate. Python 3.10 configuration and real MCP image responses have behavioral coverage.

## Native and visual scope

The [production reproduction script](../examples/source_capability/showcase.py)
uses fresh synthetic inputs, public Runtime calls, independent numeric readback
and real AutoCAD DWG conversions/AUDIT. It demonstrates a three-step sleeve and
six-hole cap, room plan with openings/schedules, a control-loop P&ID and a toleranced
bore. The A3 paper size, viewport centres/scale and paper-space annotation survive
the DWG roundtrip.

The mechanical witness activates the actual AutoCAD layout with CTAB/REGENALL,
saves a new DXF and then uses **AgentCAD's PDF exporter**. It is not an AutoCAD
PDF-driver plot. Inactive layout viewports can return id/status zero; activation
is a required step for this witness, not an automatic recovery guarantee.

PDF page images were visually inspected, and an independent reviewer re-rendered
all five retained PNGs from their PDFs with identical pixels. Mechanical and
tolerance delivery manifests score **94**, with two undefined-VIEWPORTS-layer
warnings each; architecture and P&ID score **100**. These internal drawing-quality
scores are separate from the source score and from v8. They must not be presented
as four warning-free deliveries.

The mechanical template has readable views, section, axial dimensions, frame,
BOM and balloons; it does not automatically annotate all manufacturing-critical
diameters and hole patterns. The example is not a complete manufacturing release.
M14 counterbore dimensions remain an explicitly unverified engineering recommendation.
PDF/SVG structural checks are not full visual equivalence. Native Windows results
do not establish native AutoCAD/FreeCAD behavior on Linux or macOS.

## Reproduction and historical continuity

[Commands and evidence policy](../examples/source_capability/README.md) explain
fixed versions, lock installation, native activation, same-environment comparison,
failure retention and import-path verification. Historical trials, the original
31/31 evidence, Pro's source 93 and all old charts remain unchanged. This assessment
adds a new record; it does not relabel earlier measurements or award an upstream rank.

The [result index](../examples/source_capability/results/2026-10-30/README.md)
links the assessment, raw reports, five inspected previews and a permanent evidence
archive. Its manifest hashes every archived file without newline normalization.
CI artifacts are retained there independently of GitHub's expiration policy.

The figure in [benchmarks.md](benchmarks.md#source-capability-comparison) is drawn from the final assessment and the pinned upstream rows
in [data.json](assets/mcp-benchmark/data.json). It shows the rubric-v1 pair and
U-C4N's published board as separate panels and never ranks them together:

```
python docs/assets/source-capability/make_chart.py
python docs/assets/source-capability/make_chart.py --check
```
