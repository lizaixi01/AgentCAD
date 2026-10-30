# Source-capability evidence — 2026-10-30

**AgentCAD 98 / AutoCAD MCP Pro 96**, using the same
[frozen local rubric](../../../../docs/source-capability-rubric.md). This is an
independent AI review requested and published by AgentCAD, not external
certification or an official upstream ranking. Pro's historical **93** belongs to
its v1.6.0 self-review of 2026-09-24 and is retained separately.

| Record | Content |
|---|---|
| [Assessment](assessment.json) | 20 items per product, all scores/deductions, 181 fixed source references, 44 evidence hashes and assessor identity |
| [Review report](../../../../docs/source-capability-review.md) | Six category totals, repaired defects, verification and remaining limits |
| [Regression summary](verification-summary.json) | Five lanes with the same 693 test IDs; pass/skip counts, every skip reason and JUnit hashes |
| [v8 report](v8-report.json) | Original 31-task evaluator, 31/31 and 100/100 through public MCP, clean pinned source |
| [Version comparison](performance.json) | 24 correct observations, excluded warm-ups, five measured trials per version/count, medians and raw logs in ZIP |
| [Production report](showcase-report.json) | Public Runtime calls, saved outputs, DWG roundtrips/AUDIT, native A3 activation and numeric readback |
| [Visual review](visual-review.md) | Five PDF previews, provenance, readability and explicit manufacturing limits |
| [Evidence ZIP](evidence.zip) | 872 retained files: JUnit, transcripts, original synthetic drawings, native jobs, reviewer reproductions and historical failures |
| [Manifest](manifest.json) | Raw-byte SHA-256 for the ZIP, every member and standalone evidence files |

The product commit is `b4c04669238e771a0888114f1af3260d7c371834`;
Pro and the unmodified evaluator are pinned to
`58a05ddfc34a9832c626e82cd88ecdce8e16a62a`. The version-comparison baseline is
`a713426e1e2f271dd2db068cd165b7d020604700`. Later publication commits only add
documentation/evidence and do not retroactively change the measured product.

## Integrity and paths

The 9,622,273-byte ZIP has SHA-256:

```text
1d2889cf18d66faf3c3a4633ef5e49ae0d5ed29a22aa3a7f1d4834683165de3e
```

The independent `assessment.json` is copied unchanged; its SHA-256 is:

```text
760521504a260f31472e3b1945a3f40bc72587d13d9ee0bc2c57f6df5f727ddf
```

After extraction, assessment evidence paths are relative to
`output/source-capability/`. The ZIP keeps that original directory structure.
Reports retain their original machine paths as provenance; use their corresponding
archive directories when inspecting the files elsewhere. Git sources remain
available at the fixed links and are not repackaged as whole checkouts.
`manifest.json` covers raw bytes: do not normalize artifact line endings.
Git LF/CRLF normalization is used only when comparing source content across
platforms. The manifest does not hash itself or this navigational README.

Local native regression: **685 passed / 8 skipped**. The eight skipped tests need
CadQuery, which was not installed. AutoCAD 2027 and FreeCAD 1.1.4 were enabled.
CI at [run 41049567713](https://github.com/lizaixi01/AgentCAD/actions/runs/41049567713)
passed on Windows 3.11 (600/93), Linux 3.10 (528/165), Linux 3.12 (549/144) and
macOS 3.12 (549/144), written as **passed/skipped**. Only Linux 3.12 additionally
runs the full v8 gate. Optional native skips do not demonstrate native support on
those CI hosts. The archive preserves CI evidence beyond its hosted expiration.

## What the drawings demonstrate

All drawings are original synthetic examples generated for this reproduction.
No Autodesk sample drawings or downloaded standards publications are included.
Mechanical/tolerance delivery quality is **94**, with two undefined `VIEWPORTS`
layer warnings each; architecture/P&ID quality is **100**. These drawing scores
are not the source score or v8 score.

The raw native roundtrip keeps inactive paper viewports at id/status 0/0. The
retained AutoCAD activation job uses CTAB/REGENALL and DXFOUT to produce the 2/2
witness; it does not patch viewport IDs. AgentCAD exports the resulting PDF, not
an Autodesk PDF driver. Visual inspection and numeric readback have separate
records. The mechanical template still needs critical manufacturing annotations.

## Earlier failures remain visible

The archive also retains earlier full-run logs, reviewer counterexamples and
pending verdicts. These are development history, not additional successful trials:

- The `4618f86` native run had a Windows HTTP connection-reset failure; the
  early-refusal handling was subsequently fixed.
- The `25abc96` full run passed, but independent review then exposed a tolerance
  check bypass in block definitions. Its original counterexample is retained.
- Review at `3db102d` found non-finite tolerance factors and weak import binding
  in the reproduction script. The first native showcase also rejected inactive
  viewport IDs. The final product and harness fixes were rechecked at `b4c0466`.
- The rubric review retains its provisional rows, including the withdrawal of
  an asymmetric deduction against Pro's extra honestly unsupported standard tables.

Existing repository benchmark measurements and charts have not been overwritten.
For fresh execution use the [reproduction instructions](../../README.md).
