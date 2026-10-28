"""MCP server (stdio). Each tool is a thin adapter over ``Runtime``; no CAD
logic lives here. Configure with env AGENTCAD_ROOT (workspace sandbox),
AGENTCAD_READ_ONLY=1 and AGENTCAD_ALLOWED_OPS=op1,op2."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .policy import Policy
from .service import Runtime

INSTRUCTIONS = """AgentCAD: headless 2D CAD runtime over DXF files.
Workflow: list_operations (compact index; ops=[...] gives full schemas) -> apply_operations (batch many ops in one
call; create={units,...} makes a new drawing in the same call; ops can reference entities created earlier in the
batch as "$<index>", tagged entities as "tag:<name>"). Its result already holds the independent validation of the
saved file (pass requirements to check them); call validate_drawing only for detail=true. Several drawings:
apply_batch, one call. get_diff / history / rollback as needed. Independent read-only calls can go in one turn.
Coordinates are [x, y] in drawing units; lengths may be strings with units ("8mm"). Angles are degrees CCW.
Every result has ok + structured error {code, category, message, entities, retryable, hint, partial_changes}.
A failed batch never modifies the file (partial_changes=false).
Real drawings often have paper-space layouts (printed sheets, read_drawing.layouts) with their own copy of the part:
edit and validate them too, using the 'layout' parameter. New sheets: create_layout, then add_viewport.
run_script (if enabled) covers edits no op can express."""

Path_ = Annotated[str, Field(description="Drawing path (.dxf), relative to the workspace root")]


def build_server(policy: Policy | None = None) -> FastMCP:
    rt = Runtime(policy or Policy())
    mcp = FastMCP("agentcad", instructions=INSTRUCTIONS)

    @mcp.tool()
    def list_operations(category: Annotated[str | None, Field(description="draw|edit|annotate|layer|block|layout: "
                                                                           "full schemas for that category")] = None,
                        ops: Annotated[list[str] | None, Field(description="Op names: full schemas for just these")] = None,
                        detail: Annotated[bool, Field(description="Full schemas for every op (~90K chars)")] = False) -> dict:
        """Operations usable in apply_operations. Without arguments: a compact index (name, category, summary,
        parameter names, * = required). Get JSON schemas (types, units, defaults, limits) with ops=[...] or category."""
        return rt.list_operations(category, ops, detail)

    @mcp.tool()
    def create_drawing(path: Path_, units: Literal["mm", "cm", "m", "in", "ft"] = "mm",
                       template: Literal["mechanical", "blank"] = "mechanical",
                       dxf_version: Literal["R2000", "R2004", "R2007", "R2010", "R2013", "R2018"] = "R2010",
                       overwrite: bool = False,
                       annotation_scale: Annotated[float, Field(gt=0, description="N of plot scale 1:N; dimension and "
                                                                "linetype sizes are multiplied by N. 1 for parts, "
                                                                "50-100 for building plans in mm")] = 1.0) -> dict:
        """Create an empty drawing with an explicit length unit. 'mechanical' adds OUTLINE/HOLES/CENTER/DIM/TEXT/BORDER layers."""
        return rt.create_drawing(path, units, template, dxf_version, overwrite, annotation_scale)

    @mcp.tool()
    def read_drawing(path: Path_) -> dict:
        """Drawing summary: units, extents, layers (with entity counts), entity type counts, blocks, tags, stored spec,
        integrity status and checkpoints. Counts and extents are for model space; 'layouts' lists the paper-space
        sheets and what they contain. A sheet holding geometry is usually the printed drawing (often a scaled copy of
        the part): edits to the part may have to be made there too (use the 'layout' parameter of ops)."""
        return rt.read_drawing(path)

    @mcp.tool()
    def inspect_entities(path: Path_,
                         filter: Annotated[dict | None, Field(description="{type, layer, tag, tag_prefix, layout}")] = None,  # noqa: A002
                         ids: Annotated[list[str] | None, Field(description="Entity handles or 'tag:<name>'")] = None,
                         window: Annotated[list[list[float]] | None, Field(description="[[x0,y0],[x1,y1]] crossing window")] = None,
                         limit: Annotated[int, Field(ge=1, le=5000)] = 200, offset: int = 0, detail: bool = True,
                         layout: Annotated[str | None, Field(description="'Model' (default), a paper layout name "
                                                                "from read_drawing.layouts, or '*' for all")] = None) -> dict:
        """List entities with geometry (paginated, filterable). Paper-space entities carry a 'layout' field."""
        return rt.inspect_entities(path, filter, ids, limit, offset, detail, window, layout)

    @mcp.tool()
    def apply_operations(path: Path_,
                         operations: Annotated[list[dict[str, Any]], Field(description="Ordered ops, e.g. "
                             "[{\"op\":\"add_circle\",\"center\":[10,10],\"diameter\":8,\"layer\":\"HOLES\",\"tag\":\"h1\"}]. "
                             "See list_operations for every op's parameters.")],
                         dry_run: bool = False,
                         requirements: Annotated[list[dict] | None, Field(description="Requirements the result is "
                                                 "validated against (same as validate_drawing)")] = None,
                         strict: Annotated[bool, Field(description="Do not save if post-validation fails")] = False,
                         label: str | None = None,
                         create: Annotated[dict | None, Field(description="Create the drawing first if it does not "
                                           "exist: {units, template, dxf_version, annotation_scale}")] = None,
                         bounds: Annotated[list[list[float]] | None, Field(description="[[x0,y0],[x1,y1]] for the "
                                           "validation")] = None,
                         layout: Annotated[str | None, Field(description="Validate this paper-space sheet instead of "
                                           "model space (ops choose their own layout)")] = None) -> dict:
        """Execute an operation batch as one transaction: all params are checked first, any failure aborts with the
        file untouched; success checkpoints the old file, saves atomically, journals, and validates the result.
        The returned 'validation' is the same independent re-read of the saved file as validate_drawing (issues,
        failed requirements, passed ids, recognized counts, coverage): no separate validate_drawing call is needed
        unless you want its detail=true report. With 'create' a new drawing takes one call."""
        return rt.apply_operations(path, operations, dry_run, requirements, strict, label, create, bounds, layout)

    @mcp.tool()
    def apply_batch(jobs: Annotated[list[dict[str, Any]], Field(description="[{path, operations, create?, "
                                    "requirements?, bounds?, layout?, strict?, label?}, ...], one per drawing")],
                    stop_on_error: Annotated[bool, Field(description="Skip the remaining jobs after a failure")] = False
                    ) -> dict:
        """apply_operations on several drawings in one call, e.g. a family of parts from a parameter table. Each job
        is its own transaction (a failed job's operations change nothing, though a drawing its 'create' made stays
        empty; the other jobs still run) and returns its own validation, so one call creates, draws and checks the
        whole set."""
        return rt.apply_batch(jobs, stop_on_error)

    @mcp.tool()
    def run_script(path: Path_,
                   code: Annotated[str, Field(description="Python using ezdxf. The drawing is given as `doc` (model "
                                                          "space as `msp`); edit it in place, do not open or save "
                                                          "files. Paper layouts: doc.layouts.get(name). Optionally "
                                                          "set `result` to a JSON value to return it.")],
                   dry_run: Annotated[bool, Field(description="Return the diff without saving")] = False,
                   requirements: Annotated[list[dict] | None, Field(description="Optional requirements to validate after")] = None,
                   strict: Annotated[bool, Field(description="Do not save if post-validation fails")] = False,
                   label: str | None = None) -> dict:
        """For edits the operation catalogue cannot express. Runs the script on a copy of the drawing in a separate
        process (time-limited; imports limited to ezdxf/math/standard data modules), then commits it like a batch:
        checkpoint, diff, validation, journal with the full script; rollback works as usual. Disabled unless the
        server runs with AGENTCAD_ALLOW_SCRIPTS=1. Prefer apply_operations when an operation exists."""
        return rt.run_script(path, code, label, dry_run, requirements, strict)

    @mcp.tool()
    def apply_constraints(path: Path_,
                          constraints: Annotated[list[dict[str, Any]], Field(description="e.g. {\"type\":\"perpendicular\","
                              "\"a\":\"tag:l1\",\"b\":\"tag:l2\"}, {\"type\":\"distance\",\"a\":\"tag:h1@center\","
                              "\"b\":\"tag:h2@center\",\"value\":80}")],
                          mode: Literal["check", "enforce"] = "check", tolerance: float = 1e-6) -> dict:
        """Check geometric constraints (all types) or enforce a subset by sequential direct edits (NOT a simultaneous
        solver; saves only if all constraints hold afterwards)."""
        return rt.apply_constraints(path, constraints, mode, tolerance)

    @mcp.tool()
    def validate_drawing(path: Path_, requirements: Annotated[list[dict] | None, Field(description=
                         "outline/hole/hole_count/dimension/entity_count/text/within_bounds requirements; default: "
                         "re-derived from the drawing's stored part spec")] = None,
                         bounds: Annotated[list[list[float]] | None, Field(description="[[x0,y0],[x1,y1]]")] = None,
                         tolerance: float = 1e-6,
                         layout: Annotated[str | None, Field(description="Check this paper-space sheet instead of "
                                                                "model space")] = None,
                         detail: Annotated[bool, Field(description="Full report: expected/actual of passed "
                                                       "requirements, every recognized circle and dimension")] = False
                         ) -> dict:
        """Independent validator: re-reads the DXF from disk and checks integrity (duplicates, degenerate geometry,
        dimension consistency, bounds) and requirements (failed ones with expected / actual / deviation /
        tolerance). It reports layouts it did not check (LAYOUT_NOT_VALIDATED, 'coverage'); dimension values are
        compared as displayed. Compact by default; detail=true for everything."""
        return rt.validate_drawing(path, requirements, True, bounds, tolerance, None, layout, detail)

    @mcp.tool()
    def draw_from_spec(spec: Annotated[dict[str, Any], Field(description="{kind:'plate', units, width, height, holes:"
                       "[{pattern:'corners', diameter, edge_offset}|{pattern:'single', diameter, center}], corner_radius, "
                       "material, thickness, sheet:'A4'|null, title_block:{...}|null} or {kind:'plan', units, operations}")],
                       output: Path_, overwrite: bool = False) -> dict:
        """Generate a dimensioned drawing from a structured part spec and validate it against the spec."""
        return rt.draw_from_spec(spec, output, overwrite)

    @mcp.tool()
    def revise_drawing(path: Path_, changes: Annotated[dict[str, Any], Field(description="Spec fields to change, e.g. {\"width\": 120}")],
                       dry_run: bool = False) -> dict:
        """Change design parameters of a spec-made drawing; entities are updated in place by tag, untouched ones keep
        their ids, user-added entities are preserved; result is re-validated."""
        return rt.revise_drawing(path, changes, dry_run)

    @mcp.tool()
    def extract_requirements(document: Annotated[str, Field(description="PDF / TXT / MD path in the workspace")],
                             facts: Annotated[list[dict] | None, Field(description="Optional agent-extracted facts "
                                 "[{field, value, unit, quote, page}]; quotes are verified against the document")] = None,
                             overrides: Annotated[dict | None, Field(description="Caller decisions for missing values")] = None) -> dict:
        """Extract dimensions, units, material and hole requirements with page/line/section sources; reports missing,
        contradictory and ambiguous items instead of guessing."""
        return rt.extract_requirements(document, facts, overrides)

    @mcp.tool()
    def revise_from_document(document: Annotated[str, Field(description="PDF / TXT / MD spec document")], output: Path_,
                             facts: list[dict] | None = None, overrides: dict | None = None, overwrite: bool = False) -> dict:
        """Document -> structured spec -> drawing (created, or revised in place if it exists) -> requirement-by-
        requirement verification traced back to document sources. Refuses to draw when information is missing/conflicting."""
        return rt.revise_from_document(document, output, facts, overrides, overwrite)

    @mcp.tool()
    def get_diff(path: Path_, against: Annotated[str, Field(description="'previous', a checkpoint id 'cp-0003' or another .dxf")] = "previous",
                 detail: Annotated[bool, Field(description="Full geometry of added/deleted entities")] = False) -> dict:
        """Entity-level diff between the drawing and a checkpoint or file: modified entities with old/new values of
        each changed field; added/deleted entities by id/type/layer/tag (detail=true for their geometry)."""
        return rt.get_diff(path, against, detail)

    @mcp.tool()
    def rollback(path: Path_, checkpoint: Annotated[str | None, Field(description="Checkpoint id; default latest")] = None) -> dict:
        """Restore a checkpoint. The state before the rollback is itself checkpointed."""
        return rt.rollback(path, checkpoint)

    @mcp.tool()
    def list_checkpoints(path: Path_) -> dict:
        """Checkpoints taken before each change."""
        return rt.list_checkpoints(path)

    @mcp.tool()
    def history(path: Path_, limit: int = 50,
                seq: Annotated[list[int] | None, Field(description="Return these records in full (operations with "
                                                       "parameters, scripts, errors)")] = None,
                detail: Annotated[bool, Field(description="Every record in full")] = False) -> dict:
        """Operation journal, one line per record (tool, label, op names, change counts, checkpoint_before).
        seq=[...] gives full records, e.g. to see the parameters an earlier round used."""
        return rt.history(path, limit, detail, seq)

    @mcp.tool()
    def recover(path: Path_) -> dict:
        """Restore the last valid checkpoint if the file is corrupt or a transaction was interrupted."""
        return rt.recover(path)

    @mcp.tool()
    def export_drawing(path: Path_, output: str, format: Literal["dxf", "svg", "json", "pdf", "dwg"] = "dxf",  # noqa: A002
                       dxf_version: Literal["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"] | None = None,
                       overwrite: bool = False,
                       layout: Annotated[str | None, Field(description="pdf: 'Model', a paper layout or '*'; default "
                                                          "every paper layout with content, else Model")] = None,
                       paper: Annotated[Literal["A0", "A1", "A2", "A3", "A4", "auto"] | None,
                                        Field(description="pdf, model space: sheet size")] = None,
                       scale: Annotated[float | None, Field(gt=0, description="pdf, model space: paper mm per "
                                                            "drawing unit (0.5 = 1:2); default largest standard "
                                                            "scale that fits")] = None,
                       orientation: Literal["auto", "landscape", "portrait"] = "auto",
                       monochrome: bool = False) -> dict:
        """Export to another DXF version (R12 via a safe converter), SVG preview, JSON, PDF (plotted without
        external software: one page per layout, paper layouts 1:1 on their sheet, vector output, reports scale and
        too-small printed text), or DWG (optional AutoCAD backend; dxf_version selects the DWG release)."""
        return rt.export_drawing(path, output, format, dxf_version, overwrite, layout, paper, scale, orientation,
                                 monochrome)

    @mcp.tool()
    def import_drawing(source: Annotated[str, Field(description="DWG file in the workspace")], output: Path_,
                       overwrite: bool = False) -> dict:
        """Import a DWG as a DXF drawing (optional AutoCAD backend), then validate it."""
        return rt.import_drawing(source, output, overwrite)

    @mcp.tool()
    def autocad_audit(path: Path_) -> dict:
        """Open the drawing in AutoCAD headlessly and run AUDIT (no fixes): AutoCAD's own verdict on the file.
        Needs the optional AutoCAD backend; returns a dependency error otherwise."""
        return rt.autocad_audit(path)

    @mcp.tool()
    def get_metrics() -> dict:
        """Tool-call counts, durations and payload sizes for this server session (no model calls are made)."""
        return rt.get_metrics()

    return mcp


def serve_stdio(policy: Policy | None = None) -> None:
    build_server(policy).run("stdio")


def main() -> None:
    serve_stdio()


if __name__ == "__main__":
    main()
