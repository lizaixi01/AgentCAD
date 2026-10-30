# Four previously unrun drawing tasks — 2026-10-30

This is a new-task check of the [dimension-reading workflow](dimension-anchors-2026-10-30.md).
It uses four drawing tasks that do not appear in this project's prior local
CADBench run manifests or model workspaces. It is a small development holdout,
not a claim that the underlying model has never encountered these public tasks.

## Result: used on four new drawings, with uneven outcomes

All four fresh attempts submitted within 900 seconds. The unmodified task
scorers return a **46.45/100 arithmetic mean** over all four. One task is nearly
exact, one is intermediate, and two score below 16. This does not establish
reliable generalization, nor measure an improvement over an older product on
these same tasks: there is no matched pre-optimization control for this cohort.

| Drawing | Task reward /100 | Geometry /100 | Specification score /100 | Consistent specification checks | Seconds |
|---|---:|---:|---:|---:|---:|
| Wire safety lanyard | 11.64 | 6.22 | 90.00 | 20/21 | 318.16 |
| 16×2 LCD display module | 58.65 | 46.30 | 80.00 | 15/17 | 404.53 |
| Valve chest housing | 99.83 | 99.67 | 100.00 | 49/49 | 299.91 |
| Stepped enclosure main body | 15.66 | 10.60 | 30.00 | 17/24 | 647.17 |

The specification score uses the scorer's failure budget of ten; it is not the
percentage in the adjacent count column. The [result ledger](unseen-drawings-2026-10-30.json)
retains unrounded values and complete scorer explanations. No failed or low-score
case is omitted, retried, manually repaired or replaced. All four have one native
editable PartDesign Body and one valid solid; that validates CAD structure, not
agreement with the source drawing.

## Selection fixed before viewing or running

The drawing cohort contains 40 tasks. Six historical run manifests and six
workspace inventories identify two previously exercised drawing tasks:
`freecad-686f17ce17` and `freecad-6fd69bd0c4`. Both are excluded. Before opening
any remaining drawing, the [selection script](artifacts/unseen-drawings-2026-10-30/select_cohort.py)
uses `random.Random(42).sample(sorted_eligible, 4)` on the remaining 38 IDs.
The resulting task order is fixed:

| Task ID | Drawing title, read after selection |
|---|---|
| `freecad-4f4363246f` | Wire safety lanyard |
| `freecad-1338adbf8b` | 16×2 LCD display module |
| `freecad-7dfcc14b48` | Valve chest housing |
| `freecad-6b54209a13` | Stepped enclosure main body |

The [selection record](artifacts/unseen-drawings-2026-10-30/selection.json)
contains all candidate IDs, exclusions, embedded historical manifests and
their hashes, workspace inventories and the algorithm. The
[run manifest](artifacts/unseen-drawings-2026-10-30/manifest.json) binds the
selected inputs, configuration and product version. Sampling is independently
recomputed before launch; there is no overlap with the recorded previous tasks.
No task is substituted after viewing its difficulty or result.
The dataset distribution digest remains unverified, as in the preceding local
pilot; individual public input hashes are pinned and verified in this run.

## Same model and budget, frozen product

Each task receives one fresh Codex CLI 0.163.0 / **gpt-6.1-sol** attempt with
requested **xhigh** effort and **900 seconds**, with concurrency **two** and
seed 42. FreeCAD remains 1.1.4 / OCCT 7.8.1, Python 3.11.16 and validator 0.6.0's
unmodified v2 task scorer. These configuration fields and the pilot/stage-server
hashes are checked against the preceding two-task run.

The run pins commit `211aaf1` (the preparation script). Its product source is
byte-identical to merged optimization `a713426`; the existing `pilot.py`,
`stage_server.py`, model prompt adaptation and enabled tools are unchanged.
There is no new modeling instruction, answer, reference coordinate or
task-specific tool behavior. Product code stays frozen during the experiment.

Models receive only the original public drawing and instructions. Graders,
reference models, previous attempts and score feedback remain outside their
workspaces. Scripts, shell, web and other MCP servers are disabled. Modeling
uses native editable PartDesign operations and the same immutable final-stage
submission contract as earlier experiments.

One attempt means failures, timeouts and missing submissions remain in the
four-task denominator under the existing pilot rules. An infrastructure/scorer
error remains an explicit error, not a silently substituted zero. There are
no model restarts, manual repairs or best-of selection. Model corrections
within its single 900-second attempt are ordinary parts of that attempt.

## What the observations support

Every agent used dimension endpoints before its first modeling operation. The
first groups contain 12, 9, 7 and 12 readings respectively; the LCD attempt also
checked two additional groups before building and revised a group afterward.
The four attempts made 8, 17, 11 and 12 image-inspection calls. Their successful
dimension graphs report consistent supplied relations, while
`semantics_verified` remains false. They also measured final geometry and
exported a preview after the last successful model edit. Thus the new workflow
was used beyond the two development drawings, but following it was insufficient
to ensure correct reconstruction.

- **Valve housing:** 49/49 specification checks agree; volume differs by 0.003%
  and surface alignment RMSE is about 0.0016 mm. The near-perfect score is
  evidence of a successful reconstruction on a newly selected drawing.
- **Wire lanyard:** 20/21 specification checks agree and the bounding-box gate
  passes, but surface-type difference is 83.072%, volume difference is 14.043%
  and alignment RMSE is about 3.07 mm. Many matching named dimensions do not
  establish the correct swept shape.
