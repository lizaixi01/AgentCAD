# 操作教程

本教程从零开始带你用一遍 AgentCAD Runtime：生成图纸、校验、修改、出错与回滚、从文档出图、约束、导出 DWG，最后接入 Claude Code / Codex。文中每条命令和输出都在本机（Windows 11，AutoCAD 2027）实际运行过；输出只截取了关键字段。

## 0. 准备

```bash
uv venv .venv --python 3.12
uv pip install --python .venv -e ".[dev]"
```

装好后会有命令 `agentcad`（在 `.venv/Scripts/` 下）。下文把它简写为 `agentcad`；没有激活虚拟环境时，请写完整路径 `.venv/Scripts/agentcad.exe`。

先记住三条规则：

1. **`--root` 是工作区沙箱**。图纸路径（如 `plate.dxf`）和技术文档路径都相对于 root 解析，不能用 `..` 或 root 之外的绝对路径跳出 root。
2. **输入文件（`--spec`、`--ops-file`、`--requirements-file`、约束的 `--file`）按当前目录解析**，不是按 root。在别的目录运行时，请写完整路径。
3. **每条命令都向 stdout 输出一个 JSON**，先看 `ok`。退出码：0 成功，1 验证未通过，2 输入/规格/几何错误，3 文件错误，4 策略拒绝，5 内部错误，6 可选依赖（如 AutoCAD）缺失。

下文统一用 `--root work`，即仓库下的 `work/` 目录（不存在会自动创建）。

---

## 1. 按规格生成一张图纸

规格文件 [examples/specs/plate_100x60.json](../examples/specs/plate_100x60.json)：

```json
{"kind": "plate", "units": "mm", "name": "Mounting plate",
 "width": 100, "height": 60,
 "holes": [{"pattern": "corners", "diameter": 8, "edge_offset": 10}],
 "material": "Q235", "thickness": 3}
```

```bash
agentcad --root work draw --spec examples/specs/plate_100x60.json --output plate.dxf
```

结果（节选）：

```json
{"ok": true,
 "changes": {"added": ["93", "95", "96", "...共 21 个"]},
 "validation": {"passed": true, "issues": [],
   "requirements": [
     {"type": "outline", "expected": {"width": 100, "height": 60}, "actual": {"width": 100.0, "height": 60.0}},
     {"type": "hole", "expected": {"center": [10, 10], "diameter": 8}, "actual": {"center": [10.0, 10.0], "diameter": 8.0}},
     "...",
     {"type": "hole_count", "expected": 4, "actual": 4}]}}
```

`added` 里是新实体的 handle（实体 ID）。生成后会立刻从磁盘重读文件做独立校验，`validation` 就是校验结果。图里包含轮廓、4 个孔、中心线、7 个尺寸标注和标题栏文字。

## 2. 查看图纸

```bash
agentcad --root work inspect plate.dxf
```

返回单位、范围、图层、各类实体数量、标签和存储的规格，例如：`"units": "mm", "entity_types": {"LWPOLYLINE": 1, "CIRCLE": 4, "LINE": 8, "DIMENSION": 7, "MTEXT": 1}`。

按条件列出实体：

```bash
agentcad --root work entities plate.dxf --type CIRCLE --brief
```

```json
{"total": 4, "entities": [
  {"id": "95", "type": "CIRCLE", "layer": "HOLES", "tag": "hole.bl"},
  {"id": "98", "type": "CIRCLE", "layer": "HOLES", "tag": "hole.br"},
  {"id": "9B", "type": "CIRCLE", "layer": "HOLES", "tag": "hole.tr"},
  {"id": "9E", "type": "CIRCLE", "layer": "HOLES", "tag": "hole.tl"}]}
```

`tag` 是语义标签，后续可以用 `"tag:hole.br"` 引用这个实体，比记 handle 方便。也可以用 `--layer`、`--tag`、`--tag-prefix`、`--ids` 过滤；去掉 `--brief` 会返回完整几何。

## 3. 独立校验

```bash
agentcad --root work validate plate.dxf
```

验证器只读磁盘上的文件，从几何本身识别轮廓、孔和标注，再与图纸里存储的规格比对。不通过时退出码为 1，每一项都给出 expected、actual 和偏差。

也可以指定自己的要求，见第 5 节。

## 4. 修改规格（修订）

