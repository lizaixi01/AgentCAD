# AutoCAD 2027 实机研究记录（黑盒行为、互操作性、差分测试）

日期：2026-10-27。本记录补完 [autocad-dxf-research.md](autocad-dxf-research.md) 中标为 BLOCKED 的部分。证据等级沿用原记录：**[实测]** 表示在 AutoCAD 中实际运行并观察到，**[推断]**、**[未知]** 同原义。所有脚本在 `research/autocad/`，原始结果在 `research/autocad/results/` 和 `tests/golden/autocad_ops.json`。

## 0. 测试环境与授权前提

- **AutoCAD 2027**：简体中文版，build X.60.0.0，注册表 R26.0 / ACAD-A101:804，安装在 `D:\Apps\AutoCAD\AutoCAD 2027\`。由用户提供并安装，持有合法授权。
- **运行方式**：全部使用 `accoreconsole.exe`（AutoCAD 核心引擎控制台，无 GUI）。每个实验生成一个脚本，运行后读取结果文件。驱动程序是 `research/autocad/acad.py`。
- **对照组**：ezdxf 1.4.5，以及 AgentCAD 当前代码。

## 1. 无头自动化本身的行为（对 Agent 后端最重要）

| 观察 | 证据 | 对实现的启发 |
|---|---|---|
| `accoreconsole /i x.dxf` **不会打开 DXF**，而是退回 `acadiso.dwt` 新建空图 | [实测] 日志显示"使用 acadiso.dwt … 创建的图形" | 用 `DXFIN` 导入；`/i` 只用于 DWG |
| `(load "x.lsp")` 被 SECURELOAD=1 拒绝（"文件加载已取消"） | [实测] | 不修改安全设置。LISP 直接内联进 .scr，不用 load |
| .scr 中的空行会重复上一条命令 | [实测] | 生成脚本时去掉空行 |
| 脚本或结果路径含**非 ASCII 字符**时，脚本不执行，进程挂起 | [实测] `中文目录` 失败；`--` 和 129 字符的长路径都正常 | 后端把文件复制到纯 ASCII 的作业目录，文件名固定 |
| 从 Git Bash 启动会挂起，从 Python `subprocess`（stdin=DEVNULL）启动正常 | [实测]，原因 [未知] | 后端只用 Python 启动 |
| 用户的 **OSMODE=4133**（端点、圆心、交点、延伸捕捉），会让命令点被吸附 | [实测] STRETCH 的基点和第二点被吸到同一处，位移变成 0，结果什么都没变；加 `_non` 后正常。DIM 用例在加 `_non` 前后结果不同 | 每个坐标参数前都加 `"_non"`（`exp_ops_oracle.no_snap`） |
| 交叉窗口选择只看得到当前视图内的对象 | [实测] 不先 ZOOM 时"找到 0 个" | 窗口选择前先 ZOOM |
| 控制台内部 FILEDIA 恒为 0，但不写回注册表 | [实测] 注册表为 1 时，控制台内读到 0，退出后仍为 1 | 不需要也不应该 `setvar FILEDIA` |
| 在控制台里 `setvar` 一个**保存在注册表中的**变量（FILEDIA、TRIMEXTENDMODE），会改到用户 GUI 所用的同一个"<<未命名配置>>" | [实测] | 见 §6 的事故记录；现在一律保存原值并在同一会话内恢复，并用注册表前后比对验证 |
| 控制台输出是 UTF-16LE | [实测] | 按 UTF-16LE 解码 |

## 2. AgentCAD 生成的文件在 AutoCAD 中的表现（`exp_open_generated.py`）

- **步骤**：DXFIN → 统计 → AUDIT（不修复）→ SAVEAS DWG 2018 → DXFOUT 2018。
- **结果**：6 个交付 DXF（A、B、C-PDF、C-中文、R12、Codex 产出）全部 **0 个审计错误** [实测]。单位为 mm（INSUNITS=4），实体数一致。
- **标注值**：AutoCAD 读到的 group 42 与设计值完全一致，例如 B 图为 120/100/60/40/10/10/8。
- **元数据保留**：XDATA 标签（24/24）、`AGENTCAD` 字典（存储的规格）、handle，都在 DXFIN → DXFOUT 和 DXF → DWG → DXF 两条往返路径中保留下来 [实测]。往返后的文件在 AgentCAD 中独立验证 17/17 通过，规格修订仍然只修改 10 个实体。
- **差异**：AutoCAD 写出 MTEXT 时会显式写入宽度 `0`（表示不换行）。AgentCAD 原来把"0"和"缺省"当成不同值，导致一次误判的修改，现已改为语义比较。

### R12 导出（`exp_r12_bisect.py`）

- ezdxf `r12export` 的原始输出在 AutoCAD 中有 **233 个审计错误**。对照组：AutoCAD 自己导出的 R12 再导入是 0 个错误。
- 逐项剔除后定位到两个原因：
  - LTYPE 表含 `BYBLOCK`/`BYLAYER`，导致 2 个错误。R12 中这两个是内置名，不应作为表项写出。
  - `setup=True` 加入的 26 个未使用文字样式，导致 231 个"Annotative 重复"错误。
- **已修复**：`service.clean_r12`。现在 R12 导出是 0 个错误，并有回归测试 `test_autocad_live`。
- R12 本身不保存 `$INSUNITS`，AutoCAD 读到的是 0，导出结果会带警告。

## 3. 原记录 §5.8 中被阻塞的 5 项（`exp_blocked_items.py`）

| # | 问题 | AutoCAD 2027 实测结果 | 处理 |
|---|---|---|---|
| ① | ezdxf 写出的标注没有 group 42；或定义点移动后块未重绘 | 42 保持为 **−1**，AutoCAD **不会**重算；块里的线仍画到 x=100，而定义点在 150。**AutoCAD 相信块，不按定义点重绘** | 证实了"每次修改都重新渲染并写 42"的必要性；验证器的 `DIMENSION_STALE` 检查有实际价值 |
| ② | 负半径 / NaN 坐标 | 负半径：导入时**静默改成 1.0**，AUDIT 不报。NaN："DXF 读取错误……图形被放弃"，**整张图被拒绝** | 验证器对两者都报错（`DEGENERATE_GEOMETRY`、`INVALID_COORDINATE`）；参数层拒绝非有限值 |
| ③ | extrusion=−Z 的 ARC | 原样保留，DXFOUT 后仍是 −Z、OCS 坐标 | 所有读取都改为按 WCS 解释（`model.circle_wcs`、`lwpoly_wcs`）；编辑操作先把目标归一化为 +Z |
| ④ | 未注册 APPID 的 XDATA | **整个文件被拒绝**（"读取 LINE 时遇到下列错误……图形被放弃"） | 新增 `XDATA_APPID_UNREGISTERED`（error）；AgentCAD 自己的标签总会先注册 APPID |
| ⑤ | 弧角 −90/450 | 能导入，DXFOUT 保留原值，但 AUDIT 报 2 个错误 | AgentCAD 写入时归一化；验证器对外来文件报 `ARC_ANGLE_NOT_NORMALIZED` |
| + | XDATA 超过 16 KB | **整个文件被拒绝** | 新增 `XDATA_TOO_LARGE`（error） |

`autocad_audit` 也据此修正：DXFIN 拒绝文件后 AUDIT 面对的是空图，会显示"0 个错误"。现在会识别"图形被放弃"，并返回 `import_rejected=true`。

## 4. 系统变量默认值（基于 acadiso.dwt 的新图）[实测]

MIRRTEXT=0、FILLETRAD=0、TRIMMODE=1、CHAMMODE=0、CHAMFERA=CHAMFERB=0、ARRAYASSOCIATIVITY=1、OFFSETGAPTYPE=0、INSUNITS=4、MEASUREMENT=1、DIMASSOC=2、ANGBASE=0、ANGDIR=0、LUNITS=2、SECURELOAD=1。

- 原记录中"MIRRTEXT 默认值文档互相矛盾"一项，在本机已确认为 **0**（另有 SysvarMonitor 的首选值为 0 佐证）。
- TRIMEXTENDMODE 的读数被我们的实验污染过（见 §6），这里不作为默认值证据。AutoCAD 2021 起的文档默认值为 1 [文档]。

## 5. 编辑命令差分测试（AutoCAD 作为 oracle，`exp_ops_oracle.py`）

**方法**：同一组初始几何，在 AutoCAD 中用 entmake 生成后执行真实命令；在 AgentCAD 中执行对应 op。两边结果统一到 WCS、度数、多段线起点与方向归一化之后再比较。AutoCAD 的结果存为 `tests/golden/autocad_ops.json`，由 `tests/test_autocad_golden.py` 在**不需要 AutoCAD** 的情况下回归。共 27 个用例。

**首轮**：21/25 一致。不一致的 4 项中，3 项是 AgentCAD 的真实缺陷，另 1 项（STRETCH）的根因是 §1 的捕捉问题。补充 2 个镜像用例后共 27 项。**修复后 27/27 一致**。

| 用例 | AutoCAD 行为 [实测] | AgentCAD 结论 |
|---|---|---|
| FILLET R10 / R0（不相交，延伸）/ R5 钝角 | 与几何推导一致 | 一致 |
| CHAMFER 5/8（CHAMMODE 0） | 一致 | 一致 |
| OFFSET 线 / 圆向内 / 矩形向外、向内 | 一致 | 一致 |
| TRIM 线中段 / 线端 / 圆→弧 / 弧中段（TRIMEXTENDMODE=0） | 圆被修剪后变成 ARC；弧中段被修剪后拆成两段 | 一致 |
| EXTEND 到圆 / 到线 | 一致 | 一致 |
| MIRROR 弧 + bulge 多段线 | 结果是 +Z 实体，bulge 取反 | 一致 |
| MIRROR 文字（MIRRTEXT=0，竖轴） | 仍为左对齐；插入点移动，使**墨迹包围盒被镜像**：x=10 → −12.145 = −(10 + 墨迹左 0.0819 + 墨迹右 2.0634) | **原实现只镜像插入点（错）**。现改为交换对齐方式（左↔右），以镜像后的起点为锚点：不依赖字体，得到同一个包围盒（字形两侧留白相等时完全相同） |
| MIRROR 文字（横轴） | 基线从 5 移到 −7.5（= −5 − 字高） | 改为顶部对齐，锚点 −5，基线同为 −7.5。一致 |
| MIRROR 块参照 | **几何真正被镜像**：X 比例 −1，插入点 (−10,10) | **原实现只移动插入点（错）**。现在对 INSERT 做真实变换（ezdxf 表示为 Y 比例 −1、旋转 180°，与 AutoCAD 的变换等价），属性文字仍保持可读 |
| ROTATE / SCALE（含 bulge 多段线） | 一致 | 一致 |
| -ARRAY 矩形 / 环形（旋转项目）/ 90° 部分环形 | 一致 | 一致 |
| STRETCH 交叉窗口 | 窗口内的端点和顶点移动；圆心在窗口内的圆整体移动 | 一致 |
| ARC 三点，顺时针点序 (−10,0)→(0,10)→(10,0) | 存为逆时针 0°→180° 的上半圆 | **原实现得到 180°→0°，即下半圆，不经过中点（错）**。已改为自行计算外接圆并判断方向 |
| DIMLINEAR 水平/垂直、DIMALIGNED、DIMDIAMETER、DIMRADIUS | 42 分别为 100、40、50、20、10 | 一致 |
| DIMANGULAR（三点） | **group 42 以弧度存储**（1.5708），entget 中的 50/51 也是弧度 | **原实现在 42 里写度数（错）**。现在写弧度；对外 API 仍用度；验证器的过期检查会做换算 |

## 6. 事故记录：实验修改了用户的 AutoCAD 偏好设置

- **发生了什么**：差分测试为了使用经典 TRIM/EXTEND 提示，执行了 `setvar TRIMEXTENDMODE 0`；驱动程序的前置部分执行了 `setvar FILEDIA 0`。两者都保存在注册表中，与 GUI 共用同一个配置，结果被持久化。注册表显示 `Variables\TRIMEXTENDMODE=0`、`FixedProfile\General Configuration\FileDialog=0`。
- **处理**：两者都恢复为 AutoCAD 默认值（TRIMEXTENDMODE 的覆盖值已移除，即恢复为 1；FileDialog=1）。驱动程序和后端不再设置 FILEDIA；oracle 中的 TRIMEXTENDMODE 先保存原值，并在同一会话内恢复。之后完整重跑一次 oracle 加全部实机测试，注册表前后一致。
- **启示**：Agent 后端绝不能修改宿主 CAD 的持久设置。命令行为差异要通过显式参数（如 `_non`）或"保存后恢复"来处理。

## 7. 对 Agent-native 架构的启发

1. AutoCAD 对坏数据的处理分两类：**静默修改**（负半径 → 1）和**整文件拒绝**（NaN、未注册 APPID、XDATA 超过 16 KB）。两种都会让 Agent 以为成功了，所以独立验证器必须先于"交付给 AutoCAD 用户"这一步把它们拦下来。
2. AutoCAD 信任 DIMENSION 块而不是定义点，因此"修改几何 → 重绘标注块 → 写 42"必须在同一个事务里完成。
3. 宿主 CAD 的会话状态（捕捉、视图、注册表变量）会改变命令结果。对 Agent 暴露的操作应当是无状态的结构化调用（AgentCAD 的 op），而不是在 GUI 命令外面包一层。
4. DWG 互操作可以通过可选的 AutoCAD 后端可靠实现（实测 DWG 往返后规格、标签、handle 全部保留），核心运行时仍然不依赖商业软件。

## 8. 已转化的实现与自动化测试

- **实现**：
  - `backends/autocad.py`：DWG 导入/导出、AUTOCAD AUDIT。
  - `service.clean_r12`、`store.finalize`（范围写入，源自 LibreOffice 观察）。
  - `model.circle_wcs`/`lwpoly_wcs`：−Z 实体按 WCS 读取。
  - 三点弧、角度标注写弧度、文字/MTEXT/块的镜像。
  - 验证器新增 XDATA、弧角检查。
- **测试**：
  - `tests/test_autocad_golden.py`：27 个 AutoCAD 差分用例，无需 AutoCAD 即可运行。
  - `tests/test_autocad_findings.py`：6 项，无需 AutoCAD。
  - `tests/test_autocad_live.py`：5 项，需要 AutoCAD，未安装时自动跳过。

## 9. 仍然未知

- 从 Git Bash 启动 accoreconsole 会挂起的原因。
- AutoCAD 2027 支持的最新 DXF 版本号。我们一直显式指定 `_V 2018`，所以无法据此判断是否有更新的格式。
- 非对称字形下，"左右对齐交换"方案与 AutoCAD 实际插入点之间的残差（取决于 SHX/TTF 字形度量，本项目没有建模）。
