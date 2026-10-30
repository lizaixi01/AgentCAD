"""MCP server (stdio). Each tool is a thin adapter over ``Runtime``; no CAD
logic lives here. Configure with env AGENTCAD_ROOT (workspace sandbox),
AGENTCAD_READ_ONLY=1 and AGENTCAD_ALLOWED_OPS=op1,op2. The live viewer starts on the first change
(AGENTCAD_VIEWER=0: not at all; AGENTCAD_VIEWER_OPEN=1: also open it in the browser)."""
from __future__ import annotations

import base64
import os
import json
from functools import wraps
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field

from .policy import Policy
from .service import Runtime
from .worker import CADWorker

INLINE_IMAGE_MAX = 2 * 1024 * 1024  # bytes: a png export larger than this is not returned inline

INSTRUCTIONS = """AgentCAD: CAD runtime for agents: 2D drawings (.dxf) and 3D parametric parts (.FCStd, FreeCAD).
Paths are relative to the workspace. The same tools work on both; the file extension picks 2D or 3D.
Tool names below are this server's own; your client may list them with a prefix (Claude Code:
mcp__<server name>__<tool>, usually mcp__agentcad__list_operations). Always call them by the listed name.

Basics
- Find operations: list_operations() is a compact index (2D ops, plus part_operations names). Full schemas for
  just the ops you need: list_operations(ops=["add_sketch", "pad"]) (2D and 3D names alike), or a whole
  category ('part', 'draw', 'annotate', ...). Unsure of a parameter? Fetch the schema instead of guessing.
- Change files with apply_operations: many ops in one call; create={"units": "mm"} makes the file in the same
  call. Later ops reference earlier ones as "$<index>" and tagged ones as "tag:<name>". A failed batch changes
  nothing (partial_changes=false); fix what the error names (code, message, hint) and resend the batch.
  Several files in one call: apply_batch. Independent read-only calls can go in one turn.
- The result already holds an independent validation of the saved file (pass requirements to check sizes,
  counts, ...); validate_drawing only for detail=true. Undo: rollback; what changed: get_diff / history.
- Lengths: numbers in the file's units, or strings with units ("8mm", "0.5in"). Angles: degrees, CCW.
- Exporting to a file that exists returns FILE_EXISTS: pass overwrite=true (e.g. re-rendering a preview).

2D drawings (.dxf)
- Coordinates [x, y]. Templates add layers OUTLINE/HOLES/CENTER/DIM/TEXT. Dimensions, leaders, tables,
  title blocks, blocks with attributes, P&ID / GD&T / ISO fasteners and bearings ('library' ops; standard_library looks up sizes and lists a
  drawing's parts).
- Real drawings often have paper-space sheets (read_drawing.layouts) with their own copy of the part: edit
  them too with the 'layout' parameter. New sheets: create_layout, then add_viewport.
- Export svg / png / pdf / json, dwg with AutoCAD. autocad_live shows your drawing in the user's running AutoCAD
  and pulls their edits back.
  run_script (only if enabled) covers edits no op can express.

3D parts (.FCStd)
- For an engineering drawing image, inspect_image magnifies callouts and section views. Before modeling,
  rotate vertical or inverted annotations upright with inspect_image(rotate=90/180/270). Recheck ambiguous
  digits and decimal points at a readable orientation. Make a dimension ledger from the drawing, then
  map each dimension to the edges/centres it measures, rather than a nearby feature. Use section extension
  lines and hatching to distinguish cut depth from remaining wall thickness and to identify which side
  each recess or protrusion occupies. Record signed face levels in the chosen coordinate frame.
  For each thickness/depth callout, name BOTH measured surfaces and follow both witness lines to them;
  a nearby number is not evidence for a surface pair. Resolve an ambiguous assignment against the other
  views before building. State a short dimension ledger (value, measured features, source view, planned check).
- One PartDesign Body, one solid, every feature native and editable. Usual order: set_parameters (optional),
  add_sketch on a plane (XY normal +Z, XZ normal -Y, YZ normal +X; offset moves it along the normal) or
  on_face, then pad (adds along the normal) / pocket (cuts against it) / revolve / groove / hole, then fillet,
  chamfer, thickness, patterns, mirror, loft, sweep, helix. primitive adds or cuts boxes, cylinders, ...
- Example batch: [{"op":"add_sketch","plane":"XY","shapes":[{"type":"rectangle","center":[0,0],"width":80,
  "height":40}]}, {"op":"pad","sketch":"$0","length":10}, {"op":"add_sketch","on_face":"top","shapes":
  [{"type":"circle","center":[0,0],"diameter":12}]}, {"op":"pocket","sketch":"$2","through_all":true}]
- Sketch coordinates are [x, y] in the sketch plane, space coordinates [x, y, z], mm. Edge / face selectors
  ("top", {"type": "circle", "radius": 6}) are re-resolved after every edit; '=Params.w' drives dimensions: change them later with set_parameters or
  modify_feature and the part rebuilds.
- The result's validation.shape gives size, volume and holes: check them against what you meant to build.
  Derive validation targets independently from explicit drawing callouts, not from the geometry you just
  created. Check that the signed face-level differences agree with those callouts before saving.
  A valid solid with matching overall size/hole count can still have wrong local geometry. Compare opposite
  faces and section depth levels, and use inspect_entities for the relevant face positions.
  Use inspect_entities(filter={kind:'faces'}), not the default feature history or the DXF type filter.
  measure_entities(target={kind:'planar_levels',axis:'z'}) lists the final solid's plane levels. Measure
  each intended local thickness with target={kind:'face_distance',from:'FaceN',to:'FaceM'}; validation
  supports requirements={type:'face_distance',from:...,to:...,value:...,tolerance:...} in its list.
- See what you built: export_drawing(path, "preview.png", "png", views=[...]); a view is a name (iso, front,
  top, right, ...) or the camera position [x, y, z] relative to the part. The image comes back in the result.
  Each view is scaled to fill its cell (fit='view'), so compare shapes and proportions within a view, not
  sizes across views; fit='uniform' uses one scale. To match a reference image, use its camera positions.
  Keep one consistent orientation across front/top/side views; establish the drawing's projection layout
  and track the same named features between views. Do not mirror individual views to make them fit.
  The preview's camera_frames report screen-right/up directions, so left/right correspondence is explicit.
  Angle operands on operations are numeric degrees; set_parameters does not accept strings ending in 'deg'.
- Deliver with export_drawing(path, "part.step", "step") (also stl, iges, brep, obj): read back and compared.

3D scripts and reference images
- Ops build an editable feature tree (parameters, modify_feature; what CADBench requires). A script is often
  quicker for complex shapes, or when only the solid counts (STEP, a score on the shape). If enabled,
  run_script(path.FCStd, code) runs CadQuery (`cq` imported) that sets `result` to a cq.Workplane or Shape
  (language="freecad": FreeCAD Part code). The solid becomes the part's base, committed like a batch; part ops
  (fillet, hole, pocket, ...) can build on it. To revise, re-run the whole changed script (keep_features=true
  rebuilds those ops on the new solid).
- Compare with a reference image: export_drawing(path, "cmp.png", "png", views=[...], reference="ref.png"),
  views in the reference's order and grid (2 columns up to 4 views). Each view is scaled and centred onto the
  reference's silhouette, so overall size is not compared, only shape and proportions. compare.score (per view:
  views[].score) is the mean of outline (silhouette IoU) and edges (lines and shading steps inside the part). A part
  that matches usually scores 0.95 or more (thin flanges, springs and hollow parts can score lower); below 0.9, look
  where the diff shows red or blue. The
  image is a diff per view: grey where both have material, light red / light blue where only the reference / only
  ours has; red edges only in the reference (a feature yours lacks or misplaces), blue only in yours. views[].cut
  names sides where the reference runs out of its picture: nothing beyond them is compared.

Live viewer: results that change a file carry viewer_url, a page on this computer where the user watches the
work step by step and can save or share it. Give the user that link once, the first time you change something."""

