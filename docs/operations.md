# 操作目录 (自动生成)

由 `scripts/gen_docs.py` 从 `agentcad.ops.REGISTRY` 和 `agentcad.part.ops.PART_REGISTRY` 生成，与 `list_operations` 返回一致。
长度参数接受数字（图纸单位）或带单位字符串（如 `"8mm"`）；角度为度、逆时针。
`part_*` 类别是三维零件（.FCStd）的操作，`dim` 类型还接受表达式（如 `"=Params.width"`），见 [part-3d.md](part-3d.md)。

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
| `tolerance` | object |  |  | Signed lower/upper deviations in displayed drawing units (or unit strings); optional precision=3 and mode=deviations\|limits. Linear/radius/diameter dimensions only. |
| `text_height` | length >0 |  |  | Override text height |
| `length_factor` | number >0 |  |  | DIMLFAC: displayed value = measured length x factor, e.g. 1/0.325 on a sheet that shows the part at scale 0.325 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_center_mark`

Center mark of CIRCLEs / ARCs (AutoCAD CENTERMARK): a horizontal and a vertical LINE through each center, 'extension' beyond the radius. Layer CENTER with linetype CENTER unless given. With 'tag' the lines are tagged '<tag>.h' / '<tag>.v' (several targets: '<tag>.<i>.h').

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | CIRCLE / ARC entities |
| `extension` | length ≥0 |  |  | Overshoot past the circle (default: max(2, radius/2)) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_diameter_dim`

Diameter dimension of a circle/arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector |  |  | CIRCLE or ARC to dimension |
| `center` | point |  |  |  |
| `radius` | length >0 |  |  |  |
| `angle` | angle |  | 45.0 | Direction of the leader |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `tolerance` | object |  |  | Signed lower/upper deviations in displayed drawing units (or unit strings); optional precision=3 and mode=deviations\|limits. Linear/radius/diameter dimensions only. |
| `text_height` | length >0 |  |  | Override text height |
| `length_factor` | number >0 |  |  | DIMLFAC: displayed value = measured length x factor, e.g. 1/0.325 on a sheet that shows the part at scale 0.325 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `tolerance` | object |  |  | Signed lower/upper deviations in displayed drawing units (or unit strings); optional precision=3 and mode=deviations\|limits. Linear/radius/diameter dimensions only. |
| `text_height` | length >0 |  |  | Override text height |
| `length_factor` | number >0 |  |  | DIMLFAC: displayed value = measured length x factor, e.g. 1/0.325 on a sheet that shows the part at scale 0.325 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_mtext`

Multi-line text (MTEXT). Use '\P' or newlines for line breaks.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 |  | Text content |
| `insert` | point | 是 |  | Top-left insert point |
| `char_height` | length >0 |  | 2.5 | Character height |
| `width` | length >0 |  |  | Reference column width (optional) |
| `style` | string |  |  | Text style (see create_text_style); default Standard |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_ordinate_dim`

Ordinate (datum) dimension: the X or Y distance of 'feature' from 'origin', written at the end of a leader from the feature to 'leader_end'.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `feature` | point | 是 |  | Point being dimensioned |
| `leader_end` | point | 是 |  | End of the leader, where the text goes |
| `axis` | enum ['x', 'y'] | 是 |  | 'x' measures the X distance (vertical leader), 'y' the Y distance |
| `origin` | point |  | (0.0, 0.0) | Datum point (UCS origin of the ordinates) |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `tolerance` | object |  |  | Signed lower/upper deviations in displayed drawing units (or unit strings); optional precision=3 and mode=deviations\|limits. Linear/radius/diameter dimensions only. |
| `text_height` | length >0 |  |  | Override text height |
| `length_factor` | number >0 |  |  | DIMLFAC: displayed value = measured length x factor, e.g. 1/0.325 on a sheet that shows the part at scale 0.325 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_radius_dim`

Radius dimension of a circle/arc.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector |  |  | CIRCLE or ARC to dimension |
| `center` | point |  |  |  |
| `radius` | length >0 |  |  |  |
| `angle` | angle |  | 45.0 | Direction of the leader |
| `text` | string |  |  | Text override; '<>' stands for the measured value |
| `tolerance` | object |  |  | Signed lower/upper deviations in displayed drawing units (or unit strings); optional precision=3 and mode=deviations\|limits. Linear/radius/diameter dimensions only. |
| `text_height` | length >0 |  |  | Override text height |
| `length_factor` | number >0 |  |  | DIMLFAC: displayed value = measured length x factor, e.g. 1/0.325 on a sheet that shows the part at scale 0.325 |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_text`

