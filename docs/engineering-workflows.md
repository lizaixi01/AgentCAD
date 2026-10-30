# Native engineering workflows and guarded edits

These capabilities use the same transactional DXF runtime as primitive drawing
operations. They require neither AutoCAD nor an LLM API. Readback loads the saved
DXF; it does not reuse a generator's in-memory answer. The public MCP, HTTP and
Python runtime share the implementation.

## Plan, inspect and edit

`preflight(spec)` validates a native design spec and returns `ready`, its exact
canonical `spec_hash`, generated requirements, and operation count. It validates
the existing native plate/bracket/spec vocabulary; it is not a universal engineering
specification or standards checker.

`apply_operations(..., dry_run=true)` returns `preview.revision` and
`preview.preconditions`. Carry both back with the intended operation batch:

```python
preview = rt.apply_operations("plate.dxf", ops, dry_run=True)["preview"]
result = rt.apply_operations(
    "plate.dxf", ops,
    expected_revision=preview["revision"],
    preconditions=preview["preconditions"],
)
```

Revisions advance with committed drawing replacements, including rollback; reads,
exports and refused edits do not advance them. Revisions persist across processes.
File hashes detect external edits, including changes to layer/style/block tables;
entity fingerprints identify changed top-level entities and their attached attributes.
`inspect_entities` exposes those fingerprints for narrower entity guards. A revision
alone does not detect a foreign editor's changes: use the returned preconditions.
The runtime checks again before committing, but does not provide an operating-system
compare-and-swap against an editor that ignores its workspace lock.

The MCP server runs synchronous CAD calls on one worker. Cancelling the awaiting
request does not stop a running mutation or allow the next mutation to overlap it.
The worker can finish and commit after cancellation; reread status before retrying.
There is no hard-kill guarantee for a hung native dependency.

## Measure, verify and deliver

`measure_entities(path, target)` computes analytic areas/perimeters for supported
lines, arcs, circles, bulged polylines and line/arc hatch boundaries. Hatch island
styles are respected. Elliptical hatch edges are explicitly unsupported; nesting
classification uses flattened loops. `trace_boundary` handles simple connected
LINE/ARC/open-polyline chains, retaining their bulges and sources. Branching or
intersecting networks require trimming first.

Spatial selection supports crossing/contained windows and conservative polygon
containment of entity bounding boxes. It does not claim an exact intersection test
for every curved entity. `block_from_entities` copies selected supported 2D entities
into a reusable block with a base point, preserving the source entities.

`verify_dimensions(path, requirements)` takes `{id, handle, value, tolerance?}` rows.
It binds DIMENSION anchors to actual geometry and compares the physical measurement
with the requirement. Displayed text/DIMLFAC mismatches remain separate findings:
a physical requirement can pass while the drawing is rejected for misleading text.
Existing `validate_drawing` dimension requirements retain their displayed-value
semantics, so existing clients do not silently change meaning.

`refine_drawing` reports before/after quality and attempts conservative exact-duplicate
removal. Differing styles, attributes and domain records are retained. Large deletions
still require the operation's `confirm_large`. It is not a general automatic repairer.

`deliver_drawing` requires a new/empty directory. It restores stored part-spec
requirements, checks every layout's generic integrity, and merges native P&ID,
architecture and mechanical critique into its quality gate. Each error or failed
requirement costs 15 points; each warning costs 3. Default `strict=true` also rejects
any error or failed requirement regardless of `min_score`. An explicit non-strict,
lower-threshold diagnostic delivery retains every failure in its manifest.
Domain reconstruction currently supports model space. Native domain records in
paper space or block definitions are explicitly rejected as unverified instead
of being labelled as passed; generic layout validation still runs.

Manifest version 2 records format-specific readback checks. DXF compares all layout
entities, block definitions, attributes, styles, page settings, selected drawing
variables and AgentCAD metadata. JSON compares its model-space projection; CSV/XLSX
compare saved cells with source text/attributes, preserving formula protections.
PDF checks page count, MediaBox, drawing content and clipping; SVG checks XML,
viewBox and drawing content. PDF/SVG checks are structural, not full geometry or
pixel equivalence. Source hashes are checked again before issuing the manifest.
A failed export can leave partial files without a manifest; retry in a fresh directory.

Linear/aligned, radius and diameter dimensions accept native numeric tolerances:
`tolerance={"lower": -0.012, "upper": 0.025, "precision": 3, "mode": "deviations"}`.
Lower/upper are signed deviations in displayed drawing units; unit strings are also
accepted. `mode="limits"` prints limits. `modify(set={"tolerance": ...})` updates and
rerenders; `null` clears it. Reopening `inspect_entities` returns the native values.
Insufficient decimal precision and fixed numeric text overrides are rejected.
Angular/ordinate tolerances are explicitly unsupported.
Precision is rechecked when an existing dimension changes, and on saved dimensions
throughout the entity database, including nested and unreferenced block definitions.
That integrity check does not certify the physical placement/scaling of every block
instance. New stacked tolerance text uses a 0.7 height factor, centred alignment and
at least half a nominal text height of line clearance; numeric values stay native.

