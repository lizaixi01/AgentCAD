# 现有 "AI Agent + CAD" 开源项目审计

- 审计日期：2026-10-26
- 环境：Windows 11（中文 GBK 区域设置），Git Bash，Python 3.12.10 / 3.11.16，uv 0.12.16，node 24，**无 AutoCAD、无 FreeCAD、无 ODA File Converter**
- 工作目录：每个仓库都浅克隆（`git clone --depth 1`）到 scratchpad 下的 `audit/<name>`，每个项目单独建 venv。探测脚本放在 `scratchpad/scripts`：`mcp_probe.py` 是一个通用 stdio MCP 客户端，负责 initialize、`tools/list` 和按顺序 `tools/call`；`ezdxf_check.py` 用来验证底层库。
- 证据等级标记（下文统一使用）：
  - **[运行]**：本机实际执行过，结果已观察到
  - **[源码]**：读过源码或配置得出，没有执行
  - **[README]**：只有 README 或网站这样写，没有核实

---

## 1. 结论速览

| 项目 | 审计 commit | 许可 | 接口 | 无头 2D DXF | AutoCAD/商业依赖 | 测试（本机） | 与 AgentCAD 的相关度 |
|---|---|---|---|---|---|---|---|
| **U-C4N/AutoCad-MCP**（AutoCAD-MCP Pro 1.7.0） | `58a05ddf` | MIT | MCP（stdio/HTTP，fastmcp） | **有**（ezdxf 后端）[运行] | COM 后端可选；无头不需要 | **6059 passed, 1 xfailed** [运行] | **很高**：功能最全，可作参考，也可以有选择地复用代码 |
| id0o0bi/autocad-mcp | `aff502ae` | MIT | MCP（5 个工具） | 有，但做法是 `exec` 任意 Python [运行] | `autocad_*` 依赖 accoreconsole.exe | 无测试套件；cases 3/4 通过 [运行] | 低（思路简单，有安全问题） |
| Jane-o-O-o-O/Agent-CAD | `bfb37827` | MIT | HTTP（FastAPI）+ Web；**不是 MCP 服务端** | 只有"3D→2D 投影图"导出和旧版 AgentScope 内部工具 | 无（build123d/OCC） | 329 passed / 24 failed / 1 error（需要绕过字体问题）[运行] | 低（3D 应用） |
| LBurny/cadpilot | `c079d2f6` | MIT | MCP（27 个工具）→ FreeCAD XML-RPC | **无** | 需要运行中的 FreeCAD GUI 和插件 | 628 passed, 1 skipped（全 mock）[运行] | 很低（3D、GUI 依赖） |
| agentcad.dev → jdilla1277/agentcad | `aff73bef` | Apache-2.0 | CLI + MCP（11 个工具） | **无**（DXF 被标为 "tier2_recognized — deferred"）[源码] | 无（build123d） | 未跑测试；CLI `run` 实测可产出 STEP [运行] | 中（3D，但"agent-first CLI+MCP、JSON 输出、版本目录"的设计值得借鉴） |
| puran-water/autocad-mcp（599★） | `95476a33` | MIT | MCP（8 个聚合工具） | 有（ezdxf 后端）[运行，进程内] | File-IPC 后端需要 AutoCAD LT 2024+ | 未运行（锁定依赖里没有 pytest） | 中低 |
| daobataotie/CAD-MCP（642★） | `628a9284` | MIT | MCP（35 个工具） | **无**（只有 COM） | AutoCAD/浩辰/中望 COM | 无测试 | 很低 |
| thewisekape/autocad-mcp | `7034dc44` | Apache-2.0 | MCP（22 个工具） | 有（ezdxf 后端）[README] | IPC/COM 可选 | 未运行；仓库里提交的 `pytest_output.txt` 显示 `1 error` 后就停了 [源码] | 低 |

**一句话结论**：只有 AutoCAD-MCP Pro 真正实现了"无头 ezdxf + 大量编辑操作 + 独立复核"，质量也高。但它是"AutoCAD 优先、只有 MCP"的单体服务器：没有 CLI，没有面向外部的 Python API，没有持久化版本历史，打包方式还会污染顶层模块名。其余项目要么依赖商业 CAD 或 FreeCAD GUI，要么是 3D。**建议独立开发 AgentCAD Runtime**。底层直接建在 ezdxf + shapely + 官方 `mcp` SDK 上；对 Pro 的验证、diff、路径安全等设计做参考或在保留版权声明的前提下复用 MIT 代码。