Single-line text.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 |  | Text content |
| `insert` | point | 是 |  | Alignment point |
| `height` | length >0 |  | 2.5 | Text height |
| `rotation` | angle |  | 0.0 | Rotation |
| `align` | enum ['left', 'center', 'right', 'middle', 'middle_center', 'top_left', 'top_center', 'bottom_center', 'middle_left'] |  | left | Alignment of the insert point |
| `style` | string |  |  | Text style (see create_text_style); default Standard |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `create_text_style`

Create a text style for add_text / add_mtext 'style'. 'font' is an SHX (e.g. gbenor.shx, txt.shx) or TrueType file (e.g. simsun.ttc, arial.ttf); SHX fonts need 'big_font' (e.g. gbcbig.shx) to show Chinese, which is the default for SHX fonts.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  | Style name |
| `font` | string |  | gbenor.shx | Font file |
| `big_font` | string |  |  | Big font for CJK characters (SHX fonts only; default gbcbig.shx) |
| `width_factor` | number >0 |  | 1.0 | Character width factor |
| `oblique` | angle |  | 0.0 | Slant angle |
| `height` | length ≥0 |  | 0.0 | Fixed text height (0 = set per text) |
| `if_exists` | enum ['error', 'skip', 'update'] |  | error |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `set_annotation_scale`

Set the plot scale 1:scale for annotations: dimension arrows/text/gaps (DIMSCALE) and linetype dash lengths (LTSCALE) are multiplied by 'scale'. Use e.g. 50 or 100 for building plans in mm. Existing dimensions are re-rendered.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `scale` | number >0 | 是 |  | N of the plot scale 1:N |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

## block

### `block_from_entities`

WBLOCK: define a reusable block by copying selected drawing entities; sources remain.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `target` | selector | 是 |  |  |
| `base_point` | point |  | (0.0, 0.0) |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `define_block`

Define (or redefine) a block from a list of draw operations and attribute definitions.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `base_point` | point |  | (0.0, 0.0) |  |
| `entities` | list | 是 |  | Draw ops (['add_arc', 'add_circle', 'add_donut', 'add_ellipse', 'add_hatch', 'add_line', 'add_mtext', 'add_point', 'add_polygon', 'add_polyline', 'add_rectangle', 'add_spline', 'add_text']) in block coordinates |
| `attributes` | list |  |  | [{tag, insert:[x,y], height, default}] |
| `if_exists` | enum ['error', 'skip', 'redefine'] |  | error |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `set_attributes`

Set attribute values of block references.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  |  |
| `values` | object | 是 |  | {TAG: value} |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_donut`

AutoCAD DONUT: a filled ring (inner_diameter 0 = filled disc), stored as AutoCAD does: a closed LWPOLYLINE of two half-circle segments with a constant width.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  | Center |
| `outer_diameter` | length >0 | 是 |  | Outer diameter |
| `inner_diameter` | length ≥0 |  | 0.0 | Inner diameter (0 = solid disc) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_hatch`

Fill an area (AutoCAD HATCH). Boundary: 'boundary' = closed LWPOLYLINE / CIRCLE / full ELLIPSE entities (several = islands, filled by the odd-even rule), or 'points' (outer loop, bulges allowed) plus optional 'holes' (list of point loops). 'pattern' is SOLID (default) or a standard pattern such as ANSI31 (section lines), ANSI37, ANGLE, BRICK, DOTS, NET, AR-CONC, AR-SAND, with 'pattern_scale' and 'pattern_angle'. The hatch is not associative: editing the boundary later does not update it. 'behind' (default true) draws it under everything already in the layout.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `boundary` | selector |  |  | Closed boundary entities |
| `points` | points |  |  | Outer loop (instead of 'boundary') |
| `holes` | list |  |  | Inner loops, each a list of [x, y] (or [x, y, bulge]) |
| `pattern` | string |  | SOLID | SOLID or a pattern name (ANSI31, ...) |
| `pattern_scale` | number >0 |  | 1.0 | Pattern scale |
| `pattern_angle` | angle |  | 0.0 | Pattern rotation |
| `style` | enum ['normal', 'outer', 'ignore'] |  | normal |  |
| `behind` | bool |  | True | Send the hatch to the back of the draw order |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_polygon`

Regular polygon (AutoCAD POLYGON) as a closed polyline. Size by 'radius' with mode 'inscribed' (corners on the circle) or 'circumscribed' (edge midpoints on the circle, e.g. a hex nut across flats), or by 'side_length'. Without 'rotation' the bottom edge is horizontal, as AutoCAD does for a typed radius; 'rotation' is the direction of the first corner (inscribed / side_length) or of the first edge midpoint (circumscribed).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  | Center |
| `sides` | int ≥3 ≤1024 | 是 |  | Number of sides |
| `radius` | length >0 |  |  | Radius of the construction circle |
| `mode` | enum ['inscribed', 'circumscribed'] |  | inscribed | How 'radius' is measured |
| `side_length` | length >0 |  |  | Edge length (instead of 'radius') |
| `rotation` | angle |  |  | Direction of the first corner / edge midpoint |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_polyline`

