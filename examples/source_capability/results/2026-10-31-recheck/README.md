# Repaired source-capability assessment — 2026-10-31

**AgentCAD 100/100 · AutoCAD MCP Pro 93/100**, under the unchanged
[local rubric v1](../../../../docs/source-capability-rubric.md). Separate AI review
requested and published by AgentCAD; this is not an official upstream ranking.
Product: `290ced3033f85e1fc97611cf1c920d922524bc3a`. Pro/evaluator:
`58a05ddfc34a9832c626e82cd88ecdce8e16a62a`.

| Record | Content |
|---|---|
| [Assessment](assessment.json) | Unchanged independent judgments for both products and indexed evidence |
| [Reviewer report](assessment-review.md) | Independent final verdict and limits |
| [Detailed report](../../../../docs/source-capability-recheck.md) | Six categories, repairs, validation and scope |
| [Regression summary](verification-summary.json) | 893 identical test IDs in five lanes; skips kept separate |
| [v8 report](v8-report.json) | Original public-MCP execution: 31/31 |
| [Performance](performance.json) | 24 correctness-checked observations, raw timings and environment |
| [Production](showcase-report.json) | Fresh synthetic examples, native DWG/AUDIT and actual A3 activation |
| [Visual review](visual-review.md) | Seven independently rendered and inspected PDFs |
| [Evidence ZIP](evidence.zip) | 7,141 new retained files, including failures and counterexamples |
| [Manifest](manifest.json) | SHA-256 for archive, every member, standalone files and companion ZIPs |

Local regression: **885 passed / 8 skipped**;
[four completed CI lanes](https://github.com/lizaixi01/AgentCAD/actions/runs/41114528669).
Archive size: 44,196,784 bytes. SHA-256:

```text
fd8787550364038c4dfa8d1cec3f0e0c3c614b2b48cbcc878f0d24a5d7f1bd5b
```

Assessment SHA-256 (copied without edits from the independent reviewer):

```text
a912c553d4f19c7db1b9f6e5a1fa6b2f3f089852ca5f4297abefc6ace1c7a048
```

Extract this ZIP and both sealed companions into the same empty directory:
[2026-10-30](../2026-10-30/README.md) and
[superseded 6699109 review](../2026-10-31/README.md).
New and 6699109 paths start at `output/source-capability-100/`; older paths start
at `output/source-capability/`. The new ZIP does not overwrite either companion's
members. The assessment labels inherited evidence by archive and retains the
invalidated 6699109 conclusion as history, not as the current score.

Machine paths record provenance and are not portable installation requirements.
Hashes cover raw bytes: do not normalize line endings. The manifest excludes
itself and this navigational README. Original synthetic drawings only; standards
PDFs/page renders and Autodesk sample drawings are excluded.

See [reproduction instructions](../../README.md). A rubric score is not complete
CAD coverage or manufacturing certification; Pro's historical self-review 93 and
v8's 31-task score remain separate results.