---

## 2. 逐项目详情

### 2.1 AutoCAD-MCP Pro（U-C4N/AutoCad-MCP）

- commit `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`（2026-10-26），版本 1.7.0，MIT（`LICENSE` 版权人 Umutcan Edizsalan）
- 规模 [源码]：Python 约 86k 行。`server.py` 单文件 13,415 行，`backends/ezdxf_backend.py` 9,538 行，`backends/com_backend.py` 8,784 行，另有 `engineering/` 下的验证、理解、机械、建筑、P&ID 等子包
- 依赖：`fastmcp>=3.4.5,<4`（Apache-2.0）、`ezdxf>=1.4,<2`（MIT）、`pydantic`（MIT）；可选 `pywin32`、`matplotlib`、`openpyxl`。锁定版本为 mcp 1.29.0、ezdxf 1.4.4

**安装与运行 [运行]**
```
uv sync --locked --extra pdf --extra office            # 成功
AUTOCAD_MCP_BACKEND=ezdxf ALLOWED_PATHS=<out> python mcp_probe.py - <repo> .venv/Scripts/autocad-mcp.exe
→ SERVER: AutoCAD MCP Pro / TOOL_COUNT: 243   （README 写的是注册 248 个、默认公开 243 个，与实测一致）
```

无头调用序列（ezdxf 后端）的实测结果：
- `drawing_new`(bootstrap) 创建了 GEOMETRY/DIM/CENTER/… 等标准图层和线型 ✔
- `layer_create`、`entity_create_line/rectangle/text`、`dimension_linear` 都返回了 handle、包围盒和面积 ✔
- `drawing_save_as a.dxf` → `drawing_open` → `entity_list` 读回 4 个实体 ✔
- `validation_check` 报告了空图层等 10 条 info ✔
- `transaction_begin` → move + delete → `transaction_rollback` 后实体恢复 ✔（实现方式是整份 DXF 快照）
- `drawing_undo` 报错：`the headless backend keeps no history by default … Set EZDXF_UNDO_DEPTH`，即无头模式下 undo 默认关闭
- `drawing_diff old=a.dxf` 正确报告 `changed: 2`，handle 保持稳定 ✔
- `drawing_export_dwg` 报错：`the ezdxf backend writes DWG only through the ODA File Converter, which is not installed here`
- `drawing_open C:/Windows/win.ini` 报错：`Path rejected … inside a system directory` ✔
- 当库用也可以：`from backends.ezdxf_backend import EzdxfBackend; await b.entity_create_line(...)` 正常返回 `EntityInfo` ✔

**测试 [运行]**
- 第一次全量跑时，默认 pytest 临时目录 `C:\Users\HUAWEI\AppData\Local\Temp\pytest-of-HUAWEI` 触发 `PermissionError: [WinError 5]`，产生 564 个 error。这是本机沙箱限制，不是项目缺陷。
- 改用 `--basetemp=<scratchpad>` 后分 4 组并行重跑：`1221 + 1549 + 1968 + 1321` 全部通过，合计 **6059 passed, 1 xfailed**，与 README 声称的 "6060 collected" 一致，用时约 2 分钟。