Path_ = Annotated[str, Field(description="Drawing path (.dxf) or 3D part (.FCStd), relative to the workspace "
                                        "root")]


class CADServer(FastMCP):
    """Run all synchronous CAD work on one cancellation-safe worker, keeping SDK validation."""
    def __init__(self, *args, **kwargs):
        self.worker = CADWorker()
        super().__init__(*args, **kwargs)

    def add_tool(self, fn, *args, **kwargs):
        @wraps(fn)
        async def serialized(*a, **kw):
            return await self.worker.run(fn, *a, **kw)
        return super().add_tool(serialized, *args, **kwargs)


def build_server(policy: Policy | None = None, profile: str | None = None) -> FastMCP:
    rt = Runtime(policy or Policy(), auto_viewer=True)
    mcp = CADServer("agentcad", instructions=INSTRUCTIONS)

    @mcp.tool()
    def inspect_image(path: Annotated[str, Field(description="PNG/JPEG/WebP image in the workspace")],
                      region: Annotated[list[int] | None, Field(description="[left, top, right, bottom] in source "
                          "pixels, top-left origin; omit for an overview showing source dimensions")] = None,
                      max_size: Annotated[int, Field(ge=64, le=2048, description="Longest preview side in pixels; "
                          "small crops are magnified. This does not create additional source detail")] = 1536,
                      rotate: Annotated[Literal[0, 90, 180, 270], Field(description="Clockwise rotation AFTER cropping; "
                          "make vertical dimensions upright. Region coordinates always refer to the source")] = 0) -> Any:
        """Look closely at a drawing's dimensions, leaders, hatching or section view before modeling.
        Returns source dimensions, crop coordinates and an inline image. Read-only; writes no files.
        Pixel distances are not CAD dimensions: use the drawing's explicit callouts and datums."""
        result = rt.inspect_image(path, region, max_size, rotate)
        if result.get("ok"):
            png = base64.b64decode(result.pop("image_base64"))
            return [result, Image(data=png, format="png")]
        return result

    @mcp.tool()
    def list_operations(category: Annotated[str | None, Field(description="draw|edit|annotate|layer|block|layout|library: "
                                                                           "full schemas for that category; 'part' "
                                                                           "(or part_sketch|part_feature|part_edit) "
                                                                           "for 3D part operations")] = None,
                        ops: Annotated[list[str] | str | None, Field(description="Op names, 2D or 3D: full "
                                                                     "schemas for just these")] = None,
                        detail: Annotated[bool, Field(description="Full schemas for every op (~90K chars)")] = False) -> dict:
        """Operations usable in apply_operations. Without arguments: a compact index (name, category, summary,
        parameter names, * = required). Get JSON schemas (types, units, defaults, limits) with ops=[...] or category;
        part schemas point to a shared 'conventions' block (selectors, dims) in the same result."""
        return rt.list_operations(category, ops, detail)

    @mcp.tool()
    def create_drawing(path: Path_, units: Literal["mm", "cm", "m", "in", "ft"] = "mm",
                       template: Literal["mechanical", "blank"] = "mechanical",
                       dxf_version: Literal["R2000", "R2004", "R2007", "R2010", "R2013", "R2018"] = "R2010",
                       overwrite: bool = False,
                       annotation_scale: Annotated[float, Field(gt=0, description="N of plot scale 1:N; dimension and "
                                                                "linetype sizes are multiplied by N. 1 for parts, "
                                                                "50-100 for building plans in mm")] = 1.0) -> dict:
        """Create an empty drawing with an explicit length unit. 'mechanical' adds OUTLINE/HOLES/CENTER/DIM/TEXT/BORDER layers.
        A .FCStd path creates an empty 3D part (FreeCAD); units then set what bare numbers mean (stored in mm)."""
        return rt.create_drawing(path, units, template, dxf_version, overwrite, annotation_scale)

    @mcp.tool()
    def read_drawing(path: Path_) -> dict:
        """Drawing summary: units, extents, layers (with entity counts), entity type counts, blocks, tags, stored spec,
        integrity status and checkpoints. Counts and extents are for model space; 'layouts' lists the paper-space
        sheets and what they contain. A sheet holding geometry is usually the printed drawing (often a scaled copy of
        the part): edits to the part may have to be made there too (use the 'layout' parameter of ops).
        3D part: feature tree (op, tag, error, sketch planes and dimensions), parameters and the solid's volume,
        size, bbox and holes."""
        return rt.read_drawing(path)

    @mcp.tool()
    def inspect_entities(path: Path_,
                         filter: Annotated[dict | None, Field(description="DXF: {type, layer, tag, tag_prefix, layout}. "
                             "FCStd: {kind: 'features'|'faces'|'edges', feature?: <ref>, selector?: {...}}; "
                             "selector is for faces/edges, type/layer are DXF-only")] = None,  # noqa: A002
                         ids: Annotated[list[str] | None, Field(description="Entity handles or 'tag:<name>'")] = None,
                         window: Annotated[list[list[float]] | None, Field(description="[[x0,y0],[x1,y1]] crossing window")] = None,
                         limit: Annotated[int, Field(ge=1, le=5000)] = 200, offset: int = 0, detail: bool = True,
                         layout: Annotated[str | None, Field(description="'Model' (default), a paper layout name "
                                                                "from read_drawing.layouts, or '*' for all")] = None,
                         selection_mode: Literal["crossing", "window"] = "crossing",
                         polygon: list[list[float]] | None = None) -> dict:
        """List entities with geometry (paginated, filterable). Paper-space entities carry a 'layout' field.
        3D part: filter={kind: features|faces|edges, feature: <ref> (default the Body), selector: {...}} lists
        features, or faces/edges with their geometry; pass the selector you plan to use to see what it picks."""
        return rt.inspect_entities(path, filter, ids, limit, offset, detail, window, layout, selection_mode, polygon)

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
                                           "model space (ops choose their own layout)")] = None,
                         expected_revision: int | None = None,
                         preconditions: Annotated[dict | None, Field(description="Carry preview.preconditions "
                             "back unchanged; stale file/entity fingerprints refuse the edit")] = None) -> dict:
        """Execute an operation batch as one transaction: all params are checked first, any failure aborts with the
        file untouched; success checkpoints the old file, saves atomically, journals, and validates the result.
        The returned 'validation' is the same independent re-read of the saved file as validate_drawing (issues,
        failed requirements, passed ids, recognized counts, coverage): no separate validate_drawing call is needed
        unless you want its detail=true report. With 'create' a new drawing takes one call.
        On a .FCStd part the ops are part_operations (list_operations(category='part'))."""
        return rt.apply_operations(path, operations, dry_run, requirements, strict, label, create, bounds, layout,
                                   expected_revision, preconditions)

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
                   code: Annotated[str, Field(description="Drawing (.dxf): Python using ezdxf; the drawing is given "
                                                          "as `doc` (model space as `msp`); edit it in place, do not "
                                                          "open or save files. Paper layouts: doc.layouts.get(name). "
                                                          "Optionally set `result` to a JSON value to return it. "
                                                          "3D part (.FCStd): a CadQuery program (`cq` imported) "
                                                          "that sets `result` to the solid (cq.Workplane or Shape); "
                                                          "no file import/export.")],
                   dry_run: Annotated[bool, Field(description="Return the diff without saving")] = False,
                   requirements: Annotated[list[dict] | None, Field(description="Optional requirements to validate after")] = None,
                   strict: Annotated[bool, Field(description="Do not save if post-validation fails")] = False,
                   label: str | None = None,
                   language: Annotated[Literal["ezdxf", "cadquery", "freecad"] | None,
                                       Field(description="Default: ezdxf for .dxf, cadquery for .FCStd; 'freecad': "
                                                         "FreeCAD Part code (Part, App, Vector given) setting "
                                                         "`result` to a Part.Shape")] = None,
                   keep_features: Annotated[bool, Field(description="3D part: keep the Body's features and rebuild "
                                                        "them on the new solid (default: the part becomes the "
                                                        "script's solid alone)")] = False) -> dict:
        """For what the operation catalogue cannot express. Runs the script in a separate process (time-limited;
        imports limited to the library and standard math/data modules), then commits it like a batch: checkpoint,
        diff, validation, journal with the full script; rollback works as usual. On a 3D part the script's solid
        becomes the Body's base (a missing part is created), and part ops can build on it afterwards. Disabled
        unless the server runs with AGENTCAD_ALLOW_SCRIPTS=1. Prefer apply_operations when an operation exists."""
        return rt.run_script(path, code, label, dry_run, requirements, strict, language, keep_features)

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
        compared as displayed. Compact by default; detail=true for everything.
        3D part: FreeCAD re-opens and recomputes the file; checks feature errors, one Body with one valid solid,
        only editable PartDesign features (what CADBench requires), sketch constraints. Requirements: bbox {size},
        volume/area {value, rel_tolerance}, hole {diameter, count}, hole_count, solid_count, parameter {name,
        value}, center_of_mass, feature_count {feature_type, count|min}."""
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
    def get_diff(path: Path_, against: Annotated[str, Field(description="'previous', a checkpoint id 'cp-0003' or another file of the same kind")] = "previous",
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
    def export_drawing(path: Path_, output: str,
                       format: Literal["dxf", "svg", "json", "pdf", "dwg", "csv", "xlsx", "step", "iges", "brep", "stl", "obj",
                                       "png"] = "dxf",  # noqa: A002
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
                       monochrome: bool = False,
                       views: Annotated[list[str | list[float]] | None, Field(description="png of a 3D part: views "
                           "to render, names (iso, front, back, right, left, top, bottom, iso_back, iso_bottom) or "
                           "[x, y, z] directions from the part to the camera (the camera's position); several make one labelled grid. "
                           "Default ['iso']")] = None,
                       image_size: Annotated[int | None, Field(ge=64, le=2048, description="png: pixels per view "
                                                               "(default 512 for one view, 256 per view in a grid)")] = None,
                       fit: Annotated[Literal["view", "uniform"] | None, Field(description="png: 'view' (default) "
                           "fills each view with the part (no fixed scale: do not measure pixels); 'uniform' uses "
                           "one scale for every view")] = None,
                       reference: Annotated[str | None, Field(description="png of a 3D part: a reference image in the "
                           "workspace laid out as the same grid of views (same order; 2 columns up to 4 views). The "
                           "png is then a diff of each view, aligned to the reference's silhouette; the result scores "
                           "each view (outline, edges inside it) and their mean, compare.score: usually 0.95 or more "
                           "when the part matches")] = None,
                       inline_image: Annotated[bool, Field(description="png: also return the image in this result, "
                           "so you see it without opening the file (not above 2 MB)")] = True,
                       table: Literal["entities", "pid_lines", "bom"] = "entities") -> Any:
        """Export to another DXF version (R12 via a safe converter), SVG preview, JSON, PDF (plotted without
        external software: one page per layout, paper layouts 1:1 on their sheet, vector output, reports scale and
        too-small printed text), CSV/XLSX (table: entities, pid_lines or bom), or DWG (optional AutoCAD backend).
        3D parts: step, iges, brep, stl, obj, or png: a shaded preview (parallel projection, part centred and
        filling the frame, edges drawn) to look at what you built, e.g. against a reference image. It renders
        even a part that is not one valid solid, to show what went wrong.
        STEP/IGES/BREP are read back and compared with the part; a part that is not one valid solid is refused.
        A png comes back in the result as an image too (inline_image), after the usual JSON."""
        r = rt.export_drawing(path, output, format, dxf_version, overwrite, layout, paper, scale, orientation,
                              monochrome, views, image_size, fit, reference, table)
        if format == "png" and inline_image and r.get("ok"):
            png = rt.policy.root / r["output"]
            if png.is_file() and png.stat().st_size <= INLINE_IMAGE_MAX:
                return [r, Image(path=png)]
            r["inline_image"] = "skipped: file over 2 MB"
        return r

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
    def autocad_live(action: Annotated[Literal["status", "open", "reload", "pull", "zoom", "command"],
                                       Field(description="status: AutoCAD running? open drawings. open: show the "
                                             "drawing in AutoCAD (start=true launches it). reload: re-open after "
                                             "your changes. pull: commit the user's edits made in AutoCAD. zoom: "
                                             "show ids or a window. command: send a command line (policy-gated)")],
                     path: Annotated[str | None, Field(description="Drawing path (.dxf); all actions but status")] = None,
                     start: bool = False,
                     discard: Annotated[bool, Field(description="reload: drop unsaved edits made in AutoCAD")] = False,
                     ids: Annotated[list[str] | None, Field(description="zoom: entity ids or 'tag:<name>'")] = None,
                     window: Annotated[list[list[float]] | None, Field(description="zoom: [[x0,y0],[x1,y1]]")] = None,
                     command: str | None = None, label: str | None = None,
                     force: Annotated[bool, Field(description="pull: take AutoCAD's version even though the file "
                                                  "changed since AutoCAD opened it")] = False) -> dict:
        """Work alongside the user's running AutoCAD (Windows, optional). You keep editing with apply_operations;
        AutoCAD shows the result (servers started with AGENTCAD_LIVE_SYNC=1 reload it after every change, see
        'live' in results). Edits the user makes in AutoCAD come back with pull, as a normal checkpointed change."""
        return rt.autocad_live(action, path, start, discard, window, ids, command, label, force)

    @mcp.tool()
    def standard_library(item: Annotated[str | None, Field(description="A part, hole kind, P&ID symbol or GD&T "
                                                           "characteristic: its dimensions / details")] = None,
                         size: Annotated[str | None, Field(description="e.g. 'M8' or '6204'")] = None,
                         drawing: Annotated[str | None, Field(description="A drawing: its parts list (standard "
                                                              "parts, P&ID symbols and instruments)")] = None) -> dict:
        """Industry libraries: P&ID symbols (ISO 10628 / ISA-5.1), GD&T (ISO 1101), ISO bolts, nuts, washers,
        cap screws, ball bearings and hole sizes. No arguments: compact index. Draw them with the 'library' ops
        (add_pid_symbol, add_process_line, add_feature_control_frame, add_datum_feature, add_surface_finish,
        add_standard_hole, add_standard_part)."""
        return rt.standard_library(item, size, drawing)

    @mcp.tool()
    def get_metrics() -> dict:
        """Tool-call counts, durations and payload sizes for this server session (no model calls are made)."""
        return rt.get_metrics()

    for name in ("preflight", "measure_entities", "verify_dimensions", "refine_drawing", "deliver_drawing", "search_tools",
                 "read_engineering", "understand_drawing", "plant_takeoff"):
        mcp.add_tool(getattr(rt, name))
    profile = profile or os.environ.get("AGENTCAD_TOOL_PROFILE", "full")
    if profile == "full":
        return mcp
    if profile != "discovery":
        raise ValueError("AGENTCAD_TOOL_PROFILE must be full or discovery")
    discovery = FastMCP("agentcad", instructions="Search tools and operations, fetch their schema, then call a tool. "
                        "Operations execute through apply_operations. Paths are relative to the workspace.")

    @discovery.tool()
    async def search_tools(query: str, limit: int = 3) -> dict:
        """Find native tools and operations by task description or AutoCAD command name."""
        return await mcp.worker.run(rt.search_tools, query, limit)

    @discovery.tool()
    async def tool_schema(name: str) -> dict:
        """Get the complete input schema for one tool or drawing operation."""
        for t in await mcp.list_tools():
            if t.name == name:
                return t.model_dump(by_alias=True, exclude_none=True)
        return await mcp.worker.run(rt.list_operations, ops=[name], detail=True)

    @discovery.tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        """Call a discovered tool with its schema's arguments; the same validation and policy apply."""
        result = await mcp.call_tool(name, arguments)
        if isinstance(result, tuple) and len(result) == 2:
            content, structured = result
            if isinstance(structured, dict) and all(block.type == "text" for block in content):
                return structured
            result = content
        if isinstance(result, dict):
            return result
        if len(result) == 1 and result[0].type == "text":
            try:
                return json.loads(result[0].text)
            except ValueError:
                pass
        # Preserve native image/audio content instead of burying it in a JSON
        # string. This also handles full-profile tools returning mixed content.
        return result

    return discovery


def serve_stdio(policy: Policy | None = None) -> None:
    build_server(policy).run("stdio")


def main() -> None:
    from .install import ensure_workspace  # $AGENTCAD_ROOT, else ~/AgentCAD (not the client's start folder)
    serve_stdio(Policy(root=ensure_workspace()))


if __name__ == "__main__":
    main()
