# AgentCAD — Claude Code for CAD

**We're building AgentCAD to disrupt AutoCAD.**

Traditional CAD software was built for humans to click, drag, and draw. AgentCAD is CAD infrastructure built for AI agents.

Connect Claude Code, Codex, or any agent through MCP or the CLI. Describe what you want, and the agent creates, edits, validates, and exports real engineering drawings (DXF, and DWG when AutoCAD is installed).

No clicking. No GUI. Just natural language, code, and engineering.

**CAD built for agents, not humans.**

<p align="center">
  <img src="examples/trials/hard/png/H6/A_ops/H6_r2.png" alt="A3 sheet made by Claude Code through AgentCAD: frame, title block and a 1:2 viewport onto a dimensioned base plate" width="49%">
  <img src="examples/trials/hard/png/H5/A/H5_r1__part.png" alt="Bracket plate dimensioned by an agent through AgentCAD: overall size, hole spacing, slot and chamfer" width="49%">
</p>
<p align="center"><sub>Both drawings were made by an agent through AgentCAD and plotted by AutoCAD 2027. Left: "make an A3 sheet with a 1:2 viewport". Right: "dimension this part so the shop can make it".</sub></p>

---

## Your agent can already write code. It still can't do CAD.

Ask an agent to edit a drawing today and it writes a throwaway script against a DXF library. That works until it doesn't: the script overwrites the file, there is no undo, nobody checks the result, and the next session has no idea what the last one changed.

AgentCAD gives the agent a CAD runtime instead of a blank Python file:

- **Operations, not scripts.** 55 typed operations (draw, edit, annotate, layers, blocks, sheets and viewports), each with a JSON schema. Batches are atomic: if one step fails, the file is untouched.
- **Every change is reversible.** Checkpoints before every edit, a diff of what changed, and a durable journal, so a new session can see and undo what an earlier one did.
- **Checked by something other than the agent.** An independent validator re-reads the file from disk and reports problems as structured errors the agent can act on: geometry that doesn't close, dimensions that disagree with the part, text that will print too small, sheets it didn't check.
- **Real drawings, not just new ones.** Paper-space layouts, title blocks with attributes, DWG import/export and AutoCAD AUDIT through an optional headless AutoCAD backend.
- **Safe by default.** Workspace sandbox, read-only mode, operation allow-lists. An escape hatch for custom ezdxf scripts exists, runs as a transaction, and is off unless you turn it on.

## Does it work? We measured it.

We gave two agents the same 12 drafting tasks, from a flange drawing to editing a real AutoCAD sample DWG, five rounds of revisions with an undo, a batch of 12 drawings, cleaning up a supplier's drawing, dimensioning a part and making a print sheet. One arm could only use AgentCAD. The other wrote Python with ezdxf. A neutral grader scored the files, and we plotted the results in AutoCAD.

| | Claude Code (Opus 5.5) + AgentCAD | Claude Code writing code | Codex + AgentCAD | Codex writing code |
|---|---|---|---|---|
| Runs correct | **24 / 24** | 23 / 24 | **24 / 24** | 24 / 24 |
| Five-round revision with undo | **4.1 min** | 12.9 min | **6.2 min** | 18.3 min |
| Edit a real DWG | **2.9 min** | 6.0 min | **3.4 min** | 9.7 min |
| Make an A3 print sheet | **0.9 min** | 1.7 min | **2.5 min** | 3.6 min |

Time per run, 3 runs per task (median for Claude Code, mean for Codex). The Codex AgentCAD column is after two fixes the experiments called for: the real-DWG task was 0/3 until AgentCAD could see paper-space sheets, and the print-sheet task was 0/3 until it had layout and viewport operations. On most tasks the agent was 1.4–3× faster through AgentCAD. The one miss on the code side was the undo: a fresh session had no record of what it was asked to revert. AgentCAD's journal is what made every undo work.

Where it doesn't win yet, we say so: for a batch of near-identical drawings a single generated script is faster and cheaper, and AgentCAD sessions still read 2× the input tokens of the code arm. Full numbers, logs and graders: [docs/comparison-claude-code.md](docs/comparison-claude-code.md), [docs/comparison-hard-tasks.md](docs/comparison-hard-tasks.md), [docs/comparison-code-vs-agentcad.md](docs/comparison-code-vs-agentcad.md).

## Get started in two minutes

```bash
git clone https://github.com/lizaixi01/AgentCAD.git
cd AgentCAD
uv venv .venv --python 3.12
uv pip install --python .venv -e ".[dev]"
```

**Connect Claude Code.** This writes `.mcp.json` in the repository root. The file points at your venv's interpreter and your `playground/` folder, so it works wherever you cloned and on any OS. Open a new Claude Code session in the repository afterwards.

```bash
.venv/bin/agentcad --root playground mcp-config --write
```

On Windows the command is `.venv\Scripts\agentcad.exe`. `.mcp.json` is not committed: it holds paths for your machine only. Run the command again if you move the checkout or recreate the venv.

**Connect Codex.** This appends an `[mcp_servers.agentcad]` table to `~/.codex/config.toml`. The table includes `default_tools_approval_mode = "approve"`; without it, Codex rejects every tool call under `approval_policy="never"`.

```bash
.venv/bin/agentcad --root playground mcp-config --client codex --write
```

Leave out `--write` to just print the config. `--read-only` and `--allow-scripts` go into the generated config as well.

**Then just ask:**

> Draw a 200×100 mounting plate with R8 corners, four Ø12 holes 15 mm from the edges and a Ø40 hole in the middle. Dimension it, save it as plate.dxf, check it, and export plate.svg.

> Make the plate 240 wide and keep the holes 15 mm from the edges. Tell me what changed.

> Undo that.