`standard_library(item="iso_fit", size="25 H7/g6")` returns sourced hole/shaft
limits and clearance in mm. The bounded table covers **H7, h6 and g6, 10 < nominal
<= 500 mm**, with size steps upper-inclusive. Other classes/ranges are refused.
Use the returned lower/upper values as dimension tolerances (convert units for a
non-mm drawing). Data provenance and tested scope are in [fit tables](fit-tables.md).

CSV/XLSX export supports `table="entities"`, `"pid_lines"`, and `"bom"`. Values are
read from saved text, attributes and domain records. CSV prefixes formula-like text;
XLSX writes explicit string cells. Actual numeric mass values remain numeric. Numeric
identifiers with leading zeros or more than 15 digits remain strings. BOM quantities
count drawing instances; they are not procurement or assembly multiplicity estimates.

## P&ID

`apply_operations` operation `draw_pid` accepts `spec` sections `equipment`, `valves`,
`instruments`, `connectors`, `lines`, and optional `sheet`. Nodes use library symbols,
named ports and unique ids; lines reference `id.port`. For example:

```json
{"op":"draw_pid","spec":{
  "equipment":[
    {"id":"P1","symbol":"centrifugal_pump","x":0,"y":0},
    {"id":"P2","symbol":"centrifugal_pump","x":50,"y":20}
  ],
  "lines":[{"from":"P1.discharge","to":"P2.suction","number":"DN50-ABC"}]
}}
```

`read_engineering(path, kind="pid")` reconstructs connections from saved endpoints
and transformed ports, reports dangling/ambiguous ends, and returns the line list,
equipment list and instrument index. Explicit process-line numbers survive; signal
lines remain unnumbered. This domain reader expects AgentCAD's semantic records.
Foreign untagged plant drawings use the separate geometric takeoff reader below.

## Architecture and mechanical drawings

`draw_arch_plan` accepts orthogonal `walls` with ids, axes and thicknesses; hosted
door/window `openings`; straight `stairs`; located `rooms`; exterior dimension
`chains`; and `schedules`. Net room area is recomputed from wall solids and opening
thresholds, then checked against labels after reopening. The optional `sheet.scale`
sets annotation scale. Currently units are mm, walls are axis aligned, and rooms
with internal islands are refused. Door/window marks use `OPENING_MARK` attributes
to distinguish architectural marks from ISA instrument tags.

`draw_mechanical_assembly` accepts an A3 `sheet`, named revolved `parts` (segment
length/outer diameter/bore), optional end-view hole circles, and ISO library
`fasteners`. It creates front/end/full longitudinal-section views, real dimensions,
a parts list and linked balloons. `read_engineering(..., "mechanical")` rechecks
saved profiles, quantities and links; deleting a fastener invalidates the old BOM
and its balloon. Through-bore sections and the documented revolved profiles are
supported; this is a 2D drawing workflow, not a general 3D assembly solver or a
certificate of full ISO drawing compliance.

For architecture and mechanical readback, the native `quality_score` uses AgentCAD's
own documented validation penalties. It is distinct from the upstream benchmark's
quality score. The benchmark separately runs the upstream score unchanged.

## Foreign plant drawing estimates

`understand_drawing` describes services, clusters, outliers and likely units from
actual geometry/text. A disagreement between annotation evidence and `$INSUNITS`
is reported, not silently overwritten. `plant_takeoff(pid, layout, services?,
allowance=0.2)` connects segment endpoints, tees and fitting boxes, associates tag
positions between drawings, reads sizes/circuits, and reports evidence and uncertainty.

Current takeoff requires inferred mm units. Pipe lengths are rectilinear minimum
spanning estimates; cable lengths use panel/load Manhattan distances plus allowance
and upward rounding. Missing layout tags produce `C`/null length; inferred sizes
reduce confidence. These are preliminary quantities, not surveyed installed routes.
ARC junctions and nearby labels use the finite curve, including its angular span;
an endpoint on the chord is not treated as a junction. Missing equipment tags leave
electrical callouts as explicit unresolved rows with null cable lengths and warnings.
Language/service rules cover the vocabulary exercised by the published plant fixture;
arbitrary symbol libraries and all drawing conventions are not guaranteed.

## Optional compact tool profile

Set `AGENTCAD_TOOL_PROFILE=discovery` to advertise only `search_tools`, `tool_schema`
and `call_tool`. Search by task or AutoCAD command alias, fetch the full schema, then
call the native tool. Operations execute inside `apply_operations`. The default
`full` profile preserves the existing tool list. The schema-token measurement excludes
server instructions and uses the upstream ratio estimator, not billed tokenizer usage.
