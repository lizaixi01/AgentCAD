# 验收报告（测试 A–H）

运行环境：Windows 11，Python 3.12.10，ezdxf 1.4.5，mcp 1.30.0，Pillow（SVG 导出），LibreOffice portable（仅用于独立导入检查），**AutoCAD 2027**（2026-10-27 起，仅通过无头的 accoreconsole 使用）。
自动化测试：**116 passed**（完整逐项输出见 [test-results.txt](test-results.txt)）。其中 27 项是 AutoCAD 差分测试（不需要 AutoCAD），5 项是 AutoCAD 实机测试（未安装 AutoCAD 时自动跳过）。演示产物：`python examples/run_demo.py` → `examples/output/`。

## AutoCAD 2027 实机验证（2026-10-27 新增）

详细记录见 [research/autocad-observations.md](research/autocad-observations.md)。

| 检查 | 结果 |
|---|---|
| 5 张交付 DXF（A、B、C-PDF、C-中文、R12）和 Codex 产出在 AutoCAD 中 DXFIN + AUDIT | 6/6 **0 个错误**；单位、实体数、标注值、XDATA 标签、存储的规格全部保留（`examples/output/AUTOCAD_checks.json`） |
| R12 导出 | 修复前 233 个错误（ezdxf r12export 写出了 BYBLOCK/BYLAYER 线型表项和未用文字样式），修复后 0 个 |
| 由 AutoCAD 写出的 DXF / DWG 再回到 AgentCAD | 独立验证 17/17 通过；规格修订仍只修改 10 个实体；修订后的文件再交给 AutoCAD，0 个错误 |
| DWG 交付 | `A_mounting_plate_100x60.dwg`、`B_mounting_plate.dwg`（DWG 2018），由 AutoCAD 读回并通过验证 |
| AutoCAD 作为 oracle 的 27 个编辑命令差分用例 | 首轮发现 AgentCAD 的 4 个真实缺陷：三点弧顺时针点序、角度标注 42 的单位、文字镜像、块参照镜像。全部修复，现在 27/27 一致 |
| 原研究中被阻塞的 5 项 | 全部实测（其中 NaN、未注册 APPID、XDATA 超过 16 KB 会导致 AutoCAD 整文件拒绝），并转化为验证器规则 |
| 我们的验证器与 AutoCAD 是否一致 | AutoCAD 拒绝的文件，我们的验证器同样判为失败（`test_validator_and_autocad_agree_on_rejected_file`） |

下面的每个结论都来自实际运行：要么是测试断言，要么是演示产物文件。

## 测试 A：从规格生成工程图

测试文件 `tests/test_a_spec_to_drawing.py`（4 项），产物 `examples/output/A_mounting_plate_100x60.dxf`，验证报告 `A_validation.json`。

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 有效 DXF | 通过 | ezdxf 能独立重读；LibreOffice 能独立导入并渲染（`examples/lo_render/A_mounting_plate_100x60.png`）；**AutoCAD 2027 AUDIT 0 个错误**，AutoCAD 读到的标注值与设计一致 |
| 外轮廓 100 × 60 | 通过 | 测试直接从 OUTLINE 层多段线的顶点计算尺寸，不读规格 |
| 4 孔 Ø8 | 通过 | 从 CIRCLE 半径计算 |
| 孔心距相邻边 10 mm | 通过 | 孔心坐标减去轮廓左下角，得到 (10,10)、(10,50)、(90,10)、(90,50)，并检查到最近两条边的距离 |
| 必要标注 | 通过 | 从定义点重新测量得到线性 100、60、10、10、80、40 和直径 8 |
| 独立验证器检查实际几何 | 通过 | 17 项需求全部通过，报告给出 expected/actual/deviation/tolerance |
| 导出后重读一致 | 通过 | 导出 R2000、R2018 后，逐实体序列化结果与原图完全相同；R12 导出时 LWPOLYLINE 转成 POLYLINE，4 个 CIRCLE 保留，AutoCAD AUDIT 0 个错误（需先清理 ezdxf 的表项，见上文） |
| 单位不明时拒绝 | 通过 | 规格缺少 `units` 时返回 `spec/UNITS_UNDEFINED`，不写任何文件 |