Draw a 2D polyline (LWPOLYLINE). Points may carry a bulge as third value (bulge = tan(arc_angle/4), positive = CCW arc to the next vertex).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `points` | points | 是 |  | Vertices |
| `closed` | bool |  | False | Close the polyline |
| `width` | length ≥0 |  | 0.0 | Constant segment width, drawn filled (PLINE Width) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_ray`

Construction line from 'point' to infinity in one direction (AutoCAD RAY).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `point` | point | 是 |  | A point on the line |
| `through` | point |  |  | Second point that gives the direction |
| `angle` | angle |  |  | Direction (instead of 'through') |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_xline`

Construction line infinite in both directions (AutoCAD XLINE). Not counted in extents.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `point` | point | 是 |  | A point on the line |
| `through` | point |  |  | Second point that gives the direction |
| `angle` | angle |  |  | Direction (instead of 'through') |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `trace_boundary`

BPOLY / BOUNDARY: trace a simple closed LINE/ARC/open-polyline chain around an interior point. Sources remain. Intersecting or branching networks require trimming first.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `point` | point | 是 |  |  |
| `tolerance` | length >0 |  | 1e-06 |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `array_rect`

Rectangular array: copies arranged in rows and columns (the original is cell [0,0]).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `rows` | int ≥1 ≤1000 | 是 |  | Number of rows |
| `cols` | int ≥1 ≤1000 | 是 |  | Number of columns |
| `row_spacing` | length |  | 0.0 | Distance between rows (Y) |
| `col_spacing` | length |  | 0.0 | Distance between columns (X) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `break`

AutoCAD BREAK: remove the part of a LINE, ARC or CIRCLE between p1 and p2 (points are projected onto the entity). Without p2 a LINE or ARC is split at p1 into two touching pieces. A CIRCLE loses the counter-clockwise part from p1 to p2 and becomes an ARC. The first piece keeps the entity's id and tag.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Single LINE / ARC / CIRCLE |
| `p1` | point | 是 |  | First break point |
| `p2` | point |  |  | Second break point (omit to split at p1) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `copy`

Copy entities by a displacement; 'count' > 1 repeats the displacement cumulatively.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `delta` | point |  |  | Displacement [dx, dy] |
| `base` | point |  |  | Base point |
| `to` | point |  |  | Destination of the base point |
| `count` | int ≥1 ≤10000 |  | 1 | Number of copies |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `delete`

Erase entities. Deleting more than the policy threshold needs confirm_large=true.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `confirm_large` | bool |  | False | Confirm a large deletion |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `draw_order`

AutoCAD DRAWORDER: show the targets on top of ('front') or under ('back') every other entity of their layout, e.g. a solid hatch behind its outline.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `order` | enum ['front', 'back'] | 是 |  | Where to put the targets |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `edit_hatch`

Change HATCH island style, preserving its boundaries.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  |  |
| `style` | enum ['normal', 'outer', 'ignore'] | 是 |  |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `explode`

Explode block references (INSERT) or polylines into their component entities.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `extend`

AutoCAD EXTEND: lengthen a LINE end until it meets the nearest boundary edge.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Single LINE |
| `edges` | selector | 是 |  | Boundary edges |
| `end` | enum ['start', 'end', 'auto'] |  | auto | Which end to extend ('auto' = the end nearer to an intersection) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `join`

AutoCAD JOIN / PEDIT Join: chain LINEs, ARCs and open LWPOLYLINEs whose ends meet (within 'tolerance') into one LWPOLYLINE, closed when the chain closes. The sources are deleted; the polyline takes the layer, color, linetype and lineweight of the first target, and its tag unless 'tag' is given.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to join (at least 2, or 1 polyline whose ends meet) |
| `tolerance` | length ≥0 |  | 1e-06 | Largest gap between ends that still counts as touching |
| `tag` | string |  |  | Tag for the resulting polyline |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `mirror`

Mirror entities about the line p1-p2. Text stays readable (MIRRTEXT=0).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `p1` | point | 是 |  | First point of mirror line |
| `p2` | point | 是 |  | Second point of mirror line |
| `keep_original` | bool |  | True | Keep the source entities (mirror a copy) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `modify`