**能力矩阵**
- 接口：只有 MCP（stdio，也可 `--transport http`）。**没有 CLI 操作命令**，`autocad-mcp` 入口只负责启动服务器 [源码]。
- 无头：是（ezdxf）[运行]。PNG/PDF 渲染需要 `[pdf]` extra [README]。
- DXF：新建、读、改都支持 [运行]。DWG 无头只能借 ODA，真正的 DWG 读写要靠 COM [运行/README]。
- 图层、块、标注、文字：都支持 [运行：图层/文字/线性标注；源码：块定义、属性、dimstyle、MLEADER、TABLE]。
- 编辑：move/copy/rotate/scale/mirror/offset/trim/extend/fillet/chamfer/array 等 [源码；move 已运行]。
- 读入既有图纸再修改：支持（open→move→diff→save_as）[运行]。另有 `drawing_understand` 用来读别人画的图 [源码]。
- 自然语言/文档驱动：服务端不内置 LLM。它提供 `drawing_preflight(intent, requirements)`、`*_from_spec` 这类"规格驱动"工具和 recipes 资源 [源码/README]。
- 独立验证：`drawing_verify_requirements` 在几何上测量需求；`drawing_deliver` 会重新打开输出文件再测一遍 [README/源码，未运行该工具]。`drawing_diff` [运行]。
- 版本与回滚：单检查点事务 [运行]；可选 N 步内存快照 undo（`EZDXF_UNDO_DEPTH`）[运行报错信息]；document revision 计数加 stale_revision 预检 [README]。README 原话 "The operation journal is in memory: a server restart forgets every operation id (durable in 1.8)"，**没有持久化版本历史**。
- 已知短板（README 自述）：无头 DIMENSION 在 dimstyle 修改后不会重新渲染；无头没有 REGION 和 2D 布尔；`ALLOWED_PATHS` 默认不限制；损坏的 DXF 直接拒绝（1.7.1 才计划加 `ezdxf.recover`）；工具全量公开时空闲开销约 89k token（lean 模式 66 个工具约 25k）。
- 打包隐患 [源码]：`pyproject` 用 hatch `only-include = ["server.py","config.py","security.py","version.py","backends","engineering",...]`，wheel 会往 site-packages 顶层装 `server`、`config`、`backends`、`engineering` 这些通用名字。拿它当依赖会和别的包冲突，fork 时必须先重新命名空间。

**可复用**：`engineering/verification/*`（需求绑定和测量）、`engineering/understand/diff.py`（基于 handle/几何的 diff）、`qa_scan`/`critique`、`security.py`（路径校验）、事务快照模式、ezdxf 后端里大量"ezdxf 坑位"的处理经验，以及测试用例（作为行为规格）。MIT 协议允许复用，需保留版权和许可声明。

**是否适合 fork**：不建议整仓 fork。原因有四点：工具契约以 AutoCAD 语义为中心，COM 和 ezdxf 双后端约 18k 行耦合在一起；13k 行单文件 server；fastmcp 3.x 变动较快（作者在 pyproject 注释里自己也提到了）；没有 CLI，也没有稳定的 Python API。建议当作"参考实现 + 可挑选的 MIT 代码来源"。

### 2.2 id0o0bi/autocad-mcp

- commit `aff502aea534683da44ab378b2c9b8ddef6f5e01`（2026-10-10），MIT，约 1.1k 行 Python。依赖 `mcp>=2,<3`（用 v2 新 API `mcp.server.mcpserver.MCPServer`）和 `ezdxf`。
- [运行] `uv pip install -r requirements.txt`（装到 mcp 2.3.0、ezdxf 1.4.5）。MCP 列出 5 个工具：`drawing_run, drawing_summary, autocad_run_lisp, autocad_status, autocad_accoreconsole_switches`。
- [运行] `drawing_run` 能新建图层、直线、`add_linear_dim().render()` 和文字，并保存；`drawing_summary` 读回结果为 `LINE 1 / DIMENSION 1 / TEXT 1`，版本 AC1024 ✔
- **安全问题 [运行]**：`drawing_run(code="import os; emit(os.getcwd())")` 执行成功并返回了工作目录。原因是 `drawings.py:95 exec(compile(code, "<drawing>", "exec"), scope)` 没有任何沙箱。
- [运行] `autocad_status` 返回 `"accoreconsole.exe not found. It ships with AutoCAD 2013 and newer"`；`autocad_run_lisp` 返回同样的错误。
- [运行] `cases/run_all.py`：3/4 通过。`04_floorplan.py` 因为缺 accoreconsole，在 `KeyError: 'exit_code'` 处失败（错误分支少返回了一个键，属于小 bug）。`drawings.self_check()` 输出 OK。
- 没有 pytest 套件。版本管理和回滚都没有。审计规则（10 类缺陷）写在示例脚本里，不是工具。
- 可复用：`cases/03_audit.py` 的审计规则清单可以当验证规则的灵感来源。不适合 fork。

