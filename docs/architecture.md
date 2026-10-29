# 架构、数据模型与 API

## 分层

```
外部 Agent (Claude Code / Codex / 脚本)
   │  CLI (agentcad)   MCP stdio (agentcad.mcp_server)   HTTP (/v1/<tool>)   Python
   ▼
service.Runtime          ← 唯一业务层：信封、指标、锁、journal、调用下层
   ├─ engine             ← 批量事务执行（预校验 → 内存执行 → 失败整体丢弃）；spec 修订的就地协调
   │    └─ ops/*         ← 41 个类型化操作（同一定义生成参数校验 + JSON Schema）
   ├─ validate/*         ← 独立验证器：只读磁盘文件
   ├─ constraints        ← 约束检查 / 顺序直接强制
   ├─ spec / docspec     ← 规格 → 操作计划 + 需求；文档 → 带溯源的规格
   ├─ store              ← 安全读写、检查点、journal、提交副本、恢复
   └─ policy             ← 沙箱路径、只读、操作白名单、预算
ezdxf (DXF 内核)                 part/* → backends/freecad → FreeCAD 进程 (三维零件 .FCStd，见 part-3d.md)
```

适配层（`cli.py`、`mcp_server.py`、`http_api.py`）不导入 ezdxf、ops 或 engine，`tests/test_g_interfaces.py::test_interfaces_share_one_implementation` 对此做了检查。

## 数据模型

| 概念 | 表示 |
|---|---|
| 图纸 | DXF 文件（默认 R2010）。`$INSUNITS` 必须是明确的长度单位（mm/cm/m/in/ft），`$MEASUREMENT` 与之一致，`$MIRRTEXT=0` |
| 实体 ID | DXF handle（十六进制字符串）。保存/重载后不变，删除后不复用 |
| 语义标签 | XDATA `AGENTCAD` → `(1000, "tag=<name>")`，可用 `"tag:<name>"` 引用；复制产生的新实体不继承标签 |
| 批内引用 | `"$<i>"` = 本批第 i 步创建（或修改）的实体 |
| 选择器 | handle、`tag:x`、`$i`、它们组成的列表、过滤对象 `{type, layer, tag, tag_prefix, layout}`、`{"all": true}`。空对象 `{}` 会被拒绝，避免误选全部。handle 和 `tag:` 在所有布局中查找；过滤对象默认只在当前操作的布局中查找（`layout: "*"` 表示全部布局） |
| 布局 | 模型空间和图纸空间布局（打印用的图纸）。`read_drawing.layouts` 列出每个布局的内容；每个操作都可带 `layout` 参数，新实体加在该布局；从已有实体派生的编辑（copy、offset、trim、fillet、chamfer）留在原实体所在的布局。图纸空间的实体在结果和 diff 中带 `layout` 字段 |
| 零件规格 | rootdict → `AGENTCAD` 字典 → XRECORD `part_spec`（JSON 分块存在 group 1 中），另有 `plan_tags`。随 DXF 文件一起移动 |
| 标注 | 真实 DIMENSION 实体 + 渲染块 `*D<n>`；Runtime 写入 group 42（实测值）；验证器从定义点重新测量，不信任文字或 group 42 |
| 角度 | 度、逆时针、WCS。外来文件中 extrusion (0,0,-1) 的圆/弧/多段线按 WCS 读取（AutoCAD 会原样保留这种实体）；被编辑时先归一化为 (0,0,1)。多段线 bulge = tan(θ/4)，正值为逆时针。角度标注的 group 42 按 AutoCAD 约定存弧度，API 中仍用度 |
| 文字与出图比例 | Standard 文字样式为 `gbenor.shx` + 大字体 `gbcbig.shx`（中文可显示）。`annotation_scale`（1:N）写入 `$DIMSCALE`、`$LTSCALE` 和 AGENTCAD 标注样式 |
| 单位输入 | 数字 = 图纸单位；`"8mm"`、`"0.5in"` 这类字符串会被显式换算；未知单位、或图纸没有单位时报错 |

## 状态目录（每张图纸一份）

```
<root>/.agentcad/drawings/<相对路径用 __ 连接>/
  head.json        已提交 sha256、pending 标记、检查点列表
  journal.jsonl    每次调用（成功或失败）的输入、变更、版本、哈希、检查点
  checkpoints/     cp-NNNN.dxf：每次修改前的字节级副本
  committed.dxf    最近一次提交的精确副本（崩溃恢复用）
  failed/          严格校验失败或损坏文件的现场
  lock             写锁（超过 120 s 视为过期）
```

## 事务（`apply_operations`）