Set fields of ONE entity, e.g. {target, set: {radius: 5}} for a circle, {set: {start: [0,0], end: [10,0]}} for a line, {set: {points: [...], closed: true}} for a polyline, {set: {text: 'A'}} for text, {set: {text: '4X <>', text_height: 3.5, length_factor: 2}} for a dimension.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `set` | object | 是 |  | Field -> new value |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `move`

Translate entities by a displacement (or from 'base' to 'to').

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `delta` | point |  |  | Displacement [dx, dy] |
| `base` | point |  |  | Base point |
| `to` | point |  |  | Destination of the base point |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `purge`

AutoCAD PURGE: delete layers, blocks, text styles and linetypes that nothing uses. Never purges layer 0 / Defpoints / the current layer, the Standard style, ByLayer / ByBlock / Continuous, arrow blocks ('_' names) or anonymous blocks. Repeats until nothing more is unused (nested blocks).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `kinds` | list |  |  | Subset of ['layers', 'blocks', 'text_styles', 'linetypes'] (default: all) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `remove_duplicates`

OVERKILL: remove exact duplicate geometry on each layout, keeping the first.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `tolerance` | length >0 |  | 1e-06 |  |
| `confirm_large` | bool |  | False |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `rotate`

Rotate entities about a center point (degrees, CCW).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `angle` | angle | 是 |  | Rotation angle |
| `center` | point | 是 |  | Rotation center |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `scale`

Uniformly scale entities about a base point.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Entities to operate on |
| `factor` | number >0 | 是 |  | Scale factor |
| `center` | point | 是 |  | Base point |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `stretch`

AutoCAD STRETCH with a crossing window: entities entirely inside move; LINE end points, polyline vertices and dimension definition points inside the window move; circles/arcs/text/blocks move if their center/insert point is inside. Dimensions are re-measured.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `window` | points | 是 |  | Two opposite corners of the crossing window |
| `delta` | point | 是 |  | Displacement [dx, dy] |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `trim`

AutoCAD TRIM: remove the part of the target (LINE, ARC or CIRCLE) that contains 'pick', bounded by its nearest intersections with the cutting edges. A LINE trimmed in the middle is split in two.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  | Single LINE / ARC / CIRCLE to trim |
| `edges` | selector | 是 |  | Cutting edges |
| `pick` | point | 是 |  | A point on the portion to remove |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

## engineering

### `draw_arch_plan`

Draw an orthogonal wall plan with hosted doors/windows, stairs, measured room labels, dimensions and schedules. Room detection reads wall solids and opening thresholds.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `spec` | object | 是 |  |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `draw_mechanical_assembly`

Draw revolved parts with front/end/longitudinal-section views, chain dimensions, standard fasteners, an A3 sheet, a drawing-derived BOM and linked balloons.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `spec` | object | 是 |  |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `draw_pid`

Create a port-connected P&ID from equipment, valves, instruments, connectors and lines. Entity-local semantic records survive DXF; read_engineering reconstructs and checks the graph.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `spec` | object | 是 |  |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `delete_layer`

Delete a layer. Fails if entities are on it unless delete_entities=true.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `delete_entities` | bool |  | False |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

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
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

## layout

### `add_viewport`

Add a viewport to a paper-space layout (pass layout=<name>) that shows model space at a fixed scale. center/width/height are on the paper in mm; scale is paper mm per model unit (0.5 = 1:2, 2 = 2:1). view_center defaults to the centre of everything in model space; width/height default to the model extents at that scale plus a 5% margin.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | point | 是 |  | Viewport centre on the paper (mm) |
| `scale` | number >0 | 是 |  | Paper mm per model unit, e.g. 0.5 for 1:2 |
| `width` | number >0 |  |  | Viewport width on the paper (mm) |
| `height` | number >0 |  |  | Viewport height on the paper (mm) |
| `view_center` | point |  |  | Model-space point shown at the viewport centre |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `change_space`

CHSPACE: transfer entities to another layout with an explicit scale and translation (paper millimetres per model unit). Original handles are retained.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | selector | 是 |  |  |
| `destination` | string | 是 |  |  |
| `scale` | number >0 |  | 1 |  |
| `delta` | point |  | [0, 0] |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `create_layout`

Create a paper-space layout (a printed sheet) with its paper size. Draw the frame and title block into it with the usual ops and layout=<name>, then show the model with add_viewport.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `paper` | enum ['A0', 'A1', 'A2', 'A3', 'A4', 'custom'] |  | A3 |  |
| `orientation` | enum ['landscape', 'portrait'] |  | landscape |  |
| `width` | number >0 |  |  | Paper width in mm (paper='custom') |
| `height` | number >0 |  |  | Paper height in mm (paper='custom') |
| `if_exists` | enum ['error', 'skip'] |  | error |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `set_page_setup`