### 2.3 Agent-CAD（Jane-o-O-o-O/Agent-CAD）

- commit `bfb37827f50593ee7f7ef870643b6f5780ac1236`（2026-10-21），MIT。仓库里有 Vue 前端、FastAPI 后端、AgentScope 全家桶和 sandbox，共 564 个文件。
- 定位 [README/源码]：3D B-Rep（build123d 0.11.1 / OCP 7.9）。2D 图纸由最终实体投影得到（`app/infrastructure/cad_v2/drawings.py` 使用真正的 ezdxf DIMENSION，`render()`）。接口是 HTTP `/api/v1/cad-v2/*` 和 Web 工作台。**它本身不提供 MCP 服务端**：`tools/mcp.py` 是 MCP 客户端，`mcp.json.example` 配的是 filesystem/github 这类外部服务器。
- 旧版 2D 工具 `CADToolkit.cad_generate_dxf_from_spec` [源码]：只是 AgentScope 内部的 ReAct 工具。它的标注是"可见标注"，用 `_add_raw_line` 和文字拼出来，不是 DIMENSION 实体。
- 自带样例 `mounting-plate-8.dxf` [运行，ezdxf 读取]：AC1027，`LINE 32, DIMENSION 8, TEXT 5, CIRCLE 4`。
- 安装与测试 [运行]：`uv pip sync requirements-cad-v2.txt` 成功，但 `import build123d` 直接崩溃：
  ```
  build123d/text.py:271 available_fonts = FontManager().available_fonts
  fontTools.ttLib.TTLibError: Not a TrueType or OpenType font (bad sfntVersion)
  ```
  原因是 build123d 会扫描 `C:\Windows\Fonts`，而本机的 `mstmc.ttf` 不是合法 TTF。这属于 build123d 0.11.1 在 Windows 上的健壮性问题。我在 `scripts/pytest_skipbadfont.py` 里过滤掉这个文件，再补装 `jsonschema mcp pytest`，然后 `CAD_V2_ISOLATION=process-dev pytest tests/cad_v2`：
  **329 passed, 24 failed, 1 skipped, 1 error**。失败原因：`module 'signal' has no attribute 'SIGXCPU'` 出现 28 次，`[WinError 193]` 出现 4 次，都来自只支持 POSIX 的 worker；README 也写明 strict worker 需要 Linux Landlock ABI≥3。1 个 error 是 `test_tool_bridge.py` 需要全量应用依赖。`test_drawings.py` 通过。
- 版本与回滚：不可变 revision 加 restore-as-new-revision [README/源码]，但对象是 3D IR，不是 DXF。
- 可复用：它的"revision + artifacts + 验证报告"设计思路可以参考；DXF 投影标注代码可参考。不适合 fork（3D、栈太重、Linux-only）。

### 2.4 CADPilot（LBurny/cadpilot）

- commit `c079d2f6b1d17858d4b374610a6174deaacb0d34`（2026-10-07），MIT（派生自 neka-nat/freecad-mcp，双版权人）。
- [运行] `uv sync` 后，列出 27 个 MCP 工具（`create_document, cad, execute_code, measure_geometry, check_interference, assemble, step_control …`）。启动日志：`Could not connect to FreeCAD on startup: the FreeCAD RPC endpoint refused connections for 10s`；`diagnose` 的结论是 `FreeCAD does not appear to be running at all`。
- [运行] `pytest tests`：**628 passed, 1 skipped**（全部为 mock 或纯逻辑测试，不连 FreeCAD）。
- 能力：3D 参数化（PartDesign 和装配），步骤日志加回滚 [README]。**没有 DXF 或 2D 工具** [源码 grep：仅在截图说明里提到 TechDraw]。`execute_code` 会在 FreeCAD 里执行任意代码 [源码]。
- 结论：和本项目基本不相关。"步骤日志、接受/拒绝、回放"的交互设计可以参考。

### 2.5 agentcad.dev → jdilla1277/agentcad

