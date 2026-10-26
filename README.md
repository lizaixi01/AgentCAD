# AgentCAD Runtime

面向 AI Agent 的无 GUI 二维 CAD 执行环境。外部 Agent（Claude Code、Codex 等）通过 **CLI / MCP / HTTP / Python API** 直接创建、读取、修改和验证 DXF 工程图；Runtime 负责确定性的 CAD 操作、事务与回滚、操作记录，以及**独立于生成过程的几何验证**。自然语言理解和规划由外部 Agent 负责，Runtime 本身不调用任何模型（`model_calls = 0`）。

- 不依赖 AutoCAD 或任何商业软件；底层使用 [ezdxf](https://ezdxf.mozman.de/)（MIT）
- 四种接口共用同一个 `Runtime` 服务层，适配层里没有 CAD 逻辑（有测试保证）
- 74 个自动化测试全部通过（[docs/test-results.txt](docs/test-results.txt)），覆盖验收测试 A–H 和安全策略
- 真实外部 Agent 验证：Codex CLI 只通过 MCP 完成了绘图、校验、按错误修正、修改和 diff（[docs/acceptance-report.md](docs/acceptance-report.md#测试-g外部-agent-接入)）

## 安装

```bash
uv venv .venv --python 3.12
uv pip install --python .venv -e ".[dev]"     # dev 包含 pytest 和 Pillow（SVG 预览用）
```

依赖：`ezdxf>=1.3,<2`、`mcp>=1.20,<2`（固定 1.x：mcp 2.x 的 API 不兼容）、`pypdf`；可选 `pillow`（SVG 导出）。

## 30 秒上手（CLI）

所有命令都向 stdout 输出一个 JSON 信封。退出码：0 成功，1 验证未通过，2 输入/规格/几何错误，3 文件错误，4 策略拒绝，5 内部错误。

```bash
agentcad --root ./work draw --spec examples/specs/plate_100x60.json --output plate.dxf
```

```bash
agentcad --root ./work validate plate.dxf
```

```bash
agentcad --root ./work revise plate.dxf --spec examples/specs/change_width_120.json
```

```bash
agentcad --root ./work diff plate.dxf
```

其他命令：`create`、`inspect`、`entities`、`apply`（批量操作）、`constraints`、`extract` / `from-doc`（技术文档）、`rollback`、`checkpoints`、`history`、`recover`、`export`（dxf/R12/svg/json）、`ops`（操作目录）、`mcp`、`serve`。`agentcad <cmd> --help` 查看参数。

批量操作示例（一次调用、原子执行，可用 `"$0"` 引用本批第 0 步创建的实体，用 `"tag:<name>"` 引用带标签的实体）：

```bash
agentcad --root ./work create part.dxf --units mm
```

```bash
agentcad --root ./work apply part.dxf --ops-file examples/specs/ops_example.json
```

注意：如果对一张由规格生成的图纸（如 `plate.dxf`）追加规格之外的几何，`validate` 默认按图纸内存储的规格核对，会如实报告偏差（例如多出一个孔时 `hole_count` 期望 4、实际 5）。这时要么用 `revise` 修改规格，要么用 `--requirements` / `--no-stored-spec` 指定要核对的内容。

## MCP 接入

服务器：`python -m agentcad.mcp_server`（stdio）。环境变量：`AGENTCAD_ROOT`（工作区沙箱，所有路径必须在其中）、`AGENTCAD_READ_ONLY=1`、`AGENTCAD_ALLOWED_OPS=add_line,add_circle,...`。

**Claude Code**（项目级）：

```bash
claude mcp add agentcad --env AGENTCAD_ROOT=D:/Projects/AgentCAD/work -- D:/Projects/AgentCAD/.venv/Scripts/python.exe -m agentcad.mcp_server
```

**Codex CLI**（`~/.codex/config.toml`，与实测配置一致）：

```toml
[mcp_servers.agentcad]
command = "D:/Projects/AgentCAD/.venv/Scripts/python.exe"
args = ["-m", "agentcad.mcp_server"]
env = { AGENTCAD_ROOT = "D:/Projects/AgentCAD/work" }
default_tools_approval_mode = "approve"   # 否则在 approval_policy="never" 下所有工具调用都会被拒绝（实测）
```

MCP 工具：`create_drawing`、`read_drawing`、`inspect_entities`、`apply_operations`、`apply_constraints`、`validate_drawing`、`revise_from_document`、`get_diff`、`rollback`、`export_drawing`，另有 `list_operations`、`draw_from_spec`、`revise_drawing`、`extract_requirements`、`list_checkpoints`、`history`、`recover`、`get_metrics`。

## Python API / HTTP

```python
from agentcad.service import Runtime
from agentcad.policy import Policy

rt = Runtime(Policy(root="work"))
r = rt.draw_from_spec({"kind": "plate", "units": "mm", "width": 100, "height": 60,
                       "holes": [{"pattern": "corners", "diameter": 8, "edge_offset": 10}]}, "plate.dxf")
assert r["ok"] and r["validation"]["passed"]
```

HTTP：`agentcad --root work serve --port 8765`，然后 `POST /v1/<tool>`，请求体是该工具的关键字参数；`GET /v1/tools` 列出工具。

## 端到端演示

```bash
python examples/run_demo.py
```

演示会在 `examples/output/` 生成 A/B/C/E 场景的 DXF、SVG、验证报告、diff 和文档溯源报告（详见 [docs/acceptance-report.md](docs/acceptance-report.md)）。`examples/lo_render/` 里是 LibreOffice 独立导入这些 DXF 后的渲染结果。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/audit/existing-projects.md](docs/audit/existing-projects.md) | 现有项目审计（实际安装运行、commit、许可证） |
| [docs/research/autocad-dxf-research.md](docs/research/autocad-dxf-research.md) | AutoCAD API / 命令 / DXF·DWG 研究与 ezdxf 实验 |
| [docs/decision-record.md](docs/decision-record.md) | 技术路线决策记录 |
| [docs/architecture.md](docs/architecture.md) | 架构、数据模型、事务、错误结构、API 信封 |
| [docs/operations.md](docs/operations.md) | 40 个操作的参数参考（从代码生成） |
| [docs/acceptance-report.md](docs/acceptance-report.md) | 验收测试 A–H 结果与证据、性能指标、兼容性观察 |
| [docs/coverage.md](docs/coverage.md) | 功能覆盖清单（四类状态） |
| [docs/limitations-roadmap.md](docs/limitations-roadmap.md) | 已知限制、依赖、后续路线图 |

## 目录结构

```
src/agentcad/
  service.py        统一业务 API（Runtime），CLI/MCP/HTTP 都调用它
  engine.py         事务式批量执行（预校验 → 内存执行 → 原子提交；spec 修订的就地协调）
  ops/              操作注册表：draw / edit / annotate / structure（类型化参数，同时生成 JSON Schema）
  validate/         独立验证器：features（从文件识别轮廓/孔/标注）、checks（通用完整性）、requirements
  constraints.py    约束检查（15 类）与顺序直接强制（12 类，非联立求解）
  spec.py           零件规格 → 操作计划 + 需求（两者都只从规格推导）
  docspec.py        技术文档（PDF/TXT/MD）→ 带来源的结构化规格；缺失/矛盾检测；Agent 引文校验
  store.py          安全读写、检查点、journal、提交副本、崩溃恢复
  policy.py         沙箱路径、只读、操作白名单、预算
  cli.py  mcp_server.py  http_api.py   适配层
tests/              验收测试 A–H、约束、安全
examples/           演示脚本与输出、Codex 实测记录
scripts/gen_docs.py 从代码生成操作文档和操作×测试矩阵
```

## 运行测试

```bash
python -m pytest tests
```

（在本机沙箱下需要 `--basetemp` 指向可写目录，见 [docs/test-results.txt](docs/test-results.txt) 的运行参数。）