Change an existing layout's physical paper size and plot style. ISO sizes and ANSI B (432 by 279 mm) are supported. monochrome.ctb is rendered by the native PDF exporter.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  |  |
| `paper` | enum ['A0', 'A1', 'A2', 'A3', 'A4', 'ANSI_B', 'custom'] |  | A3 |  |
| `orientation` | enum ['landscape', 'portrait'] |  | landscape |  |
| `width` | number >0 |  |  |  |
| `height` | number >0 |  |  |  |
| `ctb` | enum ['', 'monochrome.ctb'] |  |  |  |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

## library

### `add_datum_feature`

GD&T datum feature symbol: a filled triangle on the feature at 'on', a line to a square box centred at 'insert' with the datum letter. All entities share the tag.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `letter` | string | 是 |  |  |
| `on` | point | 是 |  | Point on the datum feature |
| `insert` | point | 是 |  | Centre of the letter box |
| `height` | length >0 |  |  | Text height (default 3.5 mm on paper) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_feature_control_frame`

GD&T feature control frame (ISO 1101 / ASME Y14.5): characteristic symbol, tolerance (with diameter sign and material modifier) and up to three datum references such as 'A', 'B(M)', 'A-B'. 'insert' is the frame's lower-left corner; 'leader_to' adds a leader with an arrow to the feature. Text height defaults to 3.5 mm on paper; the frame is twice as high. All entities share the tag.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `insert` | point | 是 |  |  |
| `characteristic` | enum ['angularity', 'circular_runout', 'circularity', 'concentricity', 'cylindricity', 'flatness', 'parallelism', 'perpendicularity', 'position', 'profile_line', 'profile_surface', 'straightness', 'symmetry', 'total_runout'] | 是 |  |  |
| `tolerance` | string | 是 |  | e.g. '0.05' |
| `diameter` | bool |  | False | Cylindrical zone: prefix %%c (Ø) |
| `modifier` | enum ['M', 'L', 'S', 'P', 'F', 'T', 'U'] |  |  | Tolerance modifier, e.g. M = MMC |
| `datums` | list |  |  | Datum references, primary first |
| `height` | length >0 |  |  | Text height |
| `leader_to` | point |  |  |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_pid_symbol`

P&ID symbol (ISO 10628 / ISA-5.1 style) as a block with a TAG attribute (instruments: FUNC and LOOP, from tag_no 'FIC-101'). With 'on' (a pipe: LINE or open LWPOLYLINE) an inline symbol (valves, reducer, flange, strainer, orifice) is placed on the pipe at the point nearest 'insert' (default its middle), turned along it, and the pipe is cut where the symbol sits. 'size' is the symbol width (default 10 mm on paper). See standard_library for the symbol list.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `symbol` | enum ['ball_valve', 'blind_flange', 'butterfly_valve', 'centrifugal_pump', 'check_valve', 'compressor', 'control_valve', 'flange', 'flow_arrow', 'gate_valve', 'globe_valve', 'heat_exchanger', 'instrument_dcs', 'instrument_field', 'instrument_panel', 'instrument_plc', 'orifice_plate', 'reducer', 'relief_valve', 'strainer', 'tank', 'three_way_valve', 'vessel_horizontal', 'vessel_vertical'] | 是 |  |  |
| `insert` | point |  |  | Position (or point near the pipe with 'on') |
| `on` | selector |  |  | Pipe to put an inline symbol on |
| `rotation` | angle |  | 0.0 | Rotation; with 'on' added to the pipe direction (180 reverses a check valve) |
| `size` | length >0 |  |  | Symbol width |
| `tag_no` | string |  |  | Tag number, e.g. 'V-101' or 'FIC-101' |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_process_line`

P&ID line through 'points' (one LWPOLYLINE): process, utility, signal_electric (dashed) or signal_pneumatic (with // marks), on a PID_* layer unless 'layer' is given. Optional flow arrows on each segment and a line number written along the longest segment. Arrows, marks and the number are tagged '<tag>.deco'.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `points` | points | 是 |  |  |
| `kind` | enum ['process', 'utility', 'signal_electric', 'signal_pneumatic'] |  | process |  |
| `line_number` | string |  |  | e.g. '2"-P-1001-A1A' |
| `flow_arrows` | bool |  | True | Arrow in the middle of each segment, pointing along it |
| `arrow_size` | length >0 |  |  | Default 4 mm on paper |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_standard_hole`

