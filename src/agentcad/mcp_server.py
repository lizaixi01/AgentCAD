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
Workflow: list_operations (catalog) -> create_drawing or draw_from_spec -> apply_operations (batch many ops in one
call; ops can reference entities created earlier in the batch as "$<index>", tagged entities as "tag:<name>") ->
validate_drawing (independent re-read of the file) -> get_diff / rollback as needed.
Coordinates are [x, y] in drawing units; lengths may be strings with units ("8mm"). Angles are degrees CCW.
Every result has ok + structured error {code, category, message, entities, retryable, hint, partial_changes}.
A failed batch never modifies the file (partial_changes=false)."""

Path_ = Annotated[str, Field(description="Drawing path (.dxf), relative to the workspace root")]


def build_server(policy: Policy | None = None) -> FastMCP:
    rt = Runtime(policy or Policy())
    mcp = FastMCP("agentcad", instructions=INSTRUCTIONS)

    @mcp.tool()
    def list_operations(category: Annotated[str | None, Field(description="draw|edit|annotate|layer|block")] = None) -> dict:
        """Catalog of every operation usable in apply_operations, with JSON schemas (types, units, limits)."""
        return rt.list_operations(category)

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
        integrity status and checkpoints."""
        return rt.read_drawing(path)

    @mcp.tool()
    def inspect_entities(path: Path_,
                         filter: Annotated[dict | None, Field(description="{type, layer, tag, tag_prefix}")] = None,  # noqa: A002
                         ids: Annotated[list[str] | None, Field(description="Entity handles or 'tag:<name>'")] = None,
                         window: Annotated[list[list[float]] | None, Field(description="[[x0,y0],[x1,y1]] crossing window")] = None,
                         limit: Annotated[int, Field(ge=1, le=5000)] = 200, offset: int = 0, detail: bool = True) -> dict:
        """List entities with geometry (paginated, filterable)."""
        return rt.inspect_entities(path, filter, ids, limit, offset, detail, window)

    @mcp.tool()
    def apply_operations(path: Path_,
                         operations: Annotated[list[dict[str, Any]], Field(description="Ordered ops, e.g. "
                             "[{\"op\":\"add_circle\",\"center\":[10,10],\"diameter\":8,\"layer\":\"HOLES\",\"tag\":\"h1\"}]. "
                             "See list_operations for every op's parameters.")],
                         dry_run: bool = False,
                         requirements: Annotated[list[dict] | None, Field(description="Optional requirements to validate after")] = None,
                         strict: Annotated[bool, Field(description="Do not save if post-validation fails")] = False,
                         label: str | None = None) -> dict:
        """Execute an operation batch as one transaction: all params are checked first, any failure aborts with the
        file untouched; success checkpoints the old file, saves atomically, journals, and validates the result."""
        return rt.apply_operations(path, operations, dry_run, requirements, strict, label)

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
                         tolerance: float = 1e-6) -> dict:
        """Independent validator: re-reads the DXF from disk and checks integrity (duplicates, degenerate geometry,
        dimension consistency, bounds) and requirements (expected / actual / deviation / tolerance)."""
        return rt.validate_drawing(path, requirements, True, bounds, tolerance)

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
    def get_diff(path: Path_, against: Annotated[str, Field(description="'previous', a checkpoint id 'cp-0003' or another .dxf")] = "previous") -> dict:
        """Entity-level diff (added / deleted / modified fields) between the drawing and a checkpoint or file."""
        return rt.get_diff(path, against)

    @mcp.tool()
    def rollback(path: Path_, checkpoint: Annotated[str | None, Field(description="Checkpoint id; default latest")] = None) -> dict:
        """Restore a checkpoint. The state before the rollback is itself checkpointed."""
        return rt.rollback(path, checkpoint)

    @mcp.tool()
    def list_checkpoints(path: Path_) -> dict:
        """Checkpoints taken before each change."""
        return rt.list_checkpoints(path)

    @mcp.tool()
    def history(path: Path_, limit: int = 50) -> dict:
        """Operation journal (inputs, results, versions, hashes) for reproducibility."""
        return rt.history(path, limit)

    @mcp.tool()
    def recover(path: Path_) -> dict:
        """Restore the last valid checkpoint if the file is corrupt or a transaction was interrupted."""
        return rt.recover(path)

    @mcp.tool()
    def export_drawing(path: Path_, output: str, format: Literal["dxf", "svg", "json", "dwg"] = "dxf",  # noqa: A002
                       dxf_version: Literal["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"] | None = None,
                       overwrite: bool = False) -> dict:
        """Export to another DXF version (R12 via a safe converter), SVG preview, JSON, or DWG (needs the optional
        AutoCAD backend; dxf_version then selects the DWG release; the DWG is read back and validated)."""
        return rt.export_drawing(path, output, format, dxf_version, overwrite)

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