把宽度改成 120，变更文件 [examples/specs/change_width_120.json](../examples/specs/change_width_120.json) 只写要改的字段：`{"width": 120}`。

```bash
agentcad --root work revise plate.dxf --spec examples/specs/change_width_120.json
```

```json
{"ok": true,
 "changes": {"added": [], "modified": ["93", "98", "99", "9A", "9B", "9C", "9D", "A1", "EA", "F9"], "deleted": []},
 "validation": {"passed": true, "requirements": [
   {"type": "outline", "expected": {"width": 120}, "actual": {"width": 120.0}},
   {"type": "hole", "expected": {"center": [110, 10]}, "actual": {"center": [110.0, 10.0]}}, "..."]}}
```

修订是**就地协调**的：轮廓、右侧两个孔及其中心线、宽度标注被修改，handle 不变；不受影响的实体保持原样。

看看改了什么：

```bash
agentcad --root work diff plate.dxf
```

```json
{"against": "cp-0001", "summary": {"added": 0, "deleted": 0, "modified": 10, "unchanged": 11},
 "modified": [
   {"id": "93", "tag": "outline", "changes": {"points": {"old": [[0,0],[100,0],[100,60],[0,60]], "new": [[0,0],[120,0],[120,60],[0,60]]}}},
   {"id": "98", "tag": "hole.br", "changes": {"center": {"old": [90,10], "new": [110,10]}}}, "..."]}
```

默认和上一个检查点比较；`--against cp-0001` 指定检查点，`--against other.dxf` 与另一张图比较。

## 5. 直接下操作：批量绘图

不走规格时，可以把一组操作作为一个批次提交。批次是**原子**的：任何一步失败，整个批次都不生效，文件不变。

新建空图：

```bash
agentcad --root work create bracket.dxf --units mm
```

操作文件 `bracket_ops.json`：

```json
[
  {"op": "add_rectangle", "corner": [0, 0], "width": 80, "height": 40, "corner_radius": 4, "layer": "OUTLINE", "tag": "outline"},
  {"op": "add_circle", "center": [15, 20], "diameter": 8, "layer": "HOLES", "tag": "hole.left"},
  {"op": "copy", "target": "$1", "delta": [50, 0]},
  {"op": "add_linear_dim", "p1": [0, 0], "p2": [80, 0], "offset": -10, "layer": "DIM", "tag": "dim.width"},
  {"op": "add_diameter_dim", "target": "tag:hole.left", "angle": 45, "layer": "DIM"}
]
```

引用实体的三种写法：

| 写法 | 含义 |
|---|---|
| `"98"` | handle |
| `"tag:hole.left"` | 带该标签的实体 |
| `"$1"` | 本批第 1 步（从 0 数）创建的实体 |

长度可以带单位，例如 `"diameter": "0.5in"`，会换算成图纸单位。全部 41 个操作及参数见 [operations.md](operations.md)，也可以运行 `agentcad ops` 获取（带 JSON Schema）。

要求文件 `bracket_req.json`，写你希望成品满足的条件：

```json
[
  {"type": "outline", "width": 80, "height": 40},
  {"type": "hole_count", "count": 2, "diameter": 8},
  {"type": "hole", "center": [65, 20], "diameter": 8},
  {"type": "dimension", "tag": "dim.width", "value": 80}
]
```

先试运行（`--dry-run` 不写文件）：

```bash
agentcad --root work apply bracket.dxf --ops-file bracket_ops.json --dry-run
```

正式执行。`--strict` 表示校验不通过就不保存：

```bash
agentcad --root work apply bracket.dxf --ops-file bracket_ops.json --strict --requirements-file bracket_req.json
```

```json
{"ok": true,
 "results": [{"index": 0, "op": "add_rectangle", "created": ["96"]},
             {"index": 1, "op": "add_circle", "created": ["98"]},
             {"index": 2, "op": "copy", "created": ["99"]},
             {"index": 3, "op": "add_linear_dim", "created": ["9A"]},
             {"index": 4, "op": "add_diameter_dim", "created": ["A9"]}],
 "validation": {"passed": true,
   "issues": [{"code": "DIMENSION_NOT_ATTACHED", "severity": "warning", "...": "..."}],
   "requirements": ["outline ✓", "hole_count 2/2 ✓", "hole (65,20) ✓", "dimension 80 ✓"]}}
```