1. 获取写锁，从磁盘读取图纸。
2. **预校验**全部操作：操作名（拼写错误时给出相近名称）、白名单、参数类型/范围/单位、未知参数。任何一步失败，整个批次都不执行。
3. 在内存文档上依次执行。任何一步失败都抛出结构化错误（`op_index`、`partial_changes=false`），内存文档直接丢弃，磁盘文件不变，journal 记录这次失败。
4. 可选 `strict`：先把候选文档写到临时文件，交给独立验证器检查；不通过就不保存，失败现场写入 `failed/`。
5. 提交：为旧文件建检查点 → 在 head 中写入 `pending`（带目标内容的 sha256）→ 临时文件 fsync 后 `os.replace` → 写提交副本 → 清除 `pending` → 写 journal。
   Windows 上目标文件被别的进程打开时 `os.replace` 会失败，所以每次替换最多重试 2 s（`store.replace_file`）。还是失败时（`rollback` 和 `recover` 恢复检查点也走同一个流程，`store._replace_tracked`）：图纸替换之前的任何一步 → `FILE_BUSY`，`retryable=true`，文件不变，这次刚建的检查点也删掉（否则重试 `rollback` 会恢复到它，等于什么都没做）；提交副本 → 不算失败，结果带 `warnings`；图纸替换之后的 head 更新 → `FILE_BUSY`，`partial_changes=true`、`retryable=false`，改动已在文件里，提示调 `recover`，不要重做。journal 写 head 失败不影响结果，下一条记录的 seq 从 journal 文件末尾接着编。
6. 从磁盘重新读取，运行验证器，把报告随结果一起返回。

`run_script`（可选，默认关闭）：对操作目录覆盖不到的编辑，Agent 提交一段 ezdxf 脚本。脚本先做静态检查（只允许导入 ezdxf 和标准数学/数据模块；禁止打开或保存文件、eval/exec、getattr、双下划线访问），然后在独立的 Python 进程中（`-I`、不经 shell、有超时）对图纸副本运行。运行结果由 Runtime 严格重读、检查预算、计算 diff，然后按上面第 4–6 步提交：检查点、journal（记录完整脚本和哈希）、校验、`strict`。失败时文件不变，可以 `rollback`。

`recover`：`pending` 带目标 sha256 且文件可读时，先结算这次中断的提交：文件就是目标内容 → 补写提交副本和 head，journal 记一条 `recover`（`completed_commit`，带 `sha256` 和 `checkpoint_before`，时间线把它当作一次提交）；文件还是上次提交的内容 → 只清掉 `pending`。下一次提交开始前也会先这样结算，所以 Agent 没调 `recover` 就接着改，前一次改动也不会无记录地并进去。其余情况（文件不可读、旧格式的 `pending`、文件丢失）优先恢复 `committed.dxf`（必须与 head 中的哈希一致），否则回退到最近一个可读的检查点。损坏文件会保留到 `failed/`。

`revise_drawing`（规格级修订）：把修改合并进存储的规格 → 重新编译 → 以**协调模式**执行。已存在的标签就地更新（handle 不变）；几何相同的实体不动；旧计划里有而新计划里没有的标签被删除；未打标签的实体、用户自加的实体保持不变。

## 统一结果信封

```json
{
  "ok": true,
  "tool": "apply_operations",
  "drawing": "plate.dxf",
  "changes": {"added": ["9F"], "modified": ["93"], "deleted": []},
  "results": [{"index": 0, "op": "add_circle", "created": ["9F"]}],
  "validation": {"passed": true, "summary": {}, "issues": [], "requirements": []},
  "journal_seq": 7, "checkpoint_before": "cp-0006", "sha256": "…",
  "metrics": {"duration_ms": 41.2, "input_bytes": 180, "output_bytes": 2210}
}
```

失败时：

```json
{"ok": false, "tool": "apply_operations",
 "error": {"code": "FILLET_RADIUS_TOO_LARGE", "category": "geometry", "message": "…",
           "entities": ["A1", "A2"], "op_index": 3, "op": "fillet", "retryable": false,
           "hint": "…", "partial_changes": false, "details": {"tangent_length": 57.7}}}
```

错误类别：`input`（调用参数）、`spec`（规格缺失或矛盾）、`geometry`（几何上不可行）、`file`（读不到或不是 DXF）、`policy`（沙箱、只读、预算、锁）、`validation`、`dependency`（可选组件未安装）、`internal`。CLI 退出码按类别映射（`dependency` 为 6）。

## 验证器

`validate_file(path)` 自己从磁盘读取文件（解析失败本身就是一项结果），不使用生成过程中的任何对象：