## 测试 B：修改图纸并保留约束

测试文件 `tests/test_b_revision.py`（4 项），产物 `B_mounting_plate.dxf`、`B_diff.json`、`B_validation.json`。

- `revise_drawing(width=120)` 以**就地协调**方式修改：所有 handle 保持不变（`set(after) == set(before)`）；用户手工加的、没有标签的注释原样保留。
- 发生变化的实体恰好 10 个：outline、右侧 2 个孔及其 4 条中心线、宽度标注、两个孔距标注。左侧孔、高度标注、孔径标注、孔位标注、材料注释都没有变化（测试逐个断言）。
- 孔心变为 (10,10)、(10,50)、(110,10)、(110,50)。
- `get_diff` 输出 `{"added":0,"deleted":0,"modified":10}`，其中宽度标注的 measurement 字段从 100.0 变为 120.0。
- 独立验证：17/17 通过（需求由新规格重新推导）。
- 同一修订重复提交时变更为空（幂等）；回滚到 `cp-0001` 后宽度恢复为 100；导致孔破边的修订（宽 15）被 `spec` 错误拒绝，文件字节不变。
- 不是由规格生成的图纸，走低层路线：用 `stretch` 加独立验证，同样通过。外部 Agent（Codex）在测试 G 中也是这样做的。

## 测试 C：读取技术文档并生成工程图

测试文件 `tests/test_c_document.py`（7 项），产物 `C_bracket_spec.pdf` → `C_bracket_from_pdf.dxf` + `C_pdf_trace.json`；`C_plate_spec_zh.md` → `C_plate_from_zh_md.dxf` + `C_zh_trace.json`。

- PDF（2 页，英文）：提取出单位 mm（第 1 页）、150×90、厚 5、Ø9、四角、距边 15、材料 S355。每项都带 `{page, line, section, text, match}`，例如宽度来源为 `page 2, line 2, section "2 Geometry", "Overall size 150 x 90 mm."`。
- 中文 Markdown：提取出 120×80、R5、板厚 4、Ø10、距边 12、Q235，章节溯源到 `4. 安装孔`。"四角各有一个安装孔"不会被误读成孔数 1（专门处理了"各/each"）。
- 逐项核对：`verification[]` 里每项需求都给出期望值、图纸实测值、偏差、容差和文档来源，全部通过。
- 矛盾文档：同一文档中先写 "100 x 60 mm" 又写 "Width: 110 mm"，返回 `SPEC_CONFLICT`，两个来源行号都会列出（第 5、7 行），不生成任何文件。
- 缺失信息：没有单位、没有孔径时返回 `incomplete`，列出 `UNITS_UNDEFINED` 和 `SPEC_MISSING_PARAM(hole_diameter)`，不会自行补值。调用方可以通过 `overrides` 显式补充，这类补充在溯源中标记为 `caller_override`。
- Agent 引文路线：Agent 提交 `{field, value, quote, page}`，Runtime 核对引文是否真的出现在该页。一个虚构的 "Thickness 12 mm" 被标为 `CITATION_NOT_FOUND`，规格状态因此变成非 ok。
- 文档修订（B 版改为 180×90）会**修订**已有图纸，而不是新建：added 0、deleted 0，只有 modified。

## 测试 D：错误与约束冲突检测

测试文件 `tests/test_d_errors.py`（9 项）。