- 网站写明 "Open source · Free · No signup"，源码在 https://github.com/jdilla1277/agentcad。
- commit `aff73befc89f0562500cf7c69ac572f68d3aeb4a`（2026-10-26），Apache-2.0，CLI 名 `agentcad`，MCP 通过 `python -m agentcad.mcp` 启动。
- [运行] `uv pip install -e ".[mcp]"` 后：`agentcad --help` 列出 init/run/render/export/measure/inspect/check-spec/diff/recover 等命令；MCP 列出 11 个工具：`run, render, export, measure, inspect, check_spec, docs, context, recover, diff, view`。
- [运行] `agentcad init --name t1` 生成 `agentcad.json`、`AGENTS.md`、`.claude/skills/agentcad/SKILL.md`（会往项目里写 agent 指令文件）。
  - `agentcad run box.py --label v1` 第一次返回 `validation_error: show_object_missing`，并附带 `repair_snippets`，可见错误设计对 agent 友好。
  - 补上 `show_object` 后报错：`Internal error: UnicodeEncodeError: 'gbk' codec can't encode character '\xd8'`，原因是写 viewer.html 时没有指定编码，属于中文 Windows 上的 bug。
  - 加 `PYTHONUTF8=1` 后：`status=success, outputs.step=v2/output.step, volume 1000.0, is_valid True, version 2`。
- 2D/DXF：`file_detect.py` 中写着 `".dxf": TIER2_RECOGNIZED  # … deferred`，**不支持 DXF** [源码]。
- 可借鉴：只把 JSON 写到 stdout、进度写到 stderr；版本目录 `vN/`；`next_actions` 和 `repair_snippets` 形式的错误契约；CLI 与 MCP 同构。这些和 AgentCAD 想做的"agent-first"方向一致，但它面向 3D。

### 2.6 补充检索到的项目（检索范围有限）

检索命令为 `gh search repos "<q>" --sort stars`，关键词包括 dxf mcp / ezdxf mcp / autocad mcp / cad mcp server / cadquery mcp / librecad mcp。

- **puran-water/autocad-mcp**（599★，MIT，`95476a33`，2026-02-20）
  - 8 个聚合工具（drawing/entity/layer/block/annotation/pid/view/system），用 `operation` 加 `data` 字典传参，有 File-IPC 和 ezdxf 两个后端。
  - [运行，进程内调用 server 函数]：create、layer、line、dimension_linear、save、open、info 都成功（AC1027，`entity_count 2`）。`undo` 返回 `"Not supported on this backend"`。
  - [运行，stdio]：`tools/list` 正常（8 个），但第一次 `tools/call` 就以 `McpError: Connection closed` 结束；`PYTHONUTF8=1` 下也一样，根因没有定位。
  - 测试：锁定环境里没有 pytest，所以没跑。
- **daobataotie/CAD-MCP**（642★，MIT，`628a9284`）
  - 35 个工具，只有 COM（AutoCAD/浩辰/中望）。
  - [运行] `draw_line` 返回 `AutoCAD.Application: HRESULT 0x800401F3`（CO_E_CLASSSTRING，未注册 AutoCAD），不能无头运行。
- **thewisekape/autocad-mcp**（Apache-2.0，`7034dc44`）
  - 3 个后端、22 个工具 [README]。仓库里提交的 `pytest_output.txt` 结尾是 `ERROR tests/test_ezdxf_backend.py::TestDrawingManagement::test_initialize … 1 error`。没有运行。
- 只看了元数据、没有克隆的项目：
  - OmniZenRaj/dxf-mcp（MIT，只读 DXF，0★）
  - crhomagnus/ezdxf_mcp（许可为 "other"，自述 Noncommercial，**不可复用**）
  - rishigundakaram/cadquery-mcp-server（**无许可**）
  - mattmohandiss/cad-mcp-server（STEP 检查）
  - LokmenoWer/best-cad-mcp（COM）
  - mixelpixx/KiCAD-MCP-Server（EDA，不在范围内）

---

## 3. 底层库评估

### 3.1 ezdxf（推荐作为核心）[运行]

脚本为 `scripts/ezdxf_check.py`，venv 里装的是 ezdxf 1.4.5、shapely 2.2.0、mcp 2.3.0、matplotlib 3.11.2。