这里有一条警告 `DIMENSION_NOT_ATTACHED`，原因是矩形四角倒了 R4 圆角，(0,0) 和 (80,0) 处已经没有几何，宽度标注的端点"悬空"了。这是真实的问题：要么把标注点放到直边上，要么接受。验证器不会替你判断，只会如实报告。

单独用要求文件校验任意图纸：

```bash
agentcad --root work validate bracket.dxf --requirements-file bracket_req.json
```

如果要求写成 `"count": 3`，结果是 `passed: false`、`hole_count expected 3, actual 2`，退出码 1。

> 注意：对由规格生成的图纸（如 `plate.dxf`）追加规格之外的几何时，`validate` 默认按图纸内存储的规格核对。比如多画了一个孔，会报 `hole_count` 期望 4、实际 5。这时要么用 `revise` 改规格，要么用 `--requirements-file` / `--no-stored-spec` 指定核对内容。

## 6. 出错时会怎样

故意写错参数名（`fillet` 的参数应为 `line1`/`line2`）：

```bash
agentcad --root work apply plate.dxf --ops "[{\"op\":\"add_circle\",\"center\":[10,10],\"radius\":3},{\"op\":\"fillet\",\"a\":\"tag:x\",\"b\":\"tag:outline\",\"radius\":5}]"
```

```json
{"ok": false, "error": {
  "code": "UNKNOWN_PARAM", "category": "input", "op_index": 1,
  "message": "fillet: unknown parameter(s) ['a', 'b']",
  "hint": "Valid parameters: ['color', 'if_tag_exists', 'layer', 'line1', 'line2', ...]",
  "partial_changes": false}}
```

退出码为 2。第 0 步的圆也**没有**画上：预校验先检查整个批次，任何一步有问题都不执行。几何上不可行的情况（例如圆角半径太大）会在执行阶段报错，同样整体丢弃。错误里的 `op_index`、`hint`、`entities` 足够 Agent 自行修正后重试。

## 7. 检查点、回滚、历史

每次修改前都会自动建检查点：

```bash
agentcad --root work checkpoints plate.dxf
```

```json
{"checkpoints": [
  {"id": "cp-0001", "label": "before revise_drawing"},
  {"id": "cp-0002", "label": "before apply_operations"}]}
```

回滚到最近的检查点，也可以用 `--checkpoint cp-0001` 指定：

```bash
agentcad --root work rollback plate.dxf
```

查看完整操作记录（每次调用的输入、变更、版本、哈希，失败的也会记录）：

```bash
agentcad --root work history plate.dxf
```

如果进程在写文件时崩溃，或文件被破坏，运行 `agentcad --root work recover plate.dxf`。它会从最近一次提交的副本或检查点恢复，损坏的文件保留在 `.agentcad/.../failed/` 下。

## 8. 从技术文档出图

文档 [examples/output/C_plate_spec_zh.md](../examples/output/C_plate_spec_zh.md)（也支持 PDF 和 TXT）。文档和图纸一样必须在 root 内，先复制进去：

```bash
cp examples/output/C_plate_spec_zh.md work/
```

内容节选：

```markdown
## 3. 外形尺寸
外形尺寸 120 × 80 mm，板厚 4 mm。
四角圆角半径 R5。
## 4. 安装孔
四角各有一个安装孔，孔径 Ø10 mm。
孔中心距相邻边缘均为 12 mm。
```

只提取、不画图：

```bash
agentcad --root work extract C_plate_spec_zh.md
```

一步完成"提取 → 出图 → 对照文档校验"：

```bash
agentcad --root work from-doc C_plate_spec_zh.md --output zh.dxf
```

每个提取出的数值都带出处，例如：

```json
"width": {"page": 1, "line": 10, "section": "3. 外形尺寸", "text": "外形尺寸 120 × 80 mm，板厚 4 mm。", "match": "120 × 80 mm"}
```

文档缺少必要信息或自相矛盾时（例如两处写了不同的孔径），命令会拒绝出图，并列出缺失项或冲突项及各自出处，不会猜测。内置提取器是规则式的，只认识板件的常见写法。更复杂的文档应由 Agent 自己阅读理解，再通过 `--facts-file` 提交带引文的事实；Runtime 会核对每条引文是否真的出现在文档里。

## 9. 几何约束

先画两条"差不多垂直"的线：

```bash
agentcad --root work create sketch.dxf --units mm
```