| 构造的错误 | 检测结果 |
|---|---|
| 矛盾尺寸（Ø30 孔距边 10） | `spec/SPEC_CONFLICT`，`path` 指出 `hole.bl` 等 |
| 超出图纸范围 | `OUT_OF_BOUNDS`，附实体、tag、实际包围盒 `[[295,45],[305,55]]` |
| 重复实体（包括方向相反的线段） | `DUPLICATE_ENTITY`，列出两个 handle；`strict` 模式下拒绝保存 |
| 孔位不符 | `hole` 需求 fail，deviation 2.0，并给出期望和实际坐标 |
| 无效 DXF（垃圾内容、空文件、截断文件） | `file/DXF_PARSE_ERROR`；验证器报告 `readable:false` |
| 缺失参数 | `spec/SPEC_MISSING_PARAM`（`height`、`holes[0].diameter`…）；操作层返回 `input/AMBIGUOUS_PARAMS`，带 `op_index` |
| 错误类别可区分 | 一次测试同时产生 input、geometry、file、policy、spec 五类错误 |
| 批次中途失败 | `op_index=2`、`partial_changes=false`，文件字节不变，journal 记录失败 |
| 需求中的未知字段 | 返回 `warnings`，不静默忽略（这个问题是外部 Agent 实测时暴露的） |

约束冲突：`tests/test_constraints.py` 中，两条互相矛盾的长度约束返回 `CONSTRAINT_CONFLICT`，文件不变。

## 测试 E：独立验证器

测试文件 `tests/test_e_tamper.py`（6 项）。篡改用另一条路径完成：直接用 ezdxf 读写文件，绕过 Runtime。

| 篡改 | 验证器输出 |
|---|---|
| 孔 hole.tr 右移 1.5 | fail，expected (90,50)，actual (91.5,50)，deviation 1.5，tolerance 0.001；其余孔通过 |
| 轮廓放大 2% | outline fail，actual width 102，deviation 2；宽度标注报 `DIMENSION_NOT_ATTACHED` |
| 删除宽度标注 | `dim.width` fail（报告中不存在测量值为 100 的线性标注） |
| 把标注文字改成 "65" | `DIMENSION_TEXT_MISMATCH`，expected 60 |
| 孔径改为 9 | hole fail；`hole_count.d8` 期望 4、实际 3 |
| 文件在 Runtime 外被修改 | `status.modified_outside_runtime = true`（哈希比对） |

验证器每次都重新读取磁盘文件；需求只从图纸内存储的规格推导，不使用生成过程的计划或内存状态。

## 测试 F：可复现性与修改恢复

测试文件 `tests/test_f_repro_recovery.py`（5 项）。

- 同一计划执行两次：几何完全一致，handle 序列也一致（确定性 ID）。
- 带 `if_tag_exists:"skip"` 的重放不会新增实体；不带时返回 `TAG_EXISTS` 而不是悄悄复制；对已存在的输出文件执行 `draw_from_spec` 会返回 `FILE_EXISTS`。
- journal 可追溯：每条记录包含 seq、时间戳、工具、完整操作输入、变更、检查点、sha256、ezdxf/Python 版本；`get_diff` 对比检查点时能看到 `center: (40,25) → (45,25)`。
- 中途失败后文件不变；删除后 `rollback` 恢复，几何与删除前一致。
- 崩溃模拟（写入一半的截断文件加上 pending 标记）：`recover` 恢复最近一次提交的**精确**状态（`committed`），最后一批改动不丢；损坏文件留存到 `failed/`；再次 `recover` 时报告无需恢复。

## 测试 G：外部 Agent 接入

### 协议级（自动化测试 `tests/test_g_interfaces.py`）
- **MCP**：用官方 `mcp` Python SDK 的 stdio 客户端启动真实服务器进程。列出工具，检查 10 个必需工具都存在且 schema 正确；依次完成创建、批量绘制、读取、触发 `TAG_EXISTS`、按错误改正后重试、验证、diff、回滚、规格绘图、指标。
- **CLI**：用子进程跑通 draw / inspect / entities / revise / diff / validate / apply 错误路径（退出码 2）/ 验证失败（退出码 1）/ 路径越界（退出码 4）/ 只读 / rollback / export svg / ops。
- **HTTP**：POST `/v1/<tool>`，以及 GET `/v1/tools`。
- 适配层不包含 CAD 逻辑（静态检查）。

