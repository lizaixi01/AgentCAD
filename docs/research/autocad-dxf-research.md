# AgentCAD Runtime 研究记录：AutoCAD 行为 / API / DXF·DWG 文件格式

- 日期：2026-10-26
- 范围：为 AgentCAD Runtime（无头、agent-first 的 2D CAD 运行时，基于 DXF + ezdxf，对外提供 CLI / MCP / Python API）收集 AutoCAD 语义、自动化接口与文件格式事实。
- 实验脚本与原始输出：`docs/research/experiments/`（`exp01`–`exp05`，输出在 `experiments/outputs/`）。

## 0. 证据等级与总前提

| 标记 | 含义 |
|---|---|
| **[文档]** | 本次核对过的 Autodesk / ODA / GNU / ezdxf 公开文档（附 URL） |
| **[文档-未核]** | 来自 Autodesk 公开文档的常识性内容，本次未逐页重新打开核对，实现前需复核 |
| **[实测]** | 本次在 ezdxf 1.4.5 上实际运行得到（脚本与输出见第 5 节） |
| **[推断]** | 由文档或实测推出的结论，未直接验证 |
| **[未知]** | 无法在本环境确认 |

> **阻塞声明（BLOCKED）**：本环境（Windows 11 Home 10.0.26200、Python 3.12.10、uv 0.12.16、Git Bash）**没有 AutoCAD 许可证或安装**，也未安装 ODA File Converter（`odafc.is_installed() == False`，见 exp03）。因此 **AutoCAD 黑盒行为测试全部无法执行**：凡是写着“AutoCAD 会……”的内容均来自公开文档或推断，不是观察结果。“实测”只针对 ezdxf 这个参考 DXF 实现。若后续拿到 AutoCAD（或 accoreconsole），第 5.7 节列出的用例应当首先补测。

---

## 1. 命令系统与自动化接口

### 1.1 研究目标和测试环境
弄清 AutoCAD 的几种自动化通道（命令行/脚本、AutoLISP、ActiveX/COM、.NET、accoreconsole）各自的对象引用、事务、撤销和错误模型，从中提取 agent-native 运行时应该学什么、避免什么。测试环境：无 AutoCAD，只能读文档。

### 1.2 版本/工具/授权前提
- 以上通道都需要已授权的 AutoCAD 安装（accoreconsole 随 AutoCAD 安装，位于 `Program Files\Autodesk\...`）[文档]。
- 云端等价物 APS Design Automation for AutoCAD 需要 Autodesk 云账号与计费 [推断，未调研]。

### 1.3 输入、步骤、实际输出
无法执行，状态为 BLOCKED。下表是文档调研结果。

| 通道 | 对象引用 | 事务/撤销 | 错误模型 | 要点 |
|---|---|---|---|---|
| 命令行 / `.scr` 脚本 | 无，靠“上一个对象”（`L`）或选择集 | 每条命令一个撤销步；`UNDO BEgin/End` 可以把多条命令合成一组，`Mark/Back` 回退到标记 [文档] | 只有命令行文本提示，没有结构化错误 | 交互式提示驱动，参数顺序由提示决定，脆弱 |
| AutoLISP `(command ...)` / `entmake` / `entmod` / `entget` | 实体名（ename）**仅在当前会话有效**；句柄（组码 5）跨会话不变，`handent` 把句柄转回 ename [文档] | `entmake` 一次一个实体；通常用 `UNDO BE/E` 包裹 | 失败返回 `nil` | `entmake` 直接吃 DXF 组码点对表，这和 DXF 是同一套数据模型 |
| ActiveX/COM（VBA/VLA） | 对象有 `Handle` / `ObjectID` 属性；`HandleToObject` [文档-未核] | `StartUndoMark/EndUndoMark` [文档-未核] | COM 异常 | `ModelSpace.AddArc(center, r, start, end)` 的**角度用弧度**，从起点到终点逆时针 [文档] |
| .NET（`Database`/`Transaction`/`BlockTableRecord`） | `ObjectId`（会话内）+ `Handle`（持久） | `StartTransaction()` → `GetObject(id, ForRead/ForWrite)` → `AppendEntity` + `AddNewlyCreatedDBObject` → `Commit()`；未 Commit 就 Dispose 等于回滚 [文档] | `Autodesk.AutoCAD.Runtime.Exception`，带 `ErrorStatus`（如 `eInvalidInput`、`eWasErased`、`eNotOpenForWrite`）[文档：打开已删除对象返回 eWasErased；其余枚举值为 文档-未核] | 最接近“结构化 API”。.NET `Arc` 构造函数同样用弧度 [文档] |
| `accoreconsole.exe` | 同上（可加载 LISP/.NET） | 同上 | 退出码和控制台文本 | 开关：`/i <dwg>`、`/s <scr>`、`/l <lang>`、`/product`、`/readonly`、`/p <profile>`、`/isolate`；没有 GUI，不能交互式 OPEN，图纸只能经 `/i` 传入 [文档] |

### 1.4 与公开文档对照
- “ename 是会话级、句柄是持久的”由 `handent` 文档确认 [文档]。另据 [文档]：用 BLOCK 命令把实体放进块定义时，实体会**获得新句柄**，说明句柄也不是绝对不变的，“复制/重建”类操作会换 ID。
- .NET 事务示例（打开 BlockTable 读 → 打开模型空间写 → AppendEntity → AddNewlyCreatedDBObject → Commit）与文档一致 [文档]。

### 1.5 已确认事实 / 推断 / 未知
- 确认：持久引用应使用句柄；API 层角度用弧度，DXF 层用度（见 §2、§3）；UNDO 支持分组和标记。
- 推断：AutoCAD 的“命令”实质上是对 Database 的事务性修改加交互提示；agent 运行时只需要前者。
- 未知：accoreconsole 在当前版本（2026/2027）下 `/isolate` 的精确参数格式（论坛说需要用户 ID 和数据目录）；ErrorStatus 的完整枚举表（需要 ObjectARX SDK 头文件）。

