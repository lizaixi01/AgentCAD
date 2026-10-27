# 技术路线决策记录 (ADR-001)

日期：2026-10-26　状态：已采纳并实现（P0 + 大部分 P1）

## 背景与证据

- 现有项目审计（[audit/existing-projects.md](audit/existing-projects.md)，8 个仓库均已克隆，能运行的都运行过）：
  - 只有 **AutoCAD-MCP Pro**（MIT）具备无头 ezdxf 后端和大量编辑操作，测试 6059 项通过。但它只有 MCP，没有 CLI 和对外 Python API；操作日志只存在内存里；`server.py` 单文件 1.3 万行；空闲时工具描述约 8.9 万 token；wheel 会安装 `server`、`config` 这类通用顶层模块名。
  - 其余项目要么依赖 AutoCAD COM / accoreconsole / FreeCAD GUI，要么是 3D 应用（build123d），要么存在安全问题（id0o0bi/autocad-mcp 允许执行任意 Python，已实测确认）。
- AutoCAD 研究（[research/autocad-dxf-research.md](research/autocad-dxf-research.md)）：本机没有 AutoCAD 授权，黑盒测试**被阻塞**。研究依据是 Autodesk 公开文档，以及 5 组实际运行的 ezdxf 实验。
- 本机环境：Windows 11、Python 3.12、uv、Codex CLI（已登录），无任何商业 CAD。

## 决策

1. **独立实现 Runtime，不 Fork 现有项目。** 理由：要求的形态（CLI/MCP/HTTP/Python 共用一个服务层，磁盘持久化的检查点和 journal，独立验证器）在 AutoCAD-MCP Pro 中需要大规模重构才能得到。重构的成本高于在 ezdxf 上直接实现，而且它的工具面（243 个工具、AutoCAD 语义）与"少量高层、可批量"的 Agent 接口目标相反。只借鉴它的设计思想（diff、路径安全、事务），不复制代码。
2. **几何/文件内核复用 ezdxf 1.4（MIT）。** 它支持 R2000–R2018 读写、真实 DIMENSION 渲染、块和属性，且完全无头。已知缺陷由 Runtime 补齐：
   - 没有 trim、extend、fillet、chamfer、offset：自研 `geom.py` + `ops/edit.py`。
   - 不写 group 42：渲染后自行写入。
   - 镜像会产生 OCS 挤出方向 (0,0,-1)：镜像后归一化。
   - 不维护 `$EXTMIN/$EXTMAX`：保存时自行计算。实测这会导致 LibreOffice 把整张图缩成一个点。
   - recover 模式会静默丢弃实体：一律严格读取，并区分错误类型。
3. **不引入 shapely。** 当前验证所需的几何（多边形点包含、面积、圆/线求交）用约 200 行纯 Python 实现即可，并有测试覆盖。依赖越少，验证器越容易审计。
4. **MCP SDK 固定为 `mcp>=1.20,<2`。** mcp 2.x（2.3.0）把 FastMCP 改名为 MCPServer，API 不兼容。
5. **DWG 不进入核心。** ODA File Converter 是专有软件，LibreDWG 是 GPL-3.0 且写入能力有限。列为 P3 可选插件。
6. **验证器与生成器分离。** 验证器只读磁盘文件，从几何识别特征（轮廓、孔、标注），从定义点重新测量标注值。需求只从规格推导，与操作计划无关。
7. **自然语言不进 Runtime。** 文档提取使用确定性规则；Agent 自己做理解，提交带引文的事实，由 Runtime 核对引文是否真实存在于文档中。
8. **实体标识用 DXF handle，语义标识用 XDATA 标签**（AppID `AGENTCAD`）。零件规格与 plan 标签以 XRECORD 形式存入 DXF 本身，随文件走。

## 后果

- P0 全部完成，P1 中除"表格对象（AutoCAD TABLE 实体）"与"多页 PDF 版式"外完成；详见 [coverage.md](coverage.md)。
- 约束系统明确分两层：检查 15 类；强制 12 类，采用顺序直接修改，不是联立求解，冲突时拒绝保存。
- 已知限制见 [limitations-roadmap.md](limitations-roadmap.md)。

---

# ADR-002：AutoCAD 作为可选后端与测试 oracle

日期：2026-10-27　状态：已采纳并实现

**背景**：用户安装了 AutoCAD 2027，原研究中被阻塞的实机验证由此可以进行（[research/autocad-observations.md](research/autocad-observations.md)）。

**决策**

1. **核心仍然不依赖 AutoCAD。** `backends/autocad.py` 是可选模块：未安装 AutoCAD 时，相关工具返回 `dependency/DEPENDENCY_MISSING`，其余功能不受影响。
2. **只通过 accoreconsole（无头）调用。** 不驱动 GUI，不用 COM。脚本内联在 .scr 里（SECURELOAD 不允许 `load`，而我们不修改安全设置），作业目录只用 ASCII 路径，坐标参数加 `_non` 绕开对象捕捉。
3. **AutoCAD 的角色是互操作通道和 oracle，而不是执行内核。** DWG 导入/导出和 AUDIT 交给 AutoCAD；几何操作仍由 AgentCAD 自己执行，并用 AutoCAD 录制的 golden 数据做差分回归。这样测试在没有 AutoCAD 的机器上（例如 CI）也能运行。
4. **遇到差异时以 AutoCAD 的约定为准。** 包括：三点弧方向、角度标注 42 用弧度、MIRRTEXT=0 时镜像包围盒、块参照真正镜像、R12 表项。文字水平位置的残差取决于字形度量，我们记录下来，不去模拟字体。
5. **不改动宿主环境。** 实验中曾误改用户的 TRIMEXTENDMODE 和 FILEDIA，已恢复并记录在案。之后所有会持久化的系统变量都在同一会话内保存并恢复，并用注册表前后比对来验证。