- 许可：MIT（classifier `License :: OSI Approved :: MIT License`）。纯 Python，无头运行，不需要 CAD。
- 可新建的版本：`['AC1009','AC1015','AC1018','AC1021','AC1024','AC1027','AC1032']`，即 R12 到 R2018。R12 不支持 LWPOLYLINE（实测抛出 `DXFVersionError: LWPOLYLINE requires DXF R2000`）。
- 在 R2000、R2010、R2018 下分别新建图层、块（DOOR）+ INSERT、TEXT、MTEXT、线性标注和半径标注（`render()`），写盘后用 `readfile` 读回：
  `{'LWPOLYLINE':1,'INSERT':1,'TEXT':1,'DIMENSION':2,'MTEXT':1}`，`get_measurement()` = `[6000.0, 500.0]`，标注几何块都存在 ✔
- 修改既有文件：平移多段线、改文字、`audit()`（0 errors），另存后再读回确认生效 ✔；`bbox.extents` 正常 ✔
- 渲染：matplotlib 输出 PNG（37,236 B）✔；`SVGBackend` 输出 SVG（10,654 字符）✔，不依赖 GUI。
- **注意事项**：
  - 截断的文件用 `readfile` 读会抛 `DXFStructureError`（这是对的）。但 `recover.readfile` 读同一个文件返回 `ok, entities: 0, errors: 0`，等于**静默丢失全部实体**。因此运行时必须有独立的读回和实体计数校验，不能只看 recover 是否报错。
  - DIMENSION 不会随几何修改自动更新，需要重新 `render()`（Pro 的 README 也提到 dimstyle 修改后不会重新渲染）。
  - DWG 只能借 `ezdxf.addons.odafc`。本机 `odafc.is_installed() → False`。

### 3.2 DWG 方案

- **ODA File Converter**：ODA 的专有软件，免费下载，有 GUI 和命令行批处理（源目录、目标目录、版本、递归、审计）[网站]。官网下载页**没有写明许可条款**，商用、再分发、捆绑的权利都需要查安装包里附带的 EULA。不能假设可以随产品分发，只能作为"用户自行安装的可选外部工具"（ezdxf odafc 和 Pro 都是这样处理的）。
- **LibreDWG**：GPL-3.0（`gh api repos/LibreDWG/libredwg` → `GPL-3.0`）。README 写明写入只支持到 r2004，`dxf2dwg` "r2000 only so far"，R2007 写入不可用。如果链接或打包会触发 GPL 传染；只能以独立进程调用，并单独评估分发合规。
- LibreCAD（GPL-2.0，GitHub 显示 NOASSERTION）有 `dxf2pdf`/`dxf2png` 命令行；QCAD 社区版是 GPLv3，dwg 相关命令行工具在商业版里。这两项**都没有在本机验证**，只适合作为可选的外部渲染或校验器。
- 结论：MVP 只支持 DXF；DWG 做成可选插件，通过 ODA 或 LibreDWG 子进程实现，默认关闭，并在文档中写明许可风险。

### 3.3 shapely [运行]

shapely 2.2.0，BSD-3-Clause。用读回的多段线构造 `Polygon(pts).area = 24,000,000`，`is_valid = True`。适合做闭合、自交、面积、包含、重叠这类独立几何检查。2D 布尔可以用 shapely 计算后再回写为多段线或 HATCH，从而绕开 ezdxf 的 REGION 缺口。

### 3.4 官方 `mcp` Python SDK [运行]

- PyPI 最新为 **2.3.0**，MIT。1.x 到 2.x 有破坏性变化。我自己的探测客户端就踩到了：`InitializeResult.serverInfo` 在 2.x 改成了 `server_info`；服务端 2.x 用 `mcp.server.mcpserver.MCPServer`（id0o0bi 的写法），1.x 用 `FastMCP`。
- 现状：Pro 通过 fastmcp 3.4.5 锁在 mcp 1.29；agentcad 要求 `mcp<2`；id0o0bi 要求 `mcp>=2`。
- 建议 AgentCAD 直接依赖官方 `mcp`，锁定主版本（`>=2,<3`），并把 MCP 层做成很薄的适配层，便于跟随 SDK 升级。不建议引入 fastmcp 这一层，除非需要它的额外功能。