- **LCD module:** volume differs by only 0.027%, yet surface-type difference is
  13.936% and alignment RMSE is about 1.35 mm. One specification is inconsistent
  and another is not found. Aggregate dimensions and volume can conceal local
  shape or placement differences.
- **Stepped enclosure:** its bounding-box difference rounds to 0.000%, but two
  specifications are inconsistent and five are not found; volume differs by
  6.707% and alignment RMSE is about 7.52 mm. Matching the envelope does not
  verify the internal and local features.

These are aggregate scorer observations, not a diagnosis of the exact incorrect
surface or parameter. No reference CAD or hidden specification was inspected to
repair these attempts. The agent's own statements that its checks passed are
retained in the ledger as agent messages, separately from official task scores.
The four read-only post-run validations contain no external drawing requirements;
they cannot certify the agents' interpretations.

The wire and enclosure attempts report no tool-call errors. The LCD agent
recovered from an image-size limit error. The valve agent recovered from the
same limit, an unsupported-operation query and a malformed measurement request.
All four finish normally, with zero unexpected tools, no stage-audit errors and
no truncated trajectory lines. There is no evidence here that a timeout or
unrecovered tool failure caused the two lowest scores. Separating reading,
modeling strategy and geometry-tool limitations needs a subsequent diagnosis.

## Preservation and interpretation

The [collection script](artifacts/unseen-drawings-2026-10-30/collect_results.py)
archives every available final native submission, working native file, exported
preview, run/result record and stage log, including unsuccessful cases. It
records source, native, trajectory and scorer hashes, actual image/anchor calls,
geometry checks and agent messages. Read-only validation checks each immutable
submission without changing its bytes; every archived copy has the same hash.
No original input drawing, annotated input pixels, reference CAD or solution is
redistributed.

All eight native files, eight exported previews and twelve run/result/stage
records are retained in the repository. Intermediate previews remain alongside
the final previews; the ledger records which exports precede later model edits.
Archive hashes match the source files, and each submitted file matches its
immutable stage hash. Direct links to the final outputs are below; the ledger
lists every other preserved file and its hash.

| Task ID | Submitted native model | Final preview |
|---|---|---|
| `freecad-4f4363246f` | [answer.FCStd](artifacts/unseen-drawings-2026-10-30/freecad-4f4363246f/answer.FCStd) | [Wire](artifacts/unseen-drawings-2026-10-30/freecad-4f4363246f/preview.png) |
| `freecad-1338adbf8b` | [answer.FCStd](artifacts/unseen-drawings-2026-10-30/freecad-1338adbf8b/answer.FCStd) | [LCD](artifacts/unseen-drawings-2026-10-30/freecad-1338adbf8b/module_final_preview.png) |
| `freecad-7dfcc14b48` | [answer.FCStd](artifacts/unseen-drawings-2026-10-30/freecad-7dfcc14b48/answer.FCStd) | [Valve housing](artifacts/unseen-drawings-2026-10-30/freecad-7dfcc14b48/final_preview.png) |
| `freecad-6b54209a13` | [answer.FCStd](artifacts/unseen-drawings-2026-10-30/freecad-6b54209a13/answer.FCStd) | [Enclosure](artifacts/unseen-drawings-2026-10-30/freecad-6b54209a13/final_preview.png) |

Complete raw runs remain in
`D:\Projects\bench-data\cadbench-v3-unseen-drawings-20261030`; all model
workspaces remain under the matching name in `D:\Projects\bench-ws`.
Original trajectories include the inline image responses and stay there.
Earlier experiments, artifacts and measurements are unchanged.

The harness hashes in `artifacts/unseen-drawings-2026-10-30/manifest.json` were
taken from the Windows working tree, whose files have CRLF line endings. The
committed files, unchanged since the run's commit `211aaf1`, hash to
`21e9d4a1a4123259fc9dfc9e3fda29a2f2c650066f9455b5bfebff39eb380023` (`pilot.py`)
and `773f30ba2db74c183ab7466c296980f8596fe4962324c416042a5e1e0303a73c`
(`stage_server.py`). Converting them to CRLF reproduces the recorded `9aab6247…`
and `2f0ea500…`.

This cohort has no matched pre-optimization run. Its score describes performance
on these four new tasks; subtracting the old pair's 67.05 would conflate different
tasks with a product effect. The agents used the anchors on all four new shapes,
and one was reconstructed almost exactly. Without a control, that cannot show the
dimension-reading change carried over: the public leaderboard's Claude Opus 5.5 +
Claude Code run, on 2026-09-23 (UTC) before this tool existed, scored the same
0.998341 on the valve housing. Four known-public tasks also cannot establish
broad reliability or quantify a causal improvement. No result here replaces the
original six-task pilot mean or constitutes an official leaderboard submission.

## Repository verification

The complete suite with FreeCAD configured passes **556 tests, 8 optional
CadQuery skips** in 396.70 seconds, excluding unrelated AutoCAD live integration
tests. The first run had 555 passes, 8 skips and one failure in unchanged
`test_a_3d_batch_reports_each_operation`: its progress log omitted `checking`
before `done`. The isolated recheck passed (0.77 seconds), followed by the full
passing rerun. The [verification record](artifacts/unseen-drawings-2026-10-30/verification.json)
preserves both outcomes and the failure's activity log. The intermittent cause
has not been established; no progress, viewer or modeling code was changed.
These are repository checks, not retries of benchmark model attempts.