### 1.6 对 Agent-native 架构的启发
1. **引用用句柄，不用会话指针**：实体 ID 直接采用 DXF 句柄（十六进制字符串）。实测 ezdxf 的句柄在保存/重载后保持不变（§5 E1）。
2. **事务批处理**：采用 .NET Transaction 模型（`begin → ops[] → commit | rollback`），而不是逐条命令执行。撤销组（UNDO BEgin/End）对应一个 op batch，Mark/Back 对应 checkpoint。
3. **结构化错误码**：参考 `ErrorStatus`，定义 `E_INVALID_INPUT`、`E_NOT_FOUND`（句柄不存在）、`E_ERASED`、`E_LOCKED_LAYER`、`E_UNSUPPORTED_VERSION` 等，每个错误都带 op 索引和字段路径。
4. **不模拟交互式提示**：命令参数一次性用 JSON 给全（accoreconsole 本身也不能交互）。

### 1.7 可转化为实现与自动化测试的项
- T1.1 句柄持久性：创建 → 保存 → 重载后，句柄 → 实体类型一一对应（已由 exp01 覆盖）。
- T1.2 事务原子性：一个 batch 中第 k 个 op 失败时，文档必须与 batch 前逐字节等价（需要确定性输出，见 §3.6）。
- T1.3 API 角度单位：所有对外 API 用“度、逆时针”，并加一个测试，防止有人把弧度直接写进组码 50/51。

---

## 2. 关键 2D 命令行为

### 2.1 研究目标和测试环境
确定常用 2D 命令的参数、默认值和隐式状态（系统变量），并为每个命令设计 agent-native 的结构化等价 op。没有 AutoCAD，只能读文档，并用 ezdxf 实测对应的 DXF 表示。

### 2.2 版本/工具/授权前提
文档以 AutoCAD / AutoCAD LT 2018–2027 帮助为准（各版本措辞基本一致）。ezdxf 1.4.5（MIT 许可）。

### 2.3 输入、步骤、实际输出（文档调研 + ezdxf 对照）

| 命令 | 文档要点（参数/默认/隐式状态） | DXF 结果 | Agent-native 结构化等价（建议） |
|---|---|---|---|
| LINE | 连续点；每段生成一个独立的 LINE；Close/Undo 选项 [文档-未核] | `LINE` 10/20/30、11/21/31，**WCS** | `add_line{start,end}`；折线输入应展开成 N 条 LINE 或改用 `add_polyline` |
| CIRCLE | 圆心+半径/直径、2P、3P、TTR [文档-未核] | `CIRCLE` 10（OCS 圆心）、40 半径 | `add_circle{center,radius}`；2P/3P/TTR 作为纯几何构造函数，结果仍是 center+radius。**必须校验 r>0**（ezdxf 接受负半径，见 E2） |
| ARC | 默认 3 点；还有起点-圆心-终点等组合；正方向由 `$ANGDIR`（0=逆时针）和 `$ANGBASE` 决定 [文档] | `ARC` 50/51，单位为**度**，在 OCS 中**总是从 50 逆时针到 51**；ActiveX/.NET 用弧度 [文档] | `add_arc{center,radius,start_deg,end_deg}`，约定逆时针、单位度；写入前归一化到 [0,360)，并拒绝零跨度（ezdxf 不会归一化，见 E5） |
| PLINE | 默认生成 LWPOLYLINE；可以有弧段和宽度 | `LWPOLYLINE` 90 顶点数、70 标志（1=闭合，128=plinegen）、每个顶点 10/20/40/41/42 [文档] | `add_polyline{vertices:[{x,y,bulge?,start_width?,end_width?}],closed}`。bulge = tan(包含角/4)，**负值表示顺时针**，1 表示半圆 [文档] |
| RECTANG | 生成 4 顶点闭合 LWPOLYLINE；有倒角/圆角/宽度/面积/旋转选项 [文档-未核] | `LWPOLYLINE` 70=1 | `add_rect{corner1,corner2,rotation_deg?,fillet_r?}` → 闭合 polyline（圆角用 bulge 表示） |
| OFFSET | 距离 / Through / Erase（默认 No）/ Layer（Source 或 Current）；`OFFSETGAPTYPE` 默认 0；**偏移方向靠鼠标点选** [文档] | 生成新实体（同类型） | `offset{handle,distance,side:"left"|"right"}`（相对于实体方向；闭合轮廓用 `inward/outward`）。ezdxf 只提供顶点级的 `offset_vertices_2d`：正值偏向行进方向**左侧**（CCW 多边形即向内，见 E4） |
| TRIM / EXTEND | Quick 模式（所有对象都是剪切边，点到不相交的对象会直接删除）/ Standard 模式（先选剪切边）；`TRIMEXTENDMODE` 切换；Shift 键在两者间切换 [文档] | 修改或拆分实体（可能生成新句柄） | `trim{target,cutting_edges[]|"all",keep_point|segment_param}`。**禁止 Quick 模式“点空就删除”这种隐式行为**，必须显式指定。返回 `{modified[],created[],deleted[]}` |
| FILLET / CHAMFER | 半径存在 `FILLETRAD`；`TRIMMODE` 控制是否修剪；半径 0 时把两线延伸或修剪到交点 [文档]；FILLETRAD 默认 0、TRIMMODE 默认 1 [推断，未从官方页面确认] | 新增 ARC，修改原线段 | `fillet{a,b,radius,trim:true}`，半径必填，不依赖会话状态 |
| MIRROR | 是否删除源对象（默认不删）；`MIRRTEXT` 控制文字是否镜像：**默认 0，即保持可读** [第三方/Graebert/Arkance 文档]；**冲突**：旧版 ActiveX/.NET 开发文档写“默认 On(1)” [文档]。块内文字不受 MIRRTEXT 影响 | 圆/弧镜像后可能变成 extrusion=(0,0,-1)（见 E3） | `mirror{handles,axis:[p1,p2],keep_source:true,mirror_text:false}`；运行时自己实现“文字保持可读”（翻转对齐方式），**不要直接用 ezdxf 的 transform**（它会把文字变成反字） |
| ARRAY | ARRAYRECT/POLAR/PATH；`ARRAYASSOCIATIVITY` 默认 On，此时生成关联阵列对象（类似块）[文档] | 关联阵列 = 匿名块加关联对象 [推断] | `array_rect{handles,rows,cols,dx,dy}` 默认**生成独立副本（非关联）**，便于用句柄逐个引用 |
| MOVE/COPY/ROTATE/SCALE | 基点 + 位移/角度/比例；ROTATE 正角为逆时针 [文档-未核] | 改坐标，COPY 产生新句柄 | `transform{handles,op:"move"|"rotate"|"scale",...}`；SCALE 只允许等比（ezdxf 对 CIRCLE/ARC 做非等比缩放会抛 `NonUniformScalingError`，见 E4） |
| DIMLINEAR / DIMALIGNED / DIMRADIUS / DIMDIAMETER / DIMANGULAR | 组码 70 低位为类型：0 旋转/水平/垂直，1 对齐，2 角度，3 直径，4 半径，5 三点角度，6 坐标；+32 表示块只被本标注引用，+64 坐标 X 型，+128 文字已移动；组码 2 指向匿名块（`*Dn`）；**42 = 实际测量值（只读）**；1 = 文字覆盖（空或 `<>` 表示显示测量值，单个空格表示不显示）[文档]。注意 6=2+4，不能用位掩码判断半径型 [论坛] | 见 E1/E4 | `add_dim{kind,points,style}` → 存储定义点，**由运行时重新生成块，并写入 42**；`DIMASSOC=2` 的关联（反应器/ACAD_DIMASSOC）在第一阶段**不支持**，但需要显式声明 |
| LAYER | 颜色（ACI）、线型、线宽、冻结/锁定/打印；层名有非法字符 | `LAYER` 表 | `layer.set{name,color,linetype,locked,...}`；校验层名（ezdxf 对 `<` 等字符抛 `DXFValueError`） |
| BLOCK / INSERT / ATTDEF | 块有基点；INSERT 有插入点、比例 41/42/43、旋转 50；带属性时 66=1，后面跟 ATTRIB…SEQEND [文档-未核] | `BLOCK_RECORD` + `BLOCK` + `INSERT` | `define_block{name,base,entities}` / `insert{name,at,scale,rotation_deg,attribs:{TAG:value}}`；**校验块已定义**（ezdxf 允许引用不存在的块） |
| 单位 | `$INSUNITS`（组码 70）：0 无单位、1 英寸、2 英尺、4 毫米、5 厘米、6 米……21–24 为美国测量制单位；`$MEASUREMENT`：0 英制、1 公制（只影响填充图案和线型文件选择）[文档] | 头部变量 | 文档创建时**必须显式给出单位**，不要依赖默认值（ezdxf 默认 6=米，AutoCAD 默认值取决于模板 [推断]） |
| UCS/WCS/OCS | 2D 实体（CIRCLE/ARC/LWPOLYLINE/TEXT/INSERT 等）的坐标存在 OCS 中，OCS 由 extrusion（210）经任意轴算法得到：若 \|Nx\|<1/64 且 \|Ny\|<1/64，则 Ax = Wy×N，否则 Ax = Wz×N，再归一化；Ay = N×Ax [文档]。LINE 用 WCS | 210/220/230 | 对外 API **只暴露 WCS 2D 坐标**；内部遇到 extrusion≠(0,0,1) 时先转换为 WCS（并考虑归一化回 +Z）再暴露 |