---

## 4. 可复用组件（按价值排序）

1. **ezdxf**（MIT）：DXF 读写、标注渲染、audit/recover、SVG/PNG 渲染。直接作为核心依赖。
2. **shapely**（BSD-3）：独立几何校验和 2D 布尔。
3. **官方 mcp SDK**（MIT）：MCP 适配层。
4. **AutoCAD-MCP Pro（MIT）中的设计和代码**，复用时需保留版权声明：
   - `engineering/verification/*`：需求到几何特征的绑定和测量，结果分 pass/fail/unknown/ambiguous
   - `engineering/understand/diff.py`：两版 DXF 的 handle 和几何 diff [运行]
   - `security.py`：路径白名单和系统目录拒绝 [运行]
   - 事务快照回滚模式 [运行]，以及 revision/stale_revision 预检、client operation id 幂等重放 [README]
   - 6000 多条测试，可作为 ezdxf 行为边界的参考用例
5. **agentcad（Apache-2.0）的交互契约**：stdout 只输出 JSON、`next_actions`/`repair_snippets` 错误格式、`vN/` 版本目录、`recover` 命令。这些是设计借鉴，不需要拷代码。
6. **id0o0bi `cases/03_audit.py` 的 10 类缺陷规则**：零长线、重复线、伪闭合、0 层实体、字高过小、出图框、`$INSUNITS` 未声明等，可作为默认 lint 规则清单。

## 5. Fork 候选

| 候选 | 评价 |
|---|---|
| AutoCAD-MCP Pro | **唯一值得认真考虑的**，但仍不建议整仓 fork：(1) 契约以 AutoCAD 为中心，243 个工具，空闲约 89k token；(2) `server.py` 单文件 13k 行，COM 与 ezdxf 双后端约 18k 行耦合；(3) wheel 往顶层装 `server`/`config`/`backends`/`engineering`，必须先重新命名空间；(4) 没有 CLI，没有对外 Python API，没有持久化版本；(5) 依赖变动快的 fastmcp 3.x。fork 后要改的部分接近重写，不如"独立实现 + 按模块移植" |
| puran-water / thewisekape | 功能是 Pro 的子集；本机 stdio 调用失败或测试有 error，不建议 |
| 其余 | 3D、依赖 GUI 或 COM，与需求不符 |

## 6. 现有项目普遍缺失的能力（AgentCAD 的差异化空间）

1. **CLI、MCP、Python API 三者同构**：2D 方向没有任何项目做到。Pro 只有 MCP，agentcad 有 CLI+MCP 但只做 3D。
2. **持久化的操作日志、版本历史和回滚**（落盘、可重放、进程重启后仍在）：Pro 只在内存里，并写明 "durable in 1.8"；其余项目没有。
3. **DXF 读回独立校验**：用独立进程或独立读取器，对实体计数、关键几何、标注测量值做回读比对。在 `recover` 可能静默丢实体的情况下（见 3.1，实测），这一项是必需的。
4. **标注关联**：几何修改后自动重新生成或校验相关 DIMENSION。ezdxf 不会自动做，各项目也都没做。
5. **无头 2D 布尔和区域**：Pro 明确缺失，可以用 shapely 补上。
6. **安全的执行模型**：id0o0bi 和 CADPilot 都暴露了任意代码执行。AgentCAD 应只暴露类型化操作，不做 `exec`。
7. **小而稳定的工具面**和**结构化错误**（错误码加修复建议），控制 token 成本。
8. **Windows 中文区域的健壮性**：agentcad（GBK 写文件崩溃）和 build123d（坏字体崩溃）在本机都翻车。AgentCAD 需要统一用 UTF-8 显式读写，并在 CI 里加一个 Windows 非 UTF-8 locale 的测试通道。
9. **不依赖专有软件的 DWG**：所有项目都缺，而且受许可限制只能做成可选插件。

## 7. 许可与依赖约束