> Make an A3 sheet for plate.dxf with a 1:2 viewport and drawing number MP-240 in the title block.

More prompts to try: [playground/README.md](playground/README.md).

## Prefer the command line?

Every tool is also a CLI command that prints one JSON envelope:

```bash
agentcad --root ./work create part.dxf --units mm
agentcad --root ./work apply part.dxf --ops-file ops.json
agentcad --root ./work validate part.dxf
agentcad --root ./work diff part.dxf
agentcad --root ./work rollback part.dxf
agentcad --root ./work export part.dxf part.svg
```

The same `Runtime` is available from Python and over HTTP (`agentcad --root work serve`, then `POST /v1/<tool>`). All four interfaces share one service layer.

## Watch the agent work

`agentcad --root ./work viewer` serves a live, read-only view of the workspace at `http://127.0.0.1:8770/`. Drawings and 3D parts update as the agent commits, with a timeline of every change: click one to see that version and what it changed. It works with any agent, because it only reads the files. See [docs/viewer.md](docs/viewer.md).

## What's inside

| | |
|---|---|
| Operations | 62: draw (lines to splines, hatches, polygons), edit (trim, fillet, offset, arrays, break/join, purge), annotate (linear, radial, angular, ordinate dimensions, leaders, tables, title blocks), layers, blocks with attributes, sheets and viewports, and industry libraries |
| Industry libraries | P&ID (ISO 10628 / ISA-5.1): 24 symbols, process and signal lines; a valve placed on a pipe cuts the pipe itself. GD&T (ISO 1101): feature control frames with all 14 characteristics, modifiers and datums, datum feature and surface texture symbols. ISO parts: bolts, nuts, washers, cap screws (M3–M24) and 60xx/62xx/63xx bearings, clearance, tapped and counterbored holes. One op each, sized to the annotation scale; `standard_library` looks up sizes and lists a drawing's parts |
| Agent tools (MCP) | 24, including `apply_operations`, `apply_batch` (several drawings in one call), `validate_drawing`, `get_diff`, `rollback`, `history`, `export_drawing`, `standard_library`, `autocad_live`. `list_operations` returns a compact index and full schemas on request, so it fits in an agent's context |
| Live AutoCAD | `autocad_live` works next to the user's running AutoCAD (Windows, COM): shows the agent's drawing there, reloads it after every change (`AGENTCAD_LIVE_SYNC=1`), and pulls the user's edits back as a normal checkpointed, validated change. Raw command lines are off unless `AGENTCAD_ALLOW_LIVE_COMMANDS=1` |
| Validation | Independent re-read of the file: integrity, duplicates, dimension text vs. geometry, requirements you pass in, printed text height per viewport, coverage of sheets not checked |
| 3D parts | Parametric FreeCAD parts (`.FCStd`) through the same tools: sketches, pad, pocket, revolve, holes, fillets, chamfers, shells, patterns, lofts, sweeps, helices, driven by named parameters. Edge and face selections survive edits. STEP/STL export and shaded PNG previews. Needs FreeCAD 1.1 (optional) — see [docs/part-3d.md](docs/part-3d.md) |
| File formats | DXF R12–R2018, SVG and JSON export. PDF plotting with no extra software: one page per sheet, paper layouts 1:1, model space at a standard scale, Chinese text included. DWG import/export and AUDIT through headless AutoCAD (accoreconsole), optional |
| Tests | 276 automated tests, including 27 cases checked against AutoCAD 2027 behaviour and 36 3D-part tests (30 of them build parts in FreeCAD 1.1) |

Runs on [ezdxf](https://ezdxf.mozman.de/) (MIT). The core needs no commercial software.

## Where it stands

AgentCAD is early. 3D parts are new and not yet measured with agents; they can't be turned into 2D drawings yet. DWG needs AutoCAD on the machine. The industry libraries cover common P&ID, GD&T and ISO fastener content, not a full catalogue. The live AutoCAD session is tested against a stand-in for AutoCAD's COM interface; a run against the GUI needs a signed-in AutoCAD licence. Readability checks cover text height, and plot layout still needs a human eye. The evidence so far is 12 tasks on two agents. What's missing is tracked in [docs/limitations-roadmap.md](docs/limitations-roadmap.md).

## Documentation

Most in-depth documents are in Chinese.

| | |
|---|---|
| [docs/tutorial.md](docs/tutorial.md) | Step-by-step tutorial: generate, validate, revise, roll back, DWG, connecting agents |
| [docs/architecture.md](docs/architecture.md) | Architecture, data model, transactions, error envelope |
| [docs/operations.md](docs/operations.md) | Reference for every operation (generated from code) |
| [docs/part-3d.md](docs/part-3d.md) | 3D parametric parts: FreeCAD backend, operations, selectors, validation |
| [docs/viewer.md](docs/viewer.md) | Live viewer: watch drawings and parts change in the browser, timeline, diffs |
| [docs/comparison-claude-code.md](docs/comparison-claude-code.md) | Claude Code: AgentCAD vs. writing code, before and after the compact catalog |
| [docs/comparison-hard-tasks.md](docs/comparison-hard-tasks.md), [docs/comparison-code-vs-agentcad.md](docs/comparison-code-vs-agentcad.md) | Codex: the same comparison |
| [docs/trials-report.md](docs/trials-report.md) | Classic drafting tasks and 96 real AutoCAD sample drawings |
| [docs/acceptance-report.md](docs/acceptance-report.md) | Acceptance tests and evidence |
| [docs/limitations-roadmap.md](docs/limitations-roadmap.md) | Known limitations and roadmap |

Run logs and graded results for the experiments are in `examples/trials/`. Logs of the tasks that use Autodesk sample drawings (T7, H2) are not published, because the drawings are not ours to redistribute.

## License

MIT