### 2.4 与公开文档对照
- DIMENSION 组码与 70 的位含义：与 Autodesk DXF 2024 “Common Dimension Group Codes” 一致 [文档]。ezdxf 生成的线性标注 70=32（类型 0 + 位 32），符合规范；但 **ezdxf 的 `add_aligned_dim` 写出的类型是 0（旋转型 + 角度），不是 1**（实测 E4）。
- bulge 定义：与 Autodesk VERTEX 组码 42 文档一致，实测 `bulge_to_arc` 符合（E5）。
- MIRRTEXT 默认值：不同 Autodesk 文档互相矛盾（见上），需在真 AutoCAD 上确认，目前为 [未知]。

### 2.5 已确认事实 / 推断 / 未知
- 确认：DXF 中的弧角度是“度、逆时针、OCS”；API 层是弧度；bulge 正值为逆时针；42 只读；`$INSUNITS` 编码表；任意轴算法。
- 推断：AutoCAD 读 DXF 时会根据定义点和标注样式重新生成标注块，并且 42 不是必需的（文档标注为 optional）。
- 未知：AutoCAD 打开“42 缺失 / 块与定义点不一致”的 DXF 时是否会自动重算块（需要真机验证）；FILLETRAD/TRIMMODE 当前默认值；MIRRTEXT 当前默认值。

### 2.6 对 Agent-native 架构的启发
- 所有“靠鼠标点选决定语义”的地方（OFFSET 方向、TRIM 保留哪段、FILLET 选哪一侧）都改成**显式参数**。
- 所有系统变量状态（FILLETRAD、TRIMMODE、MIRRTEXT、OFFSETGAPTYPE、ARRAYASSOCIATIVITY）都改成 **op 的必填参数或带文档说明的默认值**，运行时不保留隐式会话状态。
- 每个修改类 op 返回 `{created, modified, deleted}` 三组句柄，方便 agent 继续引用。

### 2.7 可转化为实现与自动化测试的项
- T2.1 弧角度归一化：(-90,450)→(270,90)；(370,10)→(10,10) 视为非法（零跨度）还是整圆，需定义并测试。
- T2.2 bulge：`(0,0)->(10,0), bulge=1` 的圆心为 (5,0)、r=5，弧经过 (5,-5)（E5 已验证）。
- T2.3 镜像：水平轴镜像后 ARC 的 WCS 起点/终点正确，且 extrusion 被规范回 +Z。
- T2.4 OFFSET：正方形向内偏 1 得到 (1,1)…(9,9)（E4 已验证 ezdxf 的原语）。
- T2.5 标注：线性标注 42 写入值 == 定义点投影距离；修改定义点后块文字必须更新（ezdxf 默认**不会**更新，见 E4）。
- T2.6 层名校验、块存在性校验、半径 >0、坐标有限（拒绝 NaN）。

---

## 3. DXF 格式

### 3.1 研究目标和测试环境
确认 DXF 结构、句柄、关键实体组码、表、XDATA/字典、版本、精度、兼容性陷阱，作为运行时持久化格式的依据。实测环境：ezdxf 1.4.5、Python 3.12.10。

### 3.2 版本/工具/授权前提
DXF Reference 是 Autodesk 公开文档，可以免费阅读。ezdxf 采用 MIT 许可。实测只覆盖 ASCII DXF（`ezdxf.recover` 只支持 ASCII DXF [文档]）。

