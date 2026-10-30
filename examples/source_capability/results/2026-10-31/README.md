# Source-capability follow-up evidence — 2026-10-31

**Repaired-source result:** see the [290ced3 reassessment](../2026-10-31-recheck/README.md). The older record below remains superseded.

**Superseded assessment; retained for audit.** Publication review found transparent
text and scientific-notation false successes at the scored source. The frozen
rule caps C2 at 2 until repaired and retested; the original 100 below must not be
used as the current score. [Findings](https://github.com/lizaixi01/AgentCAD/pull/44#issuecomment-6531147172).
Assessment JSON, evidence ZIP and measurements keep their original bytes.

**AgentCAD 100 / AutoCAD MCP Pro 93**, under the unchanged
[local rubric v1](../../../../docs/source-capability-rubric.md). This is an independent
AI review requested and published by AgentCAD, not official upstream ranking or
external certification. Pro's historical self-review 93 remains a separate result.

| Record | Content |
|---|---|
| [Assessment](assessment.json) | Original independent 40-item assessment, pins, deductions and evidence hashes |
| [Review report](../../../../docs/source-capability-manufacturing-review.md) | Six categories, repaired gaps, verification and limits |
| [Regression summary](verification-summary.json) | 823 identical test IDs in five lanes, with explicit skips |
| [v8 report](v8-report.json) | Original 31/31 public MCP execution |
| [Performance](performance.json) | 24 correctness-checked version observations |
| [Production](showcase-report.json) | Fresh synthetic drawings and real DWG/readback/AUDIT |
| [Visual review](visual-review.md) | Seven PDF previews and separate readability findings |
| [Independent reviewer report](assessment-review.md) | Final assessment verdict and scope |
| [Evidence ZIP](evidence.zip) | 13,888 retained files, including failed development trials |
| [Manifest](manifest.json) | SHA-256 for ZIP, every member and standalone evidence |

Product: `66991092973496b148da45b1f847ddb1a8b4999d`. Pro/evaluator: `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`.
Local native regression: **815 passed / 8 skipped**.
[Completed CI](https://github.com/lizaixi01/AgentCAD/actions/runs/41101708770); each platform's optional skips are separately recorded.

ZIP size: 80,192,184 bytes. SHA-256:

```text
32762eea5694ac57e236964da41ee55803ebaabf817624a37c9a1cec9793ed5a
```

The independently authored assessment is copied unchanged. SHA-256:

```text
836fbcf8dbf07d2b85eb42e78f11dffd779b2283b220caaaa3d178475df177d8
```

Extract this archive alongside the unchanged [2026-10-30 archive](../2026-10-30/README.md).
New paths start at `output/source-capability-100/`; inherited paths remain under
`output/source-capability/`. Original machine paths are provenance, not portable
installation requirements. Hashes cover raw bytes; do not normalize artifact line
endings. The manifest excludes itself and this navigational README.

All drawings are original synthetic examples. Standards PDFs/page renders and
Autodesk sample drawings are excluded. Mechanical/tolerance quality 94 retains
two VIEWPORTS-layer warnings; architecture/P&ID quality 100 has a different scope
from source and v8 scoring. This is not a manufacturing-release certification.

Later [main-line integration regression](integration-1041de9/summary.json) at `1041de9`: **823 passed / 8 skipped**, with no failures or errors. This check includes subsequent installer/viewer changes and does not relabel the scored `6699109` measurement.
