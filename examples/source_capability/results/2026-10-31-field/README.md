# Field review: seven public AutoCAD MCP servers under rubric v1, 2026-10-31

The [source-capability recheck](../2026-10-31-recheck/README.md) scored AgentCAD and AutoCAD MCP Pro
under the frozen [local rubric v1](../../../../docs/source-capability-rubric.md). The other public
servers on the README board had only U-C4N's July 2026 scores, which were assigned by Pro's author with
different scoring detail. This review scores them under the same rubric so that all nine can be drawn as
one list.

| Repository | Pinned commit | Commit date | F /25 | C /20 | B /15 | E /15 | T /15 | S /10 | **Total** | U-C4N, 2026-07 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [LokmenoWer/best-cad-mcp](lokmenower-best-cad-mcp.json) | [`e02b612`](https://github.com/LokmenoWer/best-cad-mcp/tree/e02b6120f4ef5fd2f3f101702cdb73f6c3e2d7a8) | 2026-10-28 | 11 | 9 | 7 | 5 | 8 | 3 | **43** | 74 |
| [beiming183-cloud/AutoCAD-MCP](beiming183-cloud-autocad-mcp.json) | [`11f7c47`](https://github.com/beiming183-cloud/AutoCAD-MCP/tree/11f7c47e5038796a20451b38b23032e625b5aa26) | 2026-07-19 | 6 | 6 | 3 | 3 | 3 | 2 | **23** | 83 |
| [varavista/autocad-mcp](varavista-autocad-mcp.json) | [`7034dc4`](https://github.com/varavista/autocad-mcp/tree/7034dc444ba5b5680145a1eff52b4d83a262a75a) | 2026-04-04 | 7 | 2 | 5 | 3 | 2 | 2 | **21** | 84 |
| [AnCode666/multiCAD-mcp](ancode666-multicad-mcp.json) | [`360ec77`](https://github.com/AnCode666/multiCAD-mcp/tree/360ec77c970ec95a962bd4d0a3238715ee78dd7c) | 2026-06-27 | 5 | 3 | 3 | 0 | 2 | 2 | **15** | 73 |
| [puran-water/autocad-mcp](puran-water-autocad-mcp.json) | [`95476a3`](https://github.com/puran-water/autocad-mcp/tree/95476a33a1c246308326eb4709d6379ef2efdbc1) | 2026-02-20 | 5 | 3 | 3 | 1 | 2 | 1 | **15** | 70 |
| [zh19980811/Easy-MCP-AutoCad](zh19980811-easy-mcp-autocad.json) | [`47347ce`](https://github.com/zh19980811/Easy-MCP-AutoCad/tree/47347ced06c663f1c51385467bfe478c5e1ec2fc) | 2026-10-15 | 5 | 2 | 3 | 1 | 1 | 2 | **14** | 30 |
| [daobataotie/CAD-MCP](daobataotie-cad-mcp.json) | [`daf7502`](https://github.com/daobataotie/CAD-MCP/tree/daf7502951175e01aba9126a702400186ba2d4f9) | 2026-10-27 | 4 | 4 | 3 | 0 | 0 | 2 | **13** | 35 |

NCO-1986/AutoCAD_mcp (U-C4N 68) was not scored: on 2026-10-31 GitHub returns 404 for the repository,
so no source could be pinned.

Each JSON file records all 20 items with their basis, limits, pinned source links, deductions, the
evidence used and the serious defects found.

## Method

- **One independent AI reviewer per repository**, each a separate agent that did not write AgentCAD,
  the rubric or the product it scored. Each was given only the rubric, the per-item format of the Pro
  assessment as a calibration example, and its repository and pin. Reviewers were told not to look at
  U-C4N's or any other published score.
- **Pinned source**: the default branch's head on 2026-10-31, listed above.
- **No third-party code was executed.** These repositories are untrusted code; nothing was installed,
  tested, built or run, and AutoCAD was not launched. Evidence is the pinned source, results committed
  in the repository (counted only where the exercised code boundary still matches the pin) and completed
  GitHub Actions runs.
- **Anchors applied literally.** Anchor 2 and above require output evidence. Code that exists without
  any output evidence is held at 1. Most of these repositories commit no results and run no test CI,
  which is the main reason for their low totals.

## What the scores do and do not mean

- The method is stricter for these seven than for AgentCAD and Pro in one respect: the recheck reviewer
  also ran headless checks of those two products locally, and both products commit extensive recorded
  evidence. A server whose code works but whose results are not recorded scores low here. A score of 1
  means "implemented, not evidenced", not "shown to be broken".
- Defects listed in the JSON files were found by reading the source, not by running it. Most did not
  lower a score, because the item was already at 1 for lack of evidence.
- The large gaps to U-C4N's July scores come from different scoring detail, different snapshots and
  this evidence requirement. Neither review is official, and this one is requested and published by
  AgentCAD. It is not an upstream listing, an official ranking or a certification.