### 3.3 输入、步骤、实际输出
见第 5 节 E1/E3。关键观察摘录：
- 文件结构：`HEADER → CLASSES → TABLES → BLOCKS → ENTITIES → OBJECTS`。在 47 KB 的示例文件中，ENTITIES 只占 75%–78% 这一段，HEADER 和 TABLES 占了大部分体积（E2 字节偏移）。
- 原始组码（E1，R2010 / AC1024）：
  - `LINE`: `0:LINE | 5:8B | 330:17 | 100:AcDbEntity | 8:WALL | 100:AcDbLine | 10/20/30 | 11/21/31`
  - `CIRCLE`: `... 100:AcDbCircle | 10/20/30 | 40:25.0`
  - `ARC`: `... 100:AcDbCircle | 10/20/30 | 40 | 100:AcDbArc | 50:-90.0 | 51:450.0`（**原样保留了非规范角度**）
  - `LWPOLYLINE`: `100:AcDbPolyline | 90:3 | 70:0 | 10:0.0 | 20:0.0 | 42:1.0 | 10:10.0 | 20:0.0 | ...`（bulge 紧跟在所属顶点之后）
  - `TEXT`: `100:AcDbText | 10/20/30 | 40:2.5 | 1:'Hello 中文' | 50:30.0 | 11/21/31 | 100:AcDbText`（子类标记 AcDbText 出现**两次**，这是规范要求）
  - `DIMENSION`: `100:AcDbDimension | 280:0 | 2:*D1 | 3:EZDXF | 10 | 11 | 70:32 | 71:5 | 1:<> | 100:AcDbAlignedDimension | 13 | 14 | 50:0.0 | 100:AcDbRotatedDimension`，**没有 42**。

### 3.4 与公开文档对照
| 项 | 公开文档 | ezdxf 实测 |
|---|---|---|
| 段 | HEADER/CLASSES/TABLES/BLOCKS/ENTITIES/OBJECTS/THUMBNAILIMAGE（可选）；R2013+ 还有 ACDSDATA（参考手册未记载）[文档/ezdxf 文档] | 一致 |
| 句柄 | 组码 5，十六进制字符串；`$HANDSEED`（组码 5）是“下一个可用句柄”；330 为所有者软指针 [文档] | 一致；**句柄单调递增，删除后不复用**；内存中的 `$HANDSEED` 在保存前不更新（显示 100，保存后为 AE）|
| 版本 | AC1009=R11/R12、AC1012=R13、AC1014=R14、AC1015=2000、AC1018=2004、AC1021=2007、AC1024=2010、AC1027=2013、AC1032=2018 [文档] | `new()` 支持 AC1009/1015/1018/1021/1024/1027/1032 |
| 精度 | AutoCAD 另存为 DXF 时可选 0–16 位小数 [文档] | ezdxf 用 `repr` 写浮点：`0.30000000000000004`、`123456789.12345679`，**可精确往返**（最多 17 位有效数字）|
| 编码 | R2007+ 用 UTF-8；更早版本用 `$DWGCODEPAGE` 和 `\U+XXXX` 转义 [文档-未核] | R2010 写 UTF-8 字节；在 Windows 上换行是 **CRLF** |
| XDATA | 1001 应用名（须在 APPID 表注册）、1000 字符串 ≤255 字节、1002 `{`/`}`、1040 实数、1070/1071 整数 [文档]；单实体约 16 KB 上限 [ezdxf 文档] | **ezdxf 不检查 APPID 是否注册，也不检查 16 KB 上限，audit 也不报** |
| 字典/XRECORD | OBJECTS 段的根字典下挂命名字典，XRECORD 存任意组码 [文档-未核] | 自定义 `AGENTCAD_META/RUN` 往返正常 |
| DIMASSOC | 0 分解、1 非关联、2 关联 [文档] | ezdxf 头部 `$DIMASSOC=2`，但**不写反应器和 DIMASSOC 对象**（实际是非关联的）|

### 3.5 已确认事实 / 推断 / 未知
- 确认（实测）：句柄在保存/重载后保持稳定；浮点精确往返；XDATA/XRECORD 往返；R12 不支持 LWPOLYLINE/MTEXT（ezdxf 抛 `DXFVersionError`）。
- 确认（实测）：**直接改 `doc.dxfversion="R12"` 再保存，会静默丢掉 LWPOLYLINE（模型空间变空，只打一条日志警告）**；应改用 `ezdxf.addons.r12export`，它会转成 `POLYLINE`。
- 推断：AutoCAD 2019–2026 仍写 AC1032（DXF 2018 格式）[推断，需核对]。
- 未知：AutoCAD 对 ezdxf 写出的、缺少 42 的 DIMENSION 的具体处理；AutoCAD 对超过 16 KB XDATA 的具体行为。

### 3.6 对 Agent-native 架构的启发
- **默认目标版本为 R2010（AC1024）或 R2018（AC1032）**，不支持写 R12（或只通过 r12export 导出）。
- **确定性输出**：ezdxf 每次写入都会生成新的 `$FINGERPRINTGUID/$VERSIONGUID` 和时间戳，所以两次相同构建的字节不同；设置 `ezdxf.options.write_fixed_meta_data_for_testing=True` 后字节一致（E3）。golden 测试还要统一换行符（CRLF/LF）。
- **元数据存储**：运行时元数据（schema 版本、op 日志 ID、checkpoint）放在 `AGENTCAD_*` 命名字典的 XRECORD 中；单实体标签放 XDATA（应用名 `AGENTCAD`，必须在 APPID 表注册，控制在 16 KB 以内，由运行时自己校验）。
- 自己实现 audit/validate 层，因为 ezdxf 的 audit 对未定义的层或 APPID 都不报错。

### 3.7 可转化为实现与自动化测试的项
- T3.1 golden 文件：固定元数据加 LF 规范化，生成后比较哈希。
- T3.2 往返测试：每类实体写入 → 读回 → 属性逐项相等（浮点按精确相等）。
- T3.3 版本矩阵：同一个 op 序列分别保存为 AC1015/1024/1032，读回后实体数一致。
- T3.4 XDATA 上限：超过 16 KB 或 APPID 未注册时，运行时返回 `E_XDATA_INVALID`。
- T3.5 降级导出：若导出 R12，断言 LWPOLYLINE 被转成 POLYLINE 而不是丢失。

---

## 4. DWG

### 4.1 研究目标和测试环境
评估 DWG 读写的可行性和授权风险。环境中没有任何 DWG 工具（无 AutoCAD、无 ODA File Converter、无 LibreDWG）。

