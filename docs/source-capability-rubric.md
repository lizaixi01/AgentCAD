# Local source-capability review rubric v1

Defined before assigning final product scores, 2026-10-30, from an independent
reviewer's proposal. It preserves the six category weights of
[U-C4N's source review](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks/source_review.json).
That upstream review publishes narrative grounds and category totals, but no
point-by-point scoring anchors. This document supplies **local** anchors; it is
not an upstream-approved scoring rule. Apply the same anchors to both pinned
repositories. Do not convert v8's execution score into a source-review score.

Each item below receives an integer 0–5; sum items within the original categories.
Anchors are cumulative:

| Score | Required evidence |
|---:|---|
| 0 | No verified implementation. |
| 1 | Real entry point, but a key ordinary capability is absent. |
| 2 | Ordinary path works with output evidence. |
| 3 | Ordinary, error and boundary cases have behavioral evidence, without false success. |
| 4 | Fixed-version complete workflow is reproducible; saved/reopened or cross-interface/process postconditions are independently checked. |
| 5 | In addition, structurally different cases outside a fixed benchmark and the applicable real backend/protocol are verified, with no unresolved serious defect in that contract. |

A serious demonstrated false-success, destructive-write or permission defect caps
the responsible item at 2 until fixed and retested. Skips are not passes. Historical
results count only when the relevant code boundary is traced. Tool counts, test
counts, stars and unsupported promises earn no points. Do not require every CAD
feature or formal certification; assess the declared, useful capability contract.
Do not narrow a contract after finding a failure. Distinctive capabilities such as
parametric 3D are described separately, not used to silently change the weights.

| Category / weight | ID | Item and boundary |
|---|---|---|
| Functional coverage / 25 | F1 | Geometry and measurement: primitives, curves, polylines, hatch/islands, length/area/topology. |
| | F2 | Editing: transforms, arrays, trim/join/offset/fillet, requirement-driven changes and identity. |
| | F3 | Annotation/styles: dimensions, text/styles, numeric tolerances/fits and actual display after editing. |
| | F4 | Organization/exchange: layers, blocks/attributes, model/paper, viewports/pages, DXF/DWG/print/tables. |
| | F5 | Domain workflows: P&ID, mechanical views/BOM, architectural rooms/openings, foreign drawing understanding and provisional takeoff with uncertainty. |
| Correctness and delivery / 20 | C1 | Transactions: failed batches, preview, conflicts, checkpoints/undo and file state on exceptions. |
| | C2 | Intent/geometry: saved specifications, dimensions vs actual geometry, fake values, omitted edits and tampering. |
| | C3 | Delivery: gates, source version/hash, readback, DXF semantic parity and explicit per-format check scope. |
| | C4 | Foreign/abnormal inputs: corruption, unknown entities/units, unsupported features, external edits and incomplete data. |
| Backends and platforms / 15 | B1 | Backend contract: discoverability, missing dependencies, capability boundaries and consistent postconditions. An independent COM implementation is not required. |
| | B2 | Native interoperability: real save/read/edit/AUDIT, representative dimensions/layouts/domains. |
| | B3 | Platforms: actual Windows/Linux and multiple-Python runs; native and headless evidence distinguished. |
| Engineering production / 15 | E1 | Standard data: sources, editions, ranges, boundaries, unknown-value refusal and no false certification. |
| | E2 | Drawing production: specification/model views/sections/dimensions/frame/BOM, saved parity and visual readability. |
| | E3 | Domain loop: connections, room area, BOM/balloon/quantities readback, real error gates and uncertainty. |
| Testing and maintenance / 15 | T1 | Behavioral regressions: unit/interface/process/integration and adversarial tests. |
| | T2 | Reproducibility: locked dependencies, fixed product/evaluator, environment/hashes and generated docs. |
| | T3 | Continuous verification: completed CI, failing reports fail gates, same-environment correctness/performance comparison between versions. |
| Security and operations / 10 | S1 | Defaults: paths, read-only and operation scopes, dangerous execution disabled, HTTP authentication/origin/input boundaries. |
| | S2 | Long tasks: locks, concurrency, cancellation, timeouts, crash/recovery and observable logs. Trusted opt-in scripts are not advertised as a hostile-code sandbox. |

Every awarded score and deduction must cite concrete evidence and its limits.
Publish the original Pro **93/100 (v1.6.0, 2026-09-24, upstream self-review)**
separately from any current local re-evaluation. Different assessors/anchors do not
establish an official leaderboard position or a precise cross-review score delta.