- 可自由复用（需保留声明）：AutoCAD-MCP Pro、id0o0bi、Agent-CAD、CADPilot、puran-water、daobataotie 都是 **MIT**；agentcad、thewisekape 是 **Apache-2.0**（需保留 NOTICE，thewisekape 有 NOTICE 文件）。
- 不可复用：没有 LICENSE 的仓库（如 rishigundakaram/cadquery-mcp-server），以及 "Noncommercial" 的仓库（crhomagnus/ezdxf_mcp）。
- 核心库：ezdxf 是 MIT，shapely 是 BSD-3，mcp 是 MIT，fastmcp 是 Apache-2.0，pydantic 是 MIT。全部宽松许可，没有传染性。
- DWG：ODA File Converter 是专有软件，许可条款要单独审阅，不能捆绑；LibreDWG 是 GPL-3.0，只能子进程调用、可选启用，并单独做分发合规评估；LibreCAD（GPL-2.0）和 QCAD 社区版（GPL-3.0）同理。
- 商业 CAD：Pro 的 COM 后端、id0o0bi 的 accoreconsole、puran 和 thewisekape 的 File-IPC、daobataotie 都需要 AutoCAD 或 LT 许可，不应进入 AgentCAD 的核心路径。

## 8. 最终建议

**值得独立开发。** 理由如下：

1. 需求是"无头、agent-first 的 2D 运行时，CLI+MCP+Python API，DXF 为中心，可验证、可回滚"。现有项目里只有 AutoCAD-MCP Pro 覆盖了其中的"无头 DXF 编辑和验证"部分，但它的架构目标是"AI 操作 AutoCAD 的 MCP 服务器"：AutoCAD 语义、单体 MCP、没有 CLI 和 API、版本历史只在内存。核心契约和 AgentCAD 不一致，fork 后基本要重构。
2. 真正的难点在 ezdxf（DXF 读写、标注渲染）和 shapely（几何校验），这两部分可以直接依赖，许可也干净。AgentCAD 要写的是上层：类型化操作模型、持久化操作日志和版本、独立校验、三端同构接口。这正是现有项目都缺的部分。
3. 降低风险的做法：把 Pro 当作"行为参考和可移植代码库"，在 MIT 下按模块移植 verification、diff、路径安全，保留版权声明；把它的测试场景当验收用例的灵感来源；MVP 只做 DXF（R2010/R2018），DWG 做成可选的外部转换插件。

---

### 附：关键命令记录（节选）

```bash
# 克隆与 commit
git clone --depth 1 https://github.com/U-C4N/AutoCad-MCP autocad-mcp-pro   # 58a05ddf
git clone --depth 1 https://github.com/id0o0bi/autocad-mcp autocad-mcp-id0  # aff502ae
git clone --depth 1 https://github.com/Jane-o-O-o-O/Agent-CAD agent-cad     # bfb37827
git clone --depth 1 https://github.com/LBurny/cadpilot cadpilot             # c079d2f6
git clone --depth 1 https://github.com/jdilla1277/agentcad agentcad-jdilla  # aff73bef
git clone --depth 1 https://github.com/puran-water/autocad-mcp ...          # 95476a33
git clone --depth 1 https://github.com/daobataotie/CAD-MCP ...              # 628a9284
git clone --depth 1 https://github.com/thewisekape/autocad-mcp ...          # 7034dc44

# Pro
uv sync --locked --extra pdf --extra office --group dev
AUTOCAD_MCP_BACKEND=ezdxf python scripts/mcp_probe.py pro_calls.json <repo> .venv/Scripts/autocad-mcp.exe
python -m pytest -q -p no:cacheprovider --basetemp=<scratch> <chunk>       # 4 组 → 6059 passed, 1 xfailed

# Agent-CAD
uv pip sync --python .venv-cad/Scripts/python.exe requirements-cad-v2.txt
CAD_V2_ISOLATION=process-dev python scripts/pytest_skipbadfont.py -q tests/cad_v2   # 329 passed / 24 failed / 1 error

# CADPilot
uv sync && pytest tests                                                     # 628 passed, 1 skipped

# agentcad
uv pip install -e ".[mcp]"; agentcad init --name t1
PYTHONUTF8=1 agentcad run box.py --label v2                                 # success, STEP + metrics

# ezdxf / shapely
python -I scripts/ezdxf_check.py <out>
```