### 4.2 版本/工具/授权前提
| 来源 | 性质 | 授权 |
|---|---|---|
| Autodesk | **没有公开 DWG 规范** [LoC 文档] | RealDWG SDK 需商业授权 [推断] |
| ODA “Open Design Specification for .dwg files” v5.4.1 | 逆向工程得到的公开规范，覆盖 R13 至 2018（AC1032）[文档] | 可免费下载 PDF |
| ODA File Converter | 免费下载；**非 ODA 会员仅限非商业用途**；ODA 不再分发旧版本 [文档] | 商业产品集成有风险 |
| LibreDWG（GNU） | 读取 r1.2–r2018，号称约 99%；默认只写 r2000，r2004+ 写入需打补丁，r2007 写入未实现 [文档] | **GPLv3+**，与闭源或宽松许可分发存在冲突 |
| ezdxf `odafc` 插件 | 调用外部 ODA File Converter 进程完成 DWG↔DXF 转换 [实测：模块存在，`is_installed()==False`] | 继承 ODA 的授权限制 |

### 4.3 输入、步骤、实际输出
没有可用的 DWG 工具，状态为 BLOCKED。只验证了 `ezdxf.addons.odafc` 可以导入，但转换器未安装。

### 4.4 与公开文档对照 / 4.5 已确认事实·推断·未知
- **公开规范**：ODA 5.4.1 PDF（逆向工程，非官方）。
- **观察**：无（没有工具）。
- **推断**：AutoCAD 2018 起 DWG 格式版本仍是 AC1032；新功能多以新对象类的形式加入，而不是改变格式版本。
- **未知**：DWG 2018 之后的未公开对象细节；Autodesk 的“TrustedDWG”校验对第三方写出文件的具体影响；ODA 规范与实际 AutoCAD 输出的差距。

### 4.6 对 Agent-native 架构的启发
- **核心格式只用 DXF**。DWG 作为可选的外部转换器插件（ODA File Converter），并在产品中明确提示授权限制。**不链接 LibreDWG**（GPL 传染）。
- 转换插件采用“外部进程 + 超时 + 校验转换结果”的模式，失败时返回 `E_CONVERTER_UNAVAILABLE`。

### 4.7 可转化为实现与自动化测试的项
- T4.1 转换器检测：未安装时 CLI/MCP 返回结构化错误，而不是抛出异常栈。
- T4.2 （有许可环境时）DWG→DXF→DWG 往返后，实体数和句柄集合一致。

---

## 5. ezdxf 可复现实验（已实际运行）

### 5.1 研究目标和测试环境
- 目标：把第 1–3 节的格式事实落到参考实现上，并找出 ezdxf 与 AutoCAD 语义不一致、会让实现者意外的地方。
- 环境：Windows 11 Home 10.0.26200；Python 3.12.10；uv 0.12.16；临时 venv（scratchpad `research/.venv`）；`ezdxf==1.4.5`、`numpy==2.5.4`、`fonttools==4.67.0`。

### 5.2 版本/工具/授权前提
ezdxf 1.4.5（MIT）。不需要 AutoCAD。复现方法：
```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/Scripts/python.exe ezdxf==1.4.5
# exp02 依赖 exp01 在同一输出目录生成的 exp01_r2010.dxf
for f in exp01_roundtrip exp02_errors_recover exp03_semantics exp04_dims_blocks_ops; do
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -I docs/research/experiments/$f.py <outdir>; done
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -I docs/research/experiments/exp05_angles_bulge.py
```

### 5.3 E1 写 R2010 → 保存 → 重载（`exp01_roundtrip.py`）
核心代码：
```python
doc = ezdxf.new("R2010", setup=True); msp = doc.modelspace()
msp.add_arc((0, 0), radius=10, start_angle=-90, end_angle=450)
msp.add_lwpolyline([(0, 0, 0, 0, 1.0), (10, 0, 0, 0, 0), (10, 10)], format="xyseb")
d1 = msp.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(100, 0), dimstyle="EZDXF"); d1.render()
d2 = msp.add_radius_dim(center=(50, 50), radius=25, angle=45, dimstyle="EZ_RADIUS"); d2.render()
doc.saveas(fn); doc2 = ezdxf.readfile(fn)   # 再按句柄 doc2.entitydb.get(h) 比对
```
实际输出（节选，全文见 `outputs/exp01.txt`）：
```
ezdxf 1.4.5 | new() acadver: AC1024 R2010
header defaults: $INSUNITS= 6 $MEASUREMENT= 1 $LUNITS= 2 $AUNITS= 0 $ANGBASE= 0.0 $ANGDIR= 0 $DIMASSOC= 2 $MIRRTEXT= 1
handles before save: {'line': '8B', 'circle': '8C', 'arc': '8D', 'arc2': '8E', 'lwpoly': '8F', 'text': '90', 'mtext': '91', 'dimlin': '92', 'dimrad': 'A1'}
$HANDSEED before save: 100
arc dxf angles as stored: -90.0 450.0 | 370.0 10.0
dimlin: geometry block = *D1  actual_measurement(42) = None  get_measurement() = 100.0
bulge_to_arc(start=(0,0), end=(10,0), bulge=1) -> center=(5.0, 0.0), start_angle(rad)=3.141593, end_angle(rad)=0.000000, r=5.0
saved exp01_r2010.dxf size 47110 bytes; $HANDSEED after save: AE
reload line    handle   8B -> LINE      (... 所有 9 个句柄重载后类型一致 ...)
reloaded acadver: AC1024  $HANDSEED: AE  $INSUNITS: 6
reloaded arc angles: -90.0 450.0
reloaded dimlin 42: None  block: *D1  block exists: True  block entity types: ['INSERT', 'LINE', 'MTEXT', 'POINT']
reloaded text: 'Hello 中文'  insert: (5.0, 5.0, 0.0)  rotation: 30.0
```
结论：句柄稳定 ✔；42 **未写入** ✘；弧角**不归一化**；`$INSUNITS` 默认 **6（米）**；`$MIRRTEXT` 默认 1；标注块由 POINT/LINE/MTEXT/INSERT（箭头块）组成；中文以 UTF-8 正确往返。

