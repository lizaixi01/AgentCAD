# 架构、数据模型与 API

## 分层

```
外部 Agent (Claude Code / Codex / 脚本)
   │  CLI (agentcad)   MCP stdio (agentcad.mcp_server)   HTTP (/v1/<tool>)   Python
   ▼
service.Runtime          ← 唯一业务层：信封、指标、锁、journal、调用下层
   ├─ engine             ← 批量事务执行（预校验 → 内存执行 → 失败整体丢弃）；spec 修订的就地协调
   │    └─ ops/*         ← 40 个类型化操作（同一定义生成参数校验 + JSON Schema）
   ├─ validate/*         ← 独立验证器：只读磁盘文件
   ├─ constraints        ← 约束检查 / 顺序直接强制
   ├─ spec / docspec     ← 规格 → 操作计划 + 需求；文档 → 带溯源的规格
   ├─ store              ← 安全读写、检查点、journal、提交副本、恢复
   └─ policy             ← 沙箱路径、只读、操作白名单、预算
ezdxf (DXF 内核)
```

适配层（`cli.py`、`mcp_server.py`、`http_api.py`）不导入 ezdxf、ops 或 engine，`tests/test_g_interfaces.py::test_interfaces_share_one_implementation` 对此做了检查。

## 数据模型

| 概念 | 表示 |
|---|---|
| 图纸 | DXF 文件（默认 R2010）。`$INSUNITS` 必须是明确的长度单位（mm/cm/m/in/ft），`$MEASUREMENT` 与之一致，`$MIRRTEXT=0` |
| 实体 ID | DXF handle（十六进制字符串）。保存/重载后不变，删除后不复用 |
| 语义标签 | XDATA `AGENTCAD` → `(1000, "tag=<name>")`，可用 `"tag:<name>"` 引用；复制产生的新实体不继承标签 |
| 批内引用 | `"$<i>"` = 本批第 i 步创建（或修改）的实体 |
| 选择器 | handle、`tag:x`、`$i`、它们组成的列表、过滤对象 `{type, layer, tag, tag_prefix}`、`{"all": true}`。空对象 `{}` 会被拒绝，避免误选全部 |
| 零件规格 | rootdict → `AGENTCAD` 字典 → XRECORD `part_spec`（JSON 分块存在 group 1 中），另有 `plan_tags`。随 DXF 文件一起移动 |
| 标注 | 真实 DIMENSION 实体 + 渲染块 `*D<n>`；Runtime 写入 group 42（实测值）；验证器从定义点重新测量，不信任文字或 group 42 |
| 角度 | 度、逆时针、WCS。外来文件中 extrusion (0,0,-1) 的圆/弧/多段线按 WCS 读取（AutoCAD 会原样保留这种实体）；被编辑时先归一化为 (0,0,1)。多段线 bulge = tan(θ/4)，正值为逆时针。角度标注的 group 42 按 AutoCAD 约定存弧度，API 中仍用度 |
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
5. 提交：为旧文件建检查点 → 在 head 中写入 `pending` → 临时文件 fsync 后 `os.replace` → 写提交副本 → 清除 `pending` → 写 journal。
6. 从磁盘重新读取，运行验证器，把报告随结果一起返回。

`recover`：文件不可读、存在 `pending`，或文件丢失时，优先恢复 `committed.dxf`（必须与 head 中的哈希一致），否则回退到最近一个可读的检查点。损坏文件会保留到 `failed/`。

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

- **通用检查**：`$INSUNITS` 是否明确；零长度、零半径、非有限坐标、少于 2 个顶点；引用了未定义的块或图层；重复实体（几何规范化后比较，线段方向无关，标注考虑方向）；标注文字与重新测量值矛盾；group 42 与定义点不一致（`DIMENSION_STALE`）；标注锚点没有落在任何几何上（`DIMENSION_NOT_ATTACHED`）；指定图层上存在开口轮廓；超出给定边界；ezdxf audit 错误。
- **特征识别**：闭合多段线，以及 LINE/ARC 首尾相接形成的环 → 轮廓；轮廓内的圆 → 孔；标注 → 类型和实测值。
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
- 代码中没有 `os.system`、`eval`、`exec`。`subprocess` 只出现在可选的 `backends/autocad.py` 中：可执行文件来自配置或自动发现，不经 shell（`shell=False`），有超时；作业脚本只包含固定文件名，不含调用方字符串；不修改宿主 AutoCAD 的持久设置。这些约束都有测试扫描。Agent 的输入只能落到封闭的操作注册表上。
- HTTP 默认只绑定 127.0.0.1，请求体限制 8 MB。