ISO metric holes at one or more 'centers' in one op: clearance (ISO 273, fit fine|medium|coarse), tapped (tap-drill circle plus the thin 3/4 thread circle of ISO 6410, on layer THREAD) or counterbore for ISO 4762 cap screws. Circles go on HOLES unless 'layer' is given; center marks are added by default. The result gives the diameters and a callout text (e.g. 'M8-6H') for a leader.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `centers` | points | 是 |  |  |
| `size` | enum ['M3', 'M4', 'M5', 'M6', 'M8', 'M10', 'M12', 'M14', 'M16', 'M20', 'M24'] | 是 |  |  |
| `kind` | enum ['clearance', 'tapped', 'counterbore'] |  | clearance |  |
| `fit` | enum ['fine', 'medium', 'coarse'] |  | medium |  |
| `center_marks` | bool |  | True |  |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_standard_part`

ISO standard part as a block, true size: hex_bolt (ISO 4014/4017), hex_nut (ISO 4032), washer (ISO 7089), socket_head_cap_screw (ISO 4762) in sizes M3-M24, or ball_bearing (ISO 15, 6000-6310). view 'top' looks along the axis; 'side' stands on 'insert' (bolts and screws: the bearing face under the head, shank pointing -y before 'rotation'; bearings: centred). Bolts and screws need 'length' for the side view. The block carries PART / STANDARD / SIZE attributes for the parts list (standard_library drawing=...).

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `part` | enum ['hex_bolt', 'hex_nut', 'washer', 'socket_head_cap_screw', 'ball_bearing'] | 是 |  |  |
| `size` | string | 是 |  | 'M10' or '6204' |
| `insert` | point | 是 |  |  |
| `view` | enum ['top', 'side'] |  | side |  |
| `length` | length >0 |  |  | Nominal length (bolts and screws) |
| `rotation` | angle |  | 0.0 |  |
| `count_in_bom` | bool |  | True | false for a second view of a part already counted |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

### `add_surface_finish`

Surface texture symbol (ISO 1302 / ISO 21920): tip at 'insert' on the surface; process any | removal_required (closed V) | removal_prohibited (circle); optional Ra value written over the extension bar. 'rotation' turns the symbol about its tip.

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `insert` | point | 是 |  |  |
| `ra` | string |  |  | e.g. '3.2' (written 'Ra 3.2') |
| `process` | enum ['any', 'removal_required', 'removal_prohibited'] |  | any |  |
| `rotation` | angle |  | 0.0 |  |
| `height` | length >0 |  |  | Text height (default 3.5 mm on paper) |
| `layer` | string |  |  | Layer name (created on the fly if missing) |
| `color` | int ≥0 ≤257 |  |  | ACI color (256 = BYLAYER) |
| `linetype` | string |  |  | Linetype name, e.g. CONTINUOUS, CENTER, DASHED |
| `lineweight` | int |  |  | Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER |
| `tag` | string |  |  | Semantic tag for later reference as 'tag:<name>' |
| `if_tag_exists` | enum ['error', 'skip', 'replace'] |  | error | Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays) |
| `layout` | string |  |  | Layout to work in: 'Model' (default) or a paper-space layout name from read_drawing. New entities go there and filter selectors search it; edits that derive entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout |

## part_edit

### `delete_feature`

Delete a feature (cascade=true also deletes the features that use it)

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `feature` | string | 是 |  | feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `cascade` | bool |  | False | Delete dependent features too |

### `modify_feature`

Change parameters of a feature made by an earlier op (same names as that op, e.g. {length: 12} for a pad, {shapes: [...]} to redraw a sketch, {edges: ...} for a fillet). Later features follow

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `feature` | string | 是 |  | feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `set` | object | 是 |  | {param: new value} |

### `set_parameters`

Create or change named parameters (a FreeCAD spreadsheet 'Params'). Reference them in any dimension as '=Params.<name>'; changing one later re-solves every feature that uses it. Names must not be units or reserved words (t, m, mm, deg, pi)

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `params` | object | 是 |  | {name: number \| '8mm' \| '=expression'} |

## part_feature

### `chamfer`

Bevel edges of the solid

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `edges` | any | 是 |  | edge selector, re-resolved after every edit: 'all', 'Edge3', or an object with any of type (line\|circle\|...), direction (x\|y\|z\|-z\|[x,y,z], lines parallel to it), axis (circles around it), radius\|diameter, length, x\|y\|z (all points on that coordinate), box [[x0,y0,z0],[x1,y1,z1]], face (a face selector: edges of those faces), near [x,y,z] + count (nearest ones); a list unites selectors |
| `size` | dim | 是 |  | Chamfer distance |
| `size2` | dim |  |  | Second distance (unequal chamfer) |
| `angle` | dim |  |  | Angle in degrees (distance-and-angle chamfer) |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `fillet`

Round edges of the solid

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `edges` | any | 是 |  | edge selector, re-resolved after every edit: 'all', 'Edge3', or an object with any of type (line\|circle\|...), direction (x\|y\|z\|-z\|[x,y,z], lines parallel to it), axis (circles around it), radius\|diameter, length, x\|y\|z (all points on that coordinate), box [[x0,y0,z0],[x1,y1,z1]], face (a face selector: edges of those faces), near [x,y,z] + count (nearest ones); a list unites selectors |
| `radius` | dim | 是 |  | Fillet radius |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `groove`

Revolve a sketch's profile around an axis and cut it out of the solid

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `axis` | string |  | V | 'V' / 'H' (the sketch's vertical / horizontal axis), 'X'\|'Y'\|'Z' (origin axes) or 'sketch_edge:<i>' (a line of the sketch) |
| `angle` | dim |  | 360 | Degrees |
| `symmetric` | bool |  | False | Revolve half to each side |
| `reversed` | bool |  | False | Revolve the other way |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `helix`

Sweep a sketch's profile along a helix (springs, threads)

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Profile sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `axis` | string |  | V | 'V'\|'H' (sketch axes) or 'X'\|'Y'\|'Z' |
| `pitch` | dim | 是 |  | Rise per turn |
| `height` | dim | 是 |  | Total height |
| `left_handed` | bool |  | False | Left-hand helix |
| `reversed` | bool |  | False | Grow the other way |
| `subtractive` | bool |  | False | Cut instead of add |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `hole`

Drill a hole at every circle centre of a sketch, into the solid against the sketch normal (sketch on the face you drill from). Optional counterbore/countersink and ISO metric thread

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Sketch with circles feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `diameter` | dim |  |  | Hole diameter (not with thread) |
| `depth` | dim |  |  | Depth (or through_all) |
| `through_all` | bool |  | False | Through the whole solid |
| `thread` | string |  |  | ISO metric size such as 'M8' (diameter then follows the standard tap drill) |
| `model_thread` | bool |  | False | Model the thread geometry (slow) |
| `counterbore` | object |  |  | {diameter, depth} |
| `countersink` | object |  |  | {diameter, angle (default 90)} |
| `drill_point` | enum ['flat', 'angled'] |  | flat | Blind hole bottom |
| `reversed` | bool |  | False | Drill along the normal instead |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `linear_pattern`

Repeat features along an axis

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `features` | list | 是 |  | Features to repeat, each a feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `direction` | string |  | X | 'X'\|'Y'\|'Z' |
| `length` | dim |  |  | Distance from the first to the last copy (or spacing) |
| `spacing` | dim |  |  | Distance between neighbouring copies (or length) |
| `occurrences` | dim | 是 |  | Number of copies including the original (>= 2) |
| `reversed` | bool |  | False | Repeat in the negative direction |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `loft`

Loft through two or more sketches (in order)

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sections` | list | 是 |  | Sketches, each a feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `ruled` | bool |  | False | Straight faces between sections |
| `closed` | bool |  | False | Loop back to the first section |
| `subtractive` | bool |  | False | Cut instead of add |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `mirror`