```bash
agentcad --root work apply sketch.dxf --ops "[{\"op\":\"add_line\",\"start\":[0,0],\"end\":[50,0],\"tag\":\"base\"},{\"op\":\"add_line\",\"start\":[0,0],\"end\":[3,40],\"tag\":\"side\"}]"
```

约束文件 `cons.json`：

```json
[{"type": "perpendicular", "a": "tag:base", "b": "tag:side"},
 {"type": "length", "a": "tag:side", "value": 40}]
```

检查：

```bash
agentcad --root work constraints sketch.dxf --file cons.json
```

```json
{"mode": "check", "all_satisfied": false, "constraints": [
  {"type": "perpendicular", "satisfied": false, "expected": 90.0, "actual": 85.71},
  {"type": "length", "satisfied": false, "expected": 40.0, "actual": 40.11}]}
```

强制满足：

```bash
agentcad --root work constraints sketch.dxf --file cons.json --enforce
```

```json
{"mode": "enforce", "solver": "sequential-direct", "all_satisfied": true,
 "changes": {"modified": ["98"]}, "checkpoint_before": "cp-0002"}
```

强制是按顺序逐条修改每条约束的第二个对象，不是联立求解。改完后只要有任何一条不满足，就返回 `CONSTRAINT_CONFLICT` 且不保存。支持的约束类型见 [architecture.md](architecture.md#约束)。

## 10. 导出

```bash
agentcad --root work export plate.dxf plate.svg
```

```bash
agentcad --root work export plate.dxf plate_r12.dxf --dxf-version R12
```

格式由扩展名决定，支持 `.svg`、`.json`、其它 DXF 版本（含 R12）。R12 没有单位信息，结果里会有警告。

### 装有 AutoCAD 时：DWG 与 AutoCAD 审核

**这几条命令请在 PowerShell 或 cmd 里运行**。从 Git Bash 启动 AutoCAD 的无头控制台会挂起。

```powershell
agentcad --root work export plate.dxf plate.dwg
```

```json
{"ok": true, "format": "dwg", "dwg_version": "2018", "backend": "autocad", "seconds": 4.34,
 "readback": {"readable": true, "entities": 21, "source_entities": 21, "issues": []}}
```

导出后会让 AutoCAD 把 DWG 读回来再校验一遍（`readback`）。

让 AutoCAD 自己审核一张 DXF：

```powershell
agentcad --root work acad-audit plate.dxf
```

```json
{"passed": true, "import_rejected": false, "entities_seen_by_autocad": 21, "audit_errors": 0}
```

把 DWG 转成 DXF，之后就能用上面所有命令处理。顺便可以和原图比较，确认往返没有丢东西：

```powershell
agentcad --root work import plate.dwg back.dxf
```

```powershell
agentcad --root work diff plate.dxf --against back.dxf
```

实测结果：`"summary": {"added": 0, "deleted": 0, "modified": 0, "unchanged": 21}`。

AutoCAD 会自动发现。找不到时，把环境变量 `AGENTCAD_ACCORECONSOLE` 设为 `accoreconsole.exe` 的完整路径。没有 AutoCAD 时这三条命令返回 `DEPENDENCY_MISSING`（退出码 6），其它功能不受影响。这些命令不会修改你 AutoCAD 的任何设置。

---

## 11. 让 AI Agent 来用

Runtime 本身不理解自然语言，理解和规划由 Agent 完成。接入后，你直接用中文告诉 Agent 要画什么。

### Claude Code

```bash
claude mcp add agentcad --env AGENTCAD_ROOT=D:/Projects/AgentCAD/work -- D:/Projects/AgentCAD/.venv/Scripts/python.exe -m agentcad.mcp_server
```

### Codex CLI

在 `~/.codex/config.toml` 中加入：

```toml
[mcp_servers.agentcad]
command = "D:/Projects/AgentCAD/.venv/Scripts/python.exe"
args = ["-m", "agentcad.mcp_server"]
env = { AGENTCAD_ROOT = "D:/Projects/AgentCAD/work" }
default_tools_approval_mode = "approve"
```

最后一行不能省：在 `approval_policy="never"` 下，没有它所有工具调用都会被拒绝。

接入后可以这样说：

> 用 agentcad 画一块 150×90 mm 的安装板，四角各一个 Ø10 孔，孔距边 15 mm，四角 R6 圆角。画完校验，然后导出 SVG。

> 把 plate.dxf 的宽度改成 130，告诉我改了哪些实体。

> 按 docs/spec.pdf 出图，有缺失或矛盾的地方先列出来问我。

Agent 会调用 `draw_from_spec`、`apply_operations`、`validate_drawing`、`get_diff`、`rollback` 等 21 个工具，与 CLI 一一对应。可用环境变量限制 Agent 的权限：`AGENTCAD_READ_ONLY=1` 设为只读，`AGENTCAD_ALLOWED_OPS=add_line,add_circle,...` 设置操作白名单。

### Python

```python
from agentcad.service import Runtime
from agentcad.policy import Policy

rt = Runtime(Policy(root="work"))
r = rt.draw_from_spec({"kind": "plate", "units": "mm", "width": 100, "height": 60,
                       "holes": [{"pattern": "corners", "diameter": 8, "edge_offset": 10}]}, "plate.dxf")
assert r["ok"] and r["validation"]["passed"]
r = rt.apply_operations("plate.dxf", [{"op": "add_circle", "center": [50, 30], "diameter": 12}])
print(r["changes"])
```

### HTTP

```bash
agentcad --root work serve --port 8765
```

```bash
curl -X POST localhost:8765/v1/validate_drawing -H "Content-Type: application/json" -d "{\"path\":\"plate.dxf\"}"
```

`GET /v1/tools` 列出所有工具及参数；请求体就是工具的关键字参数。默认只监听 127.0.0.1。

---

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| `cannot read ... file xxx.json: No such file` | 输入文件按**当前目录**解析，不按 `--root`。写完整路径。 |
| `PATH_OUTSIDE_WORKSPACE` | 图纸或文档路径跑到了 root 之外。用 root 内的相对路径。 |
| 文档命令报 `FILE_NOT_FOUND` | 技术文档也按 root 解析，先把它复制到 root 里。 |
| 已存在文件时 `create` / `draw` 失败 | 加 `--overwrite`。被覆盖的旧文件会先建检查点。 |
| `validate` 报 `hole_count` 比预期多 | 图纸是由规格生成的，默认按存储的规格核对。见第 5 节的注意事项。 |
| DWG 命令卡住不动 | 你在 Git Bash 里运行了。改用 PowerShell 或 cmd。 |
| DWG 命令返回 `DEPENDENCY_MISSING` | 没找到 AutoCAD。设置 `AGENTCAD_ACCORECONSOLE`。 |
| 建筑平面等大尺寸图纸出图后箭头看不见、点画线像实线 | 用 `create --annotation-scale 50`（1:50 出图）新建图纸，或对已有图纸执行操作 `{"op": "set_annotation_scale", "scale": 50}`。验证器会用 `ANNOTATION_TOO_SMALL` 提醒。 |
| 直径标注显示成 "ØØ12" | 标注文字里的 `<>` 已经带 Ø / R 前缀，写 `4X <>` 即可，不要写 `Ø<>`。验证器会报 `DIMENSION_DOUBLE_PREFIX`。 |
| 想看图纸实际出图效果 | 装有 AutoCAD 时：`python examples/trials/render_png.py 输出目录 图纸.dxf`（在 PowerShell 中运行），用 AutoCAD 打印成 PNG。 |
| 真实图纸改完后，打印出来的图纸还是旧的 | 很多真实图纸有打印用的图纸空间布局，里面有零件的缩放副本。`read_drawing` 的 `layouts` 会列出它们，`validate` 会用 `LAYOUT_NOT_VALIDATED` 提醒。操作加 `"layout": "布局名"` 即可在布局里编辑，`validate --layout 布局名` 检查它。 |
| 操作目录里没有我要的编辑 | 用 `agentcad --allow-scripts --root work script 图纸.dxf --file 脚本.py`（MCP 工具 `run_script`，需 `AGENTCAD_ALLOW_SCRIPTS=1`）。脚本里图纸叫 `doc`，原地修改即可；它和批量操作一样有检查点、diff、校验，可以 `rollback`。默认关闭，只对你信任的 Agent 开启。 |
| 想看某个操作有哪些参数 | `agentcad ops`，或查看 [operations.md](operations.md)。参数写错时错误信息的 `hint` 里也会列出。 |
| 想看完整演示 | `python examples/run_demo.py`，输出在 `examples/output/`。 |
