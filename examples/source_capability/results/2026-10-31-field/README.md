# Field review: seven public AutoCAD MCP servers under rubric v1, 2026-10-31

The [source-capability recheck](../2026-10-31-recheck/README.md) scored AgentCAD and AutoCAD MCP Pro
under the frozen [local rubric v1](../../../../docs/source-capability-rubric.md). The other public
servers on the README board had only U-C4N's July 2026 scores, which were assigned by Pro's author with
different scoring detail. This review scores them under the same rubric, by a comparable strict method:
read the pinned source and committed evidence, then run the product's own tests and targeted probes. The
protocol differs from the recheck in the ways listed under Method.

| Repository | Pinned commit | Commit date | F /25 | C /20 | B /15 | E /15 | T /15 | S /10 | **Total** | Source-only pass | U-C4N, 2026-07 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [LokmenoWer/best-cad-mcp](lokmenower-best-cad-mcp.json) | [`e02b612`](https://github.com/LokmenoWer/best-cad-mcp/tree/e02b6120f4ef5fd2f3f101702cdb73f6c3e2d7a8) | 2026-10-28 | 10 | 8 | 7 | 5 | 8 | 3 | **41** | 43 | 74 |
| [beiming183-cloud/AutoCAD-MCP](beiming183-cloud-autocad-mcp.json) | [`11f7c47`](https://github.com/beiming183-cloud/AutoCAD-MCP/tree/11f7c47e5038796a20451b38b23032e625b5aa26) | 2026-07-19 | 7 | 9 | 5 | 3 | 5 | 4 | **33** | 23 | 83 |
| [varavista/autocad-mcp](varavista-autocad-mcp.json) | [`7034dc4`](https://github.com/varavista/autocad-mcp/tree/7034dc444ba5b5680145a1eff52b4d83a262a75a) | 2026-04-04 | 10 | 4 | 6 | 5 | 4 | 2 | **31** | 21 | 84 |
| [puran-water/autocad-mcp](puran-water-autocad-mcp.json) | [`95476a3`](https://github.com/puran-water/autocad-mcp/tree/95476a33a1c246308326eb4709d6379ef2efdbc1) | 2026-02-20 | 9 | 5 | 5 | 1 | 3 | 1 | **24** | 15 | 70 |
| [AnCode666/multiCAD-mcp](ancode666-multicad-mcp.json) | [`360ec77`](https://github.com/AnCode666/multiCAD-mcp/tree/360ec77c970ec95a962bd4d0a3238715ee78dd7c) | 2026-06-27 | 5 | 3 | 4 | 0 | 4 | 2 | **18** | 15 | 73 |
| [zh19980811/Easy-MCP-AutoCad](zh19980811-easy-mcp-autocad.json) | [`47347ce`](https://github.com/zh19980811/Easy-MCP-AutoCad/tree/47347ced06c663f1c51385467bfe478c5e1ec2fc) | 2026-10-15 | 5 | 2 | 3 | 1 | 1 | 2 | **14** | 14 | 30 |
| [daobataotie/CAD-MCP](daobataotie-cad-mcp.json) | [`daf7502`](https://github.com/daobataotie/CAD-MCP/tree/daf7502951175e01aba9126a702400186ba2d4f9) | 2026-10-27 | 4 | 4 | 3 | 0 | 0 | 2 | **13** | 13 | 35 |

NCO-1986/AutoCAD_mcp (U-C4N 68) was not scored: on 2026-10-31 GitHub returns 404 for the repository,
so no source could be pinned.

Each JSON file records all 20 items with their basis, limits, pinned source links and deductions, what
changed between the source-only and the strict pass, the commands and counts that were run, and a table
of every defect with its reproduction status. Probe scripts, trimmed test logs and probe output are in
[`evidence/`](evidence/).

## Method

- **One independent AI reviewer per repository**, each a separate agent that did not write AgentCAD,
  the rubric or the product it scored. Each was given the rubric, the per-item format of the Pro
  assessment as a calibration example, and its repository and pin, and was told not to look at
  U-C4N's or any other published score.
- **Pinned source**: the default branch's head on 2026-10-31, listed above.
- **Source-only pass**: read the source, committed results and completed GitHub Actions runs.
- **Strict pass**, the scores above: each repository was installed in its own Docker container
  (`python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159`, locked
  dependencies where the repository has a lock). Its own test suite and the reviewer's probes then ran
  with no network, resource limits and only an output folder mounted. Probes call the product's own
  tools or backend on its headless paths, with ordinary, error and boundary cases, and reopen saved
  DXF files with ezdxf to check them independently of the tool's `ok`. Where a headless MCP mode
  exists, tools were also called over real stdio. Every defect from the source-only pass was
  re-tested and marked reproduced, not reproduced (and corrected) or not executable.

| Repository | Own test suite in the container | Headless CAD backend |
|---|---|---|
| LokmenoWer/best-cad-mcp | 454 passed, 2 skipped (AutoCAD-marked tests deselected) | none; drawing understanding and plan logic run without CAD |
| beiming183-cloud/AutoCAD-MCP | 290 passed, 3 failed (all assume Windows) | ezdxf |
| varavista/autocad-mcp | 232 passed | ezdxf |
| puran-water/autocad-mcp | 123 passed | ezdxf |
| AnCode666/multiCAD-mcp | 179 passed, 1 failed (its own path-traversal test), 1 skipped, with a pywin32 stub; 4 collection errors as shipped | none |
| zh19980811/Easy-MCP-AutoCad | 3 errors (scripts import win32com, no assertions) | none |
| daobataotie/CAD-MCP | no tests | none |

## What the scores do and do not mean

- **AutoCAD itself was not run for any of the seven**, and nothing ran on Windows. Their COM, File IPC
  and LISP paths keep their source-only evidence level unless the repository commits native results.
  The recheck reviewer did not launch AutoCAD for AgentCAD or Pro either; both products' native items
  rest on native runs recorded in their own repositories. The rubric asks for evidence, so a server
  whose AutoCAD path works but is not recorded scores low. A 1 means "implemented, not evidenced", not
  "shown to be broken".
- Servers with a headless backend (beiming183-cloud, varavista, puran-water) gained most in the strict
  pass. LokmenoWer lost two points: running it demonstrated two false successes that the source-only
  pass had only suspected, which caps the affected items at 2. Probes against stub COM objects show
  what a product reports and sends, not what a CAD application does; they did not raise drawing items.
- The large gaps to U-C4N's July scores come from different scoring detail, different snapshots and
  this evidence requirement. Neither review is official, and this one is requested and published by
  AgentCAD. It is not an upstream listing, an official ranking or a certification.