Mirror features across an origin plane

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `features` | list | 是 |  | Features to mirror, each a feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `plane` | enum ['XY', 'XZ', 'YZ'] | 是 |  | Mirror plane |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `pad`

Extrude a sketch's closed profiles into solid, along the sketch normal

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `length` | dim | 是 |  | Extrusion length |
| `symmetric` | bool |  | False | Extrude half to each side of the sketch |
| `reversed` | bool |  | False | Extrude against the normal |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `pocket`

Cut a sketch's closed profiles out of the solid, against the sketch normal

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `depth` | dim |  |  | Cut depth (or through_all) |
| `through_all` | bool |  | False | Cut through the whole solid |
| `symmetric` | bool |  | False | Cut half to each side |
| `reversed` | bool |  | False | Cut along the normal instead |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `polar_pattern`

Repeat features around an axis

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `features` | list | 是 |  | Features to repeat, each a feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `axis` | string |  | Z | 'X'\|'Y'\|'Z' (through the origin) |
| `angle` | dim |  | 360 | Total angle in degrees (360 = evenly around) |
| `occurrences` | dim | 是 |  | Number of copies including the original (>= 2) |
| `reversed` | bool |  | False | Repeat clockwise |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `primitive`

Add (or with subtractive=true cut) a box, cylinder, cone, sphere, torus, prism or wedge

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | enum ['box', 'cylinder', 'cone', 'sphere', 'torus', 'prism', 'wedge'] | 是 |  | Primitive |
| `dims` | object |  |  | box {length, width, height}; cylinder {radius, height, angle}; cone {radius1, radius2, height}; sphere {radius}; torus {radius1, radius2}; prism {sides, circumradius, height}; wedge {xmin, xmax, ymin, ymax, zmin, zmax, x2min, x2max, z2min, z2max} |
| `position` | list |  |  | [x, y, z] of the primitive's origin (box: a corner; cylinder: base centre) |
| `direction` | list |  |  | [x, y, z] the primitive's local Z points along (default +Z) |
| `subtractive` | bool |  | False | Cut instead of add |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `revolve`