### 5.4 E2 错误与恢复（`exp02_errors_recover.py`）
```
[readfile missing] builtins.FileNotFoundError: [Errno 2] No such file or directory
[readfile garbage] builtins.OSError: File 'out\garbage.dxf' is not a DXF file.
[readfile empty]   builtins.OSError: File 'out\empty.dxf' is not a DXF file.
[readfile trunc 30%] ezdxf.lldxf.const.DXFStructureError: DXFStructureError: missing ENDSEC tag.   (60%/95% 同)
[recover trunc 30%] OK -> recovered: ver=AC1024 msp_entities=0 ... auditor.errors=0 fixes=0 has_errors=False
[recover trunc 95%] OK -> recovered: msp_entities=9 types=['ARC','CIRCLE','DIMENSION','LINE','LWPOLYLINE','MTEXT','TEXT'] errors=0
[recover garbage] ezdxf.lldxf.const.DXFStructureError: Invalid group code "this is not a dxf file" at line 1.
[audit undefined layer] errors: 0 fixes: []      layer now in table?: False
[layers.add('A<B')] ezdxf.lldxf.const.DXFValueError: Invalid value A<B for attribute "name" in entity LAYER(#None).
[add_circle radius=-1] OK -> -1.0
[add_line zero length] OK -> 32
[add_line with NaN] OK -> (nan, 0.0, 0.0)
section HEADER 0% / CLASSES 15% / TABLES 16% / BLOCKS 66% / ENTITIES 75% / OBJECTS 78%
[readfile trunc mid-ENTITIES] DXFStructureError: missing ENDSEC tag.
[recover trunc mid-ENTITIES] OK -> msp entities=0 handles=[] errors=0 fixes=0 objects-section dict ok=True
entitydb has 8B (LINE)? False
```
结论：
- 异常类型**不统一**：垃圾或空文件抛 `OSError`（**不是** `DXFError` 的子类），结构损坏抛 `DXFStructureError(DXFError)`，属性非法抛 `DXFValueError(DXFError, ValueError)`。
- **`recover` 会静默丢弃不完整的段**：在 ENTITIES 中间截断时，截断点之前 5 个完整实体也全部丢失，而 `auditor.has_errors == False`。截断发生在 OBJECTS 段时实体全部保留。
- ezdxf 不做几何校验：负半径、NaN、零长度线都会被接受。

### 5.5 E3 语义细节（`exp03_semantics.py`）
```
raw LINE coordinate tags: AcDbLine| 10|0.30000000000000004| 20|3.141592653589793| 30|0.0| 11|123456789.12345679| 21|0.3333333333333333|
float round-trip exact: True
handle deleted=2F, next new=30, reused=False
copy() handle before add: assigned on add -> 31 (orig 30)
mirrored ARC: center (10.0, 0.0, 0.0) extrusion (0.0, 0.0, -1.0) angles 0.0 90.0
  ARC WCS start/end points: [(-15.0, 0.0, 0.0), (-10.0, 5.0, 0.0)]
mirrored TEXT: insert (10.0, 0.0, 0.0) rotation 0.0 text_generation_flag(71) None extrusion (0.0, 0.0, -1.0)
OCS(0,0,-1) ux,uy,uz = (-1.0, 0.0, 0.0) (0.0, 1.0, 0.0) (0.0, 0.0, -1.0) | to_wcs((15,0,0)) = (-15.0, 0.0, 0.0)
xdata round-trip: [DXFTag(1000, 'op:42'), DXFTag(1040, 3.14), DXFTag(1071, 7)]
xrecord round-trip: [DXFTag(1, 'schema=1'), DXFTag(40, 1.5), DXFTag(90, 12345)]
[set_xdata with unregistered appid] OK -> accepted
[audit >16KB xdata] OK -> no complaints
[R12 add_lwpolyline] DXFVersionError: LWPOLYLINE requires DXF R2000
[R12 add_mtext] DXFVersionError: MTEXT requires DXF R2000
  entities in downgraded R12 file: []          <- 改 dxfversion 降级：LWPOLYLINE 静默丢失
two identical builds byte-identical: False     <- 差异：两个 GUID + "1.4.5 @ <时间戳>"
with options.write_fixed_meta_data_for_testing=True byte-identical: True
audit unregistered appid: errors [] fixes [] | appid now registered: False
r12export -> AC1009 ['POLYLINE']
odafc (ODA File Converter) installed: False
```
结论：镜像（`transform(scale(-1,1,1))`）让 ARC、CIRCLE、TEXT 都变成 extrusion=-Z（OCS 坐标不变，WCS 结果正确）；TEXT 会变成反字，也就是**没有 MIRRTEXT=0 的语义**。

### 5.6 E4 标注、块与编辑原语（`exp04_dims_blocks_ops.py`）
```
EZDXF dimstyle dimlfac= 100.0 | Standard dimlfac= 1
aligned  : dimtype(70)=32 type&7=0 block=*D1 get_measurement()=50.0 42=None text(1)='<>'
diameter : dimtype(70)=35 type&7=3 block=*D2 get_measurement()=20.0 42=None
angular2l: dimtype(70)=34 type&7=2 block=*D3 get_measurement()=90.0 42=None
override dim text(1): L=<> mm | XDATA ACAD (DSTYLE): [1000 'DSTYLE', 1002 '{', 1070 271, 1070 2, 1002 '}']
rendered MTEXT inside dim block: 'L=1234.56 mm'          <- 实际长度 12.3456，被 DIMLFAC=100 放大
after moving p2 (group 14) to x=50 without re-render: get_measurement()= 50.0  block text still: 'L=1234.56 mm'
$DIMASSOC= 2 | dim reactors: None | ACAD_DIMASSOC objects: 0
INSERT attribs: [('NO', 'A-01', (101.4142, 98.5858, 0.0))]
virtual_entities (explode preview): ['ELLIPSE']           <- xscale=2,yscale=1 时圆被展开成椭圆
[delete block in use] DXFBlockInUseError: Block "TAG" is still in use.
[add_blockref undefined block] OK -> NOPE
[delete layer in use (doc.layers.remove)] OK -> removed
rotate90 then translate(5,0): line (5.0, 0.0, 0.0) (5.000000000000001, 10.0, 0.0)
[non-uniform scale CIRCLE.transform(scale(2,1,1))] NonUniformScalingError: CIRCLE/ARC does not support non uniform scaling
offset_vertices_2d square by 1 (closed): [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]
ezdxf has trim/extend/fillet API on entities?: False
doc.units setter: 4 | $MEASUREMENT unchanged: 1
```
结论：标注样式的覆盖值存在 XDATA `ACAD/DSTYLE`（271=DIMDEC）；标注块**不会自动重建**，`render()` 必须由运行时显式调用；TRIM、EXTEND、FILLET、CHAMFER、OFFSET 需要运行时自己实现；变换后会出现浮点噪声（`5.000000000000001`），比较几何时要带容差。