- **通用检查**：`$INSUNITS` 是否明确；零长度、零半径、非有限坐标、少于 2 个顶点；引用了未定义的块或图层；重复实体（几何规范化后比较，线段方向无关，标注考虑方向）；标注文字与重新测量值矛盾；group 42 与定义点不一致（`DIMENSION_STALE`）；标注锚点没有落在任何几何上（`DIMENSION_NOT_ATTACHED`）；指定图层上存在开口轮廓；超出给定边界；ezdxf audit 错误。出图可读性（来自 AutoCAD 出图复核，见 [trials-report.md](trials-report.md)）：标注文字重复 Ø/R 前缀（`DIMENSION_DOUBLE_PREFIX`）、中文用了无大字体的 SHX 字体（`TEXT_GLYPHS_MISSING`）、箭头相对标注长度过小（`ANNOTATION_TOO_SMALL`）、打印到纸上的字高小于 2.5 mm（`PRINTED_TEXT_TOO_SMALL`：模型里的文字和标注文字按各视口的比例换算，图纸空间文字直接比较）。标注附着检查接受顶点、圆/弧、与测量方向相交的边，以及块参照内的几何；含外部参照的图纸不做附着检查。
- **特征识别**：闭合多段线，以及 LINE/ARC 首尾相接形成的环 → 轮廓；轮廓内的圆 → 孔；标注 → 类型和实测值。
- **布局**：默认检查模型空间；`layout` 参数可以改为检查某个图纸布局。没有检查到的布局如果含有图形，会以 `LAYOUT_NOT_VALIDATED` 警告报告，并在 `coverage` 中列出（真实图纸的打印布局常常有一份零件的缩放副本，只改模型空间会交付自相矛盾的图纸）。标注值按显示值（乘以 DIMLFAC）比较。新建出图布局用 `create_layout`（纸张 A0–A4 或自定义，图纸空间单位为 mm），再用 `add_viewport` 按固定比例开视口（默认显示模型空间全部内容，返回实际显示的模型窗口和是否完整显示）。
- **需求检查**：`outline`、`hole`（位置相对轮廓左下角）、`hole_count`（可按直径分组）、`dimension`（可用 `tag` 指定实体）、`entity_count`、`text`、`within_bounds`。每项给出 expected、actual、deviation、tolerance 和相关实体；需求来自文档时还附带文档来源。需求里的未知字段不会被静默忽略，而是返回 `warnings`。

## 约束

| 能力 | 类型 |
|---|---|
| 检查（`mode=check`） | coincident, parallel, perpendicular, horizontal, vertical, tangent, concentric, distance, length, angle, symmetric, equal, radius, diameter, fixed |
| 强制（`mode=enforce`） | coincident, horizontal, vertical, concentric, length, distance, radius, diameter, fixed, parallel, perpendicular, equal |

强制采用**顺序直接修改**：依次修改每条约束的第二个操作数，完成后对全部约束重新检查。只要有一条不满足，就返回 `CONSTRAINT_CONFLICT`，且不保存。这**不是**联立约束求解器。tangent、symmetric、angle 只能检查。

点引用写作 `"<选择器>@<点>"`，点可以是 `start`、`end`、`mid`、`center`、`insert`、`location`、`v<N>`。

## 安全

- 所有路径都在 `AGENTCAD_ROOT` 内解析，拒绝穿越和绝对路径；`.agentcad/` 保留；按扩展名白名单。
- 覆盖需要 `overwrite=true`，被覆盖的文件会先建检查点；导出目标不能是源文件。
- 只读模式；操作白名单；批次操作数、实体总数、单批新增实体数都有预算；删除超过 50 个实体需要 `confirm_large`。
- 每张图纸有写锁，返回 `retryable` 错误。
- 代码中没有 `os.system`、`eval`。`exec` 只出现在可选脚本工具的子进程入口 `_script_runner.py` 中；`run_script` 默认关闭（`AGENTCAD_ALLOW_SCRIPTS=1` 或 CLI `--allow-scripts` 才开启），脚本先过静态检查，再在独立进程中运行。这些检查用来防止误操作，不是安全沙箱：只对你愿意让它以你的身份运行 Python 的 Agent 开启。`subprocess` 只出现在 `scripting.py`（启动脚本子进程）和可选的 `backends/autocad.py` 中：可执行文件来自配置或自动发现，不经 shell（`shell=False`），有超时；作业脚本只包含固定文件名，不含调用方字符串；不修改宿主 AutoCAD 的持久设置。这些约束都有测试扫描。Agent 的输入只能落到封闭的操作注册表上。
- HTTP 默认只绑定 127.0.0.1，请求体限制 8 MB。