### 真实外部 Agent：Codex CLI 0.163（`examples/agent_codex/`）
- 配置：Codex 运行在 `-s read-only` 沙箱中，无法执行 shell 写操作，只能通过 AgentCAD MCP 工具完成任务。任务说明见 `TASK.md`。
- **第 1 次运行（被阻塞，已留档 `run1_blocked_*`）**：用户配置为 `approval_policy="never"`，Codex 拒绝了所有 MCP 调用（"MCP tool call requires approval, but approval policy is never"）。这是客户端配置问题，不是 Runtime 的问题。解决办法是 `mcp_servers.agentcad.default_tools_approval_mode="approve"`，先用一个探针调用确认有效（`probe_events.jsonl`）。
- **第 2 次运行（`run2_events.jsonl`）**：11 次 MCP 调用，全部 `ok`，0 次 shell 命令。Codex 先用低层操作（不用 `draw_from_spec`）画出带 3 个标注的 100×60 板，验证时有一项需求失败（它把 Ø8 标注写成了默认的 linear），根据结构化结果改成 `kind:"diameter"` 后通过。随后用 `stretch` 加宽到 120，并以 `strict` 验证 9/9 通过；再调用 `get_diff`（修改 4 个）、`read_drawing`、`get_metrics`。
- 我们用 CLI 对 Codex 产出的 `ws/bracket.dxf` 做了**独立复验**：9/9 通过（`independent_revalidation.json`）。
- 成本：Codex 侧输入 494,881 token（其中缓存 455,552），输出 2,178 token，1 次需求失败后重试。Runtime 侧模型调用为 0，服务端计时约 650 ms（据 Codex 读取的 `get_metrics`）。
- Claude Code CLI 不在本机 PATH 中，所以没有用它作为第二个客户端。README 给出了 `claude mcp add` 配置，协议层面已经用官方 SDK 客户端验证过。

## 测试 H：常用功能覆盖

`tests/test_h_operations.py`（24 项）加上 AutoCAD 差分测试（27 项，见上文）以及其它测试文件：**全部 41 个操作都至少被一个测试调用**（[op_test_matrix.md](op_test_matrix.md)，由脚本根据测试源码生成）。每个操作的测试都包含：成功执行、**从磁盘重读后**的几何断言，以及至少一个失败用例的错误码断言。功能状态分类见 [coverage.md](coverage.md)。

## 性能与 Agent 使用成本

| 指标 | 数值（本机） |
|---|---|
| 规格生成 A 图（1 次调用，含验证） | 演示中 14 次调用共 2.4 s，平均约 0.17 s/次 |
| 独立验证（A 图，17 项需求） | 58 ms |
| 全量测试 | 74 项，约 50–63 s（CLI 子进程测试占 15 s） |
| A 任务所需工具调用 | 规格路线 1 次（`draw_from_spec` 自带验证）；Codex 低层路线完成 A+B 共 11 次 |
| 失败/重试 | Codex：1 次需求失败、1 次重试；Runtime 无失败 |
| 模型调用 | Runtime 0 次；外部 Agent 的 token 见上 |

每个工具结果都带 `metrics.duration_ms / input_bytes / output_bytes`，`get_metrics` 会汇总会话内的调用次数、失败数和字节量。

## 兼容性观察（独立第三方导入）

- **发现并修复的问题**：ezdxf 不维护 `$EXTMIN/$EXTMAX`（保留 1e20 哨兵值），LibreOffice 按头部范围适配页面，整张图因此缩成一个点。做过 A/B 对照：同一图形无范围时渲染为空白，写入真实范围后正常。现在每次保存和导出都写入真实范围。
- 修复后 LibreOffice 能正确导入 A/B/C 图纸和 R12 导出：图框、标题栏、板、孔、中心线、标注线都能显示（`examples/lo_render/*.png`）。
- **观察到的第三方差异**：LibreOffice 导出的 PDF 文字中没有标注数字，也没有材料注释（两者在 DXF 中都是 MTEXT）；标题栏的 ATTRIB/TEXT 则正常出现。由此推断其 DXF 导入不支持 MTEXT，但没有进一步核实。ezdxf 重读、本项目验证器以及 AutoCAD 2027 都能正确读出这些实体（AutoCAD 读到的标注值与设计一致）。
