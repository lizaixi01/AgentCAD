# 操作目录 (自动生成)

由 `scripts/gen_docs.py` 从 `agentcad.ops.REGISTRY` 生成，与 `list_operations` 返回一致。
长度参数接受数字（图纸单位）或带单位字符串（如 `"8mm"`）；角度为度、逆时针。

## annotate

### `add_angular_dim`

Angular dimension from vertex 'center' between rays to p1 and p2 (measured CCW from p1 to p2); 'radius' places the dimension arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  |  |
| `p1` | point | 是 |  |  |
| `p2` | point | 是 |  |  |
| `radius` | length >0 |  |  | Radius of the dimension arc (default: 0.6 x shorter ray) |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `text_height` | length >0 |  |  | Override text height |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_diameter_dim`

Diameter dimension of a circle/arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector |  |  | CIRCLE or ARC to dimension |
| `center` | point |  |  |  |
| `radius` | length >0 |  |  |  |
| `angle` | angle |  | 45.0 | Direction of the leader |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `text_height` | length >0 |  |  | Override text height |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_leader`

Leader (arrow polyline) with an MTEXT note at the last vertex.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `points` | points | 是 |  | Leader vertices, arrow at the first point |
| `text` | string | 是 |  |  |
| `text_height` | length >0 |  | 2.5 |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_linear_dim`

Linear dimension between two points. orientation: horizontal | vertical | aligned | rotated. The dimension line is placed at 'base' or at 'offset' from the measured points.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `p1` | point | 是 |  | First extension line origin |
| `p2` | point | 是 |  | Second extension line origin |
| `orientation` | enum ['horizontal', 'vertical', 'aligned', 'rotated'] |  | horizontal |  |
| `angle` | angle |  | 0.0 | Measurement direction for orientation=rotated |
| `offset` | length |  | 10.0 | Distance of the dimension line from the points (sign = side) |
| `base` | point |  |  | Explicit location of the dimension line |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `text_height` | length >0 |  |  | Override text height |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_mtext`

Multi-line text (MTEXT). Use '\P' or newlines for line breaks.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 |  | Text content |
| `insert` | point | 是 |  | Top-left insert point |
| `char_height` | length >0 |  | 2.5 | Character height |
| `width` | length >0 |  |  | Reference column width (optional) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_radius_dim`

Radius dimension of a circle/arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector |  |  | CIRCLE or ARC to dimension |
| `center` | point |  |  |  |
| `radius` | length >0 |  |  |  |
| `angle` | angle |  | 45.0 | Direction of the leader |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `text_height` | length >0 |  |  | Override text height |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_table`

Simple table drawn as grid lines + TEXT. 'insert' is the top-left corner. Cell texts get tags '<tag>.r<row>c<col>' when 'tag' is given.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `insert` | point | 是 |  |  |
| `rows` | list | 是 |  | List of rows, each a list of cell strings |
| `col_widths` | list | 是 |  | Column widths |
| `row_height` | length >0 |  | 8.0 |  |
| `text_height` | length >0 |  | 2.5 |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_text`

Single-line text.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 |  | Text content |
| `insert` | point | 是 |  | Alignment point |
| `height` | length >0 |  | 2.5 | Text height |
| `rotation` | angle |  | 0.0 | Rotation |
| `align` | enum ['left', 'center', 'right', 'middle', 'middle_center', 'top_left', 'top_center', 'bottom_center', 'middle_left'] |  | left | Alignment of the insert point |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_title_block`

Insert the standard 180x32 mm title block (ISO-like) with attributes ['TITLE', 'DWG_NO', 'MATERIAL', 'SCALE', 'UNITS', 'DRAWN_BY', 'DATE', 'SHEET']. 'insert' is the lower-right corner (usually the inner border corner).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `insert` | point | 是 |  |  |
| `fields` | object |  |  | Attribute values, e.g. {TITLE: 'Plate'} |
| `size_factor` | number >0 |  | 1.0 | Scale relative to the mm size |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `set_annotation_scale`

Set the plot scale 1:scale for annotations: dimension arrows/text/gaps (DIMSCALE) and linetype dash lengths (LTSCALE) are multiplied by 'scale'. Use e.g. 50 or 100 for building plans in mm. Existing dimensions are re-rendered.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `scale` | number >0 | 是 |  | N of the plot scale 1:N |

## block

### `define_block`