Revolve a sketch's profile into solid around an axis

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `axis` | string |  | V | 'V' / 'H' (the sketch's vertical / horizontal axis), 'X'\|'Y'\|'Z' (origin axes) or 'sketch_edge:<i>' (a line of the sketch) |
| `angle` | dim |  | 360 | Degrees |
| `symmetric` | bool |  | False | Revolve half to each side |
| `reversed` | bool |  | False | Revolve the other way |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `sweep`

Sweep a closed profile sketch along a path sketch

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `sketch` | string | 是 |  | Profile sketch feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `path` | string | 是 |  | Path sketch (open wire) feature reference: 'tag:<name>', '$<op index in this batch>' or an object name such as 'Pad001' |
| `frenet` | bool |  | False | Frenet orientation (for helical paths) |
| `subtractive` | bool |  | False | Cut instead of add |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

### `thickness`

Shell the solid: remove the selected faces and keep walls of a thickness

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `faces` | any | 是 |  | face selector, re-resolved after every edit: 'top'\|'bottom'\|'front'\|'back'\|'left'\|'right' (outermost planar face), 'Face2', or an object with any of type (plane\|cylinder\|...), normal (+z\|-x\|[x,y,z]), extreme (max\|min along the normal), axis, radius\|diameter, inner (holes), x\|y\|z, box, near + count (the faces to open) |
| `thickness` | dim | 是 |  | Wall thickness |
| `outward` | bool |  | False | Grow walls outward instead of inward |
| `join` | enum ['arc', 'intersection'] |  | arc | Corner style |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

## part_sketch

### `add_sketch`

Add a sketch: placed on an origin plane (plane + offset), on a planar face of the solid (on_face; sketch x/y then follow the global axes projected onto the face, origin = global origin projected), or by origin + normal (+ x_dir)

| 参数 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `shapes` | list | 是 |  | closed profiles (or construction geometry), each {type, ...}: rectangle {corner [x,y] (lower left) \| center, width, height, name}; circle {center, diameter \| radius, name}; polygon {points: [[x,y] \| [x,y,bulge], ...]}; polyline {points, closed}; regular_polygon {center, sides, circumradius \| across_flats, rotation}; slot {start, end, width}; line {start, end}; arc {center, radius, start_angle, end_angle}; point {at}. Any shape: construction=true. Rectangle sizes and circle diameters accept expressions ('=Params.w'). End points that touch are joined; every shape is fully constrained. Coordinates are in the sketch plane |
| `plane` | enum ['XY', 'XZ', 'YZ'] |  |  | Origin plane (default XY). XY: x=X, y=Y, normal +Z. XZ: x=X, y=Z, normal -Y. YZ: x=Y, y=Z, normal +X |
| `offset` | dim |  |  | Distance along the plane's normal |
| `on_face` | any |  |  | face selector, re-resolved after every edit: 'top'\|'bottom'\|'front'\|'back'\|'left'\|'right' (outermost planar face), 'Face2', or an object with any of type (plane\|cylinder\|...), normal (+z\|-x\|[x,y,z]), extreme (max\|min along the normal), axis, radius\|diameter, inner (holes), x\|y\|z, box, near + count; must match one planar face |
| `origin` | list |  |  | [x, y, z] of the sketch origin (with normal) |
| `normal` | list |  |  | [x, y, z] sketch normal (with origin) |
| `x_dir` | list |  |  | [x, y, z] sketch x axis (default: global X projected) |
| `body` | string |  |  | Body to add to (default: the part's only Body, created on first use) |
| `tag` | string |  |  | Name for later reference as 'tag:<name>' |

## 约束类型

- 可检查: angle, coincident, concentric, diameter, distance, equal, fixed, horizontal, length, parallel, perpendicular, radius, symmetric, tangent, vertical
- 可强制（顺序直接修改，非联立求解）: coincident, concentric, diameter, distance, equal, fixed, horizontal, length, parallel, perpendicular, radius, vertical