### 5.7 E5 角度与 bulge（`exp05_angles_bulge.py`）
```
ARC 50=-90 51=450:  stored=(-90.0,450.0) arc_angle_span_deg=180.000000
ARC 50=370 51=10:   stored=(370.0,10.0)  arc_angle_span_deg=360.000000   <- 模 360 相等 → 整圆
ARC 50=350 51=10:   arc_angle_span_deg=20.000000                       <- 跨 0° 正确
ARC 50=0   51=0:    arc_angle_span_deg=0.000000                        <- 完全相等 → 0（与上面 370/10 不一致）
ARC 50=0   51=360:  arc_angle_span_deg=360.000000
ARC 50=90  51=90.0000001: arc_angle_span_deg=0.000000                  <- 容差内视为 0
bulge=+1: center=(5.0, 0.0) r=5 start=180deg end=0deg   (总是从 start 逆时针到 end；弧在弦的下方)
bulge=-1: center=(5.0, -0.0) r=5 start=0deg end=180deg  (负 bulge 时 ezdxf 交换起止点)
bulge=+0.414214: center=(5.0, 5.0) r=7.071068 start=-135deg end=-45deg
arc_to_bulge(center=(0,0), 0, 90deg, r=1): ((1,0), (0,1), 0.414214)
```

### 5.8 与公开文档对照 / 已确认·推断·未知
- 与文档一致：bulge 定义、DIMENSION 70 位、`$INSUNITS` 编码、任意轴算法（OCS(0,0,-1) 的 x 轴为 (-1,0,0)）。
- 与 AutoCAD 预期不同（[实测]，AutoCAD 侧为 [推断]）：不写 42、不维护 DIMASSOC、`MIRRTEXT` 默认 1、`INSUNITS` 默认 6、`add_aligned_dim` 写成类型 0、弧角不归一化。
- 待用 AutoCAD 补测（BLOCKED）：①打开 E1 生成的 DXF，看标注是否保持 / 是否重算并写入 42；②负半径和 NaN 文件能否打开；③extrusion=-Z 的 ARC 再次保存后是否被规范化；④未注册 APPID 的 XDATA 是否被丢弃；⑤非规范弧角（-90/450）读入后的显示和保存值。

### 5.9 对 Agent-native 架构的启发 / 可转化项
见第 6 节。E1–E5 的脚本可以直接改成 pytest 用例（把 print 改成 assert），作为“参考实现行为基线”，ezdxf 升级时用来提示语义变化。

---

## 6. 设计启示清单（可直接进入实现）

1. **实体 ID = DXF 句柄**（十六进制字符串）。只增不复用；COPY、ARRAY、TRIM 拆分会产生新句柄，op 结果必须返回 `{created, modified, deleted}`。块定义内的实体也有自己的句柄。
2. **事务性 op batch + checkpoint**：`begin → ops[] → validate → commit | rollback`。checkpoint 实现为内存快照（序列化后的 DXF 字节或 entitydb 深拷贝）。batch 等价于 UNDO BEgin/End，checkpoint 等价于 UNDO Mark/Back。失败时回滚到 batch 前的状态（不能依赖 ezdxf，它没有 undo）。
3. **结构化错误码**（参考 ObjectARX ErrorStatus）：`E_INVALID_INPUT`（含字段路径，例如 radius≤0、NaN、零跨度弧、零长度线）、`E_NOT_FOUND`、`E_ERASED`、`E_NAME_INVALID`（层名或块名）、`E_UNDEFINED_REFERENCE`（未定义的层/块/线型/APPID）、`E_IN_USE`（删除仍被使用的层或块）、`E_UNSUPPORTED_VERSION`、`E_FILE_NOT_DXF`、`E_FILE_CORRUPT`、`E_PARTIAL_RECOVERY`、`E_CONVERTER_UNAVAILABLE`。**统一包装 ezdxf 的 `OSError`、`DXFStructureError`、`DXFValueError`、`DXFVersionError`、`NonUniformScalingError`、`DXFBlockInUseError`。**
4. **显式单位**：创建文档时 `units` 必填（写 `$INSUNITS`，并同步 `$MEASUREMENT`：公制单位写 1、英制写 0）；绝不依赖 ezdxf 默认的 6（米）。不提供隐式单位换算，换算时用 `ezdxf.units.conversion_factor` 显式计算。
5. **角度约定**：对外 API 统一用**度、逆时针、相对 WCS +X**；存储前把弧角归一化到 [0,360)，并拒绝零跨度；明确规定“起止角模 360 相等”时的语义（建议拒绝，整圆请用 CIRCLE）。内部和 ActiveX 风格接口不出现弧度。
6. **只暴露 WCS 2D**：读入 extrusion≠+Z 的实体时转换到 WCS；镜像操作由运行时实现，保证结果 extrusion=+Z，并实现“文字保持可读”（等价于 MIRRTEXT=0），不要直接调用 `entity.transform(mirror)`。
7. **标注 = 定义点（真值）+ 存储测量值 + 可再生块**：每次创建或修改后由运行时调用 `render()` 重建 `*Dn` 块，并**自行写入组码 42**（ezdxf 不写）。不要使用 ezdxf `setup=True` 自带的 `EZDXF` 样式（DIMLFAC=100），应自建 `AGENTCAD` 标注样式（DIMLFAC=1）。第一阶段明确声明“非关联标注”（等价于 DIMASSOC=1 的语义）。
8. **几何与引用校验层**：在 ezdxf 之上自己实现 validate：有限坐标、半径>0、层名、块和层存在、APPID 已注册、XDATA ≤16 KB、R2000 以下版本的实体兼容性。ezdxf 的 audit 不覆盖这些。
9. **加载策略**：先用 `ezdxf.readfile`，失败后再用 `recover.readfile`；**恢复后比较各段实体数和句柄集合**。如果检测到不完整的段（例如 ENTITIES 缺少 ENDSEC），即使 `auditor.has_errors==False` 也要返回 `E_PARTIAL_RECOVERY` 警告，不能把空模型空间当作成功。
10. **确定性输出**：测试和 golden 文件统一使用 `write_fixed_meta_data_for_testing=True`，并把换行规范为 LF（或固定 CRLF）；正式输出允许 GUID 和时间戳变化，但 diff 工具应忽略这些字段。
11. **版本策略**：默认写 AC1024（R2010）；R12 只通过 `ezdxf.addons.r12export` 导出，禁止直接修改 `doc.dxfversion`（会静默丢实体）。
12. **元数据**：运行时元数据放在根字典 `AGENTCAD_*` 下的 XRECORD 中；实体级标签放 XDATA `AGENTCAD`（启动时注册 APPID）。
13. **编辑算法自研**：OFFSET、TRIM、EXTEND、FILLET、CHAMFER 在 ezdxf 中没有实体级 API，需要基于 `ezdxf.math`（`bulge_to_arc`、`offset_vertices_2d`、`ConstructionArc` 等）自行实现。所有交互式拾取语义都改成显式参数（side、keep 段、radius、trim）。
14. **浮点比较**：结果比较用容差（变换后会出现 `5.000000000000001`）；存储保持 IEEE double 原值，ezdxf 已能精确往返。
15. **DWG**：不进核心。可选插件调用 ODA File Converter（非会员仅限非商业用途），避免 GPL 的 LibreDWG；缺少转换器时返回结构化错误。