Define (or redefine) a block from a list of draw operations and attribute definitions.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `base_point` | point |  | (0.0, 0.0) |  |
| `entities` | list | 是 |  | Draw ops (['add_arc', 'add_circle', 'add_ellipse', 'add_line', 'add_mtext', 'add_point', 'add_polyline', 'add_rectangle', 'add_spline', 'add_text']) in block coordinates |
| `attributes` | list |  |  | [{tag, insert:[x,y], height, default}] |
| `if_exists` | enum ['error', 'skip', 'redefine'] |  | error |  |

### `insert_block`

Insert a block reference, filling attributes from 'attributes' {TAG: value}.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `insert` | point | 是 |  |  |
| `scale` | number >0 |  | 1.0 |  |
| `rotation` | angle |  | 0.0 |  |
| `attributes` | object |  |  |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `set_attributes`

Set attribute values of block references.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  |  |
| `values` | object | 是 |  | {TAG: value} |

## draw

### `add_arc`

Draw a circular arc, counter-clockwise from start_angle to end_angle (degrees). Alternatively give three points 'start', 'mid', 'end' on the arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point |  |  | Center |
| `radius` | length >0 |  |  | Radius |
| `start_angle` | angle |  |  | Start angle |
| `end_angle` | angle |  |  | End angle |
| `start` | point |  |  | 3-point form: start point |
| `mid` | point |  |  | 3-point form: point on arc |
| `end` | point |  |  | 3-point form: end point |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_circle`

Draw a circle. Give 'radius' or 'diameter'.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  | Center |
| `radius` | length >0 |  |  | Radius |
| `diameter` | length >0 |  |  | Diameter |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_ellipse`

Draw an ellipse (or elliptical arc) by semi-axes rx, ry and rotation.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  | Center |
| `rx` | length >0 | 是 |  | Semi-axis along the rotated X |
| `ry` | length >0 | 是 |  | Semi-axis along the rotated Y |
| `rotation` | angle |  | 0.0 | Rotation of the rx axis |
| `start_angle` | angle |  | 0.0 | Start parameter angle |
| `end_angle` | angle |  | 360.0 | End parameter angle |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_line`

Draw a straight line segment.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `start` | point | 是 |  | Start point |
| `end` | point | 是 |  | End point |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_point`

Draw a point entity.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `location` | point | 是 |  | Location |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_polyline`

Draw a 2D polyline (LWPOLYLINE). Points may carry a bulge as third value (bulge = tan(arc_angle/4), positive = CCW arc to the next vertex).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `points` | points | 是 |  | Vertices |
| `closed` | bool |  | False | Close the polyline |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_rectangle`

Draw an axis-aligned (optionally rotated) rectangle as a closed polyline. Give either 'corner' (lower-left) or 'center'.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `corner` | point |  |  | Lower-left corner |
| `center` | point |  |  | Center point |
| `width` | length >0 | 是 |  | Size along X |
| `height` | length >0 | 是 |  | Size along Y |
| `corner_radius` | length ≥0 |  | 0.0 | Fillet radius of all four corners |
| `rotation` | angle |  | 0.0 | Rotation about the corner/center |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `add_spline`

Draw a spline through fit points.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `fit_points` | points | 是 |  | Fit points |
| `degree` | int ≥1 ≤11 |  | 3 | Degree |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

## edit

### `array_polar`

Polar array about a center: 'count' items (including the original) over 'total_angle'.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `center` | point | 是 |  | Array center |
| `count` | int ≥2 ≤10000 | 是 |  | Total number of items including the original |
| `total_angle` | angle |  | 360.0 | Angle to fill |
| `rotate_items` | bool |  | True | Rotate the copies (else only translate) |

### `array_rect`

Rectangular array: copies arranged in rows and columns (the original is cell [0,0]).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `rows` | int ≥1 ≤1000 | 是 |  | Number of rows |
| `cols` | int ≥1 ≤1000 | 是 |  | Number of columns |
| `row_spacing` | length |  | 0.0 | Distance between rows (Y) |
| `col_spacing` | length |  | 0.0 | Distance between columns (X) |

### `chamfer`

AutoCAD CHAMFER of two LINEs with distances d1 (on line1) and d2 (on line2).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `line1` | selector | 是 |  |  |
| `line2` | selector | 是 |  |  |
| `d1` | length >0 | 是 |  |  |
| `d2` | length >0 |  |  | Defaults to d1 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `copy`

Copy entities by a displacement; 'count' > 1 repeats the displacement cumulatively.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `delta` | point |  |  | Displacement [dx, dy] |
| `base` | point |  |  | Base point |
| `to` | point |  |  | Destination of the base point |
| `count` | int ≥1 ≤10000 |  | 1 | Number of copies |

### `delete`

Erase entities. Deleting more than the policy threshold needs confirm_large=true.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `confirm_large` | bool |  | False | Confirm a large deletion |

### `explode`

Explode block references (INSERT) or polylines into their component entities.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |

### `extend`

AutoCAD EXTEND: lengthen a LINE end until it meets the nearest boundary edge.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Single LINE |
| `edges` | selector | 是 |  | Boundary edges |
| `end` | enum ['start', 'end', 'auto'] |  | auto | Which end to extend ('auto' = the end nearer to an intersection) |

### `fillet`

AutoCAD FILLET of two LINEs: trims/extends both to tangency and adds a tangent ARC (radius 0 = sharp corner).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `line1` | selector | 是 |  |  |
| `line2` | selector | 是 |  |  |
| `radius` | length ≥0 | 是 |  |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `mirror`

Mirror entities about the line p1-p2. Text stays readable (MIRRTEXT=0).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `p1` | point | 是 |  | First point of mirror line |
| `p2` | point | 是 |  | Second point of mirror line |
| `keep_original` | bool |  | True | Keep the source entities (mirror a copy) |

### `modify`

Set geometric fields of ONE entity, e.g. {target, set: {radius: 5}} for a circle, {set: {start: [0,0], end: [10,0]}} for a line, {set: {points: [...], closed: true}} for a polyline, {set: {text: 'A'}} for text.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `set` | object | 是 |  | Field -> new value |

### `move`

Translate entities by a displacement (or from 'base' to 'to').

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `delta` | point |  |  | Displacement [dx, dy] |
| `base` | point |  |  | Base point |
| `to` | point |  |  | Destination of the base point |

### `offset`

Create an offset copy of a LINE, CIRCLE, ARC or straight-segment LWPOLYLINE. The side is given by 'side_point' (preferred) or by the sign of 'distance' (positive = left of line direction / outside of circles and closed polylines).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `distance` | length | 是 |  | Offset distance |
| `side_point` | point |  |  | A point on the side to offset towards |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |

### `rotate`

Rotate entities about a center point (degrees, CCW).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `angle` | angle | 是 |  | Rotation angle |
| `center` | point | 是 |  | Rotation center |

### `scale`

Uniformly scale entities about a base point.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `factor` | number >0 | 是 |  | Scale factor |
| `center` | point | 是 |  | Base point |

### `set_properties`

Change layer / color / linetype / lineweight / tag of entities.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `layer` | string |  |  |  |
| `color` | int ≥0 ≤257 |  |  |  |
| `linetype` | string |  |  |  |
| `lineweight` | int |  |  |  |
| `tag` | string |  |  | New tag (only valid for a single entity) |

### `stretch`

AutoCAD STRETCH with a crossing window: entities entirely inside move; LINE end points, polyline vertices and dimension definition points inside the window move; circles/arcs/text/blocks move if their center/insert point is inside. Dimensions are re-measured.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `window` | points | 是 |  | Two opposite corners of the crossing window |
| `delta` | point | 是 |  | Displacement [dx, dy] |

### `trim`

AutoCAD TRIM: remove the part of the target (LINE, ARC or CIRCLE) that contains 'pick', bounded by its nearest intersections with the cutting edges. A LINE trimmed in the middle is split in two.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Single LINE / ARC / CIRCLE to trim |
| `edges` | selector | 是 |  | Cutting edges |
| `pick` | point | 是 |  | A point on the portion to remove |

## layer

### `create_layer`

Create a layer (no-op with if_exists='skip').

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `color` | int ≥1 ≤255 |  | 7 | ACI color |
| `linetype` | string |  | Continuous |  |
| `lineweight` | int |  | -3 | 1/100 mm, -3 = default |
| `if_exists` | enum ['error', 'skip', 'update'] |  | error |  |

### `delete_layer`

Delete a layer. Fails if entities are on it unless delete_entities=true.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `delete_entities` | bool |  | False |  |

### `modify_layer`

Change layer properties (color, linetype, lineweight, on, frozen, locked, rename).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `color` | int ≥1 ≤255 |  |  |  |
| `linetype` | string |  |  |  |
| `lineweight` | int |  |  |  |
| `on` | bool |  |  |  |
| `frozen` | bool |  |  |  |
| `locked` | bool |  |  |  |
| `new_name` | string |  |  |  |

## 约束类型

- 可检查: angle, coincident, concentric, diameter, distance, equal, fixed, horizontal, length, parallel, perpendicular, radius, symmetric, tangent, vertical
- 可强制（顺序直接修改，非联立求解）: coincident, concentric, diameter, distance, equal, fixed, horizontal, length, parallel, perpendicular, radius, vertical