---

## 7. 参考链接

Autodesk（官方）
- DXF 通用标注组码（2024）：https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-DXF/files/GUID-EDD54EAC-A339-4EBA-AEA6-EC8066505E2B.htm
- DXF HEADER 变量（2021）：https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-DXF/files/GUID-A85E8E67-27CD-4C59-BE61-4DC9FADBE74A.htm
- LWPOLYLINE（2020）：https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-DXF/files/GUID-748FC305-F3F2-4F74-825A-61F04D757A50.htm
- VERTEX（bulge 定义，2020）：https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-DXF/files/GUID-0741E831-599E-4CBF-91E1-8ADBCFD6556D.htm
- 任意轴算法（2018）：https://help.autodesk.com/cloudhelp/2018/ENU/AutoCAD-DXF/files/GUID-E19E5B42-0CC7-4EBA-B29F-5E1D595149EE.htm
- 扩展数据组码（2018）：https://help.autodesk.com/cloudhelp/2018/ENU/AutoCAD-DXF/files/GUID-A2A628B0-3699-4740-A215-C560E7242F63.htm
- 持久句柄（2020）：https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-DXF/files/GUID-582ECC55-155A-48CC-A8B1-7D75FDF4ECC9.htm
- AutoLISP handent：https://help.autodesk.com/cloudhelp/2015/ENU/AutoCAD-AutoLISP/files/GUID-AF6DD533-1A24-4687-96EB-F03F26050C07.htm
- AutoLISP 对象操作概述：https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-AutoLISP/files/GUID-9AED35A1-5CB2-43D8-88ED-CBE95E54798D.htm
- ActiveX AddArc（弧度）：https://help.autodesk.com/cloudhelp/2016/JPN/AutoCAD-ActiveX/files/GUID-864A7E1F-D221-4C83-A4DB-F60C8E56FED6.htm
- .NET 事务：https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-NET/files/GUID-50FD6118-B2D1-4313-A7D6-830794DFDEFA.htm
- .NET 创建 Arc：https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-NET/files/GUID-EF4D9742-F41F-48E1-BDDC-235069C52176.htm
- ObjectARX 删除对象 / eWasErased：https://help.autodesk.com/cloudhelp/2018/CHS/OARX-DevGuide/files/GUID-B9E3225A-675F-4802-9DD0-928EA1C7917A.htm
- AutoCAD Core Console（2025）：https://help.autodesk.com/view/OARX/2025/ENU/?guid=AUTOCAD_CORE_CONSOLE
- UNDO：https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-LT/files/GUID-2729A466-B199-4840-B92B-4D8A38A8ADB8.htm
- TRIM：https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-LT/files/GUID-B1A185EF-07C6-4C53-A76F-05ADE11F5C32.htm
- FILLET：https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-LT/files/GUID-64F8B700-23B3-4BD6-8C03-66121AA13E8F.htm
- OFFSET：https://help.autodesk.com/cloudhelp/2018/ENU/AutoCAD-LT/files/GUID-C0E4246D-C420-42BD-A6FC-8B1852EFD005.htm ；Autodesk 博客：https://www.autodesk.com/blogs/autocad/autocad-offset-options-tuesday-tips-with-frank/
- ARRAYRECT：https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-BB3DA888-0C3A-4C68-A3ED-E0E528781205.htm
- 镜像（ActiveX，写“MIRRTEXT 默认 On”）：https://help.autodesk.com/cloudhelp/2019/ENU/AutoCAD-ActiveX/files/GUID-C671B30A-0596-4114-A7F3-517FC7AABD6B.htm ；LT 2021“默认不反转文字”：https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-LT/files/GUID-54B774E9-EDB1-468D-8F5C-4A1B010F173A.htm
- SAVEAS DXF 精度 0–16：https://help.autodesk.com/cloudhelp/2018/ENU/AutoCAD-LT/files/GUID-E2CEA3F2-43CA-41D0-A2C6-BACF2229715A.htm

第三方 / DWG
- MIRRTEXT 默认 0（Graebert ARES）：https://onlinehelp.graebert.com/EN/ARESCMD/26/sysvar/sv_mirrtext.htm
- ODA DWG 规范 5.4.1：https://opendesign.com/files/guestdownloads/OpenDesign_Specification_for_.dwg_files.pdf
- ODA File Converter 使用条款：https://www.opendesign.com/node/3218
- 美国国会图书馆 DWG 格式说明：https://loc.gov/preservation/digital/formats//fdd/fdd000445.shtml
- LibreDWG 手册：https://www.gnu.org/software/libredwg/manual/html_node/Overview.html
- DIMENSION 70 位掩码陷阱（CADTutor）：https://www.cadtutor.net/forum/topic/56211-dimension-type

ezdxf
- 单位：https://ezdxf.readthedocs.io/en/stable/concepts/units.html
- recover：https://ezdxf.readthedocs.io/en/stable/drawing/recover.html
- OCS：https://ezdxf.readthedocs.io/en/stable/concepts/ocs.html
- 文件结构：https://ezdxf.readthedocs.io/en/stable/dxfinternals/filestructure.html
- 句柄：https://ezdxf.readthedocs.io/en/stable/dxfinternals/handles.html
- 自定义数据（XDATA 16 KB）：https://ezdxf.readthedocs.io/en/stable/tutorials/custom_data.html
