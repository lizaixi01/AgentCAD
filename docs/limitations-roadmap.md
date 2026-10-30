# 已知限制、依赖与路线图

## 依赖

| 依赖 | 许可证 | 用途 | 说明 |
|---|---|---|---|
| ezdxf ≥1.3,<2（实测 1.4.5） | MIT | DXF 读写、标注渲染、范围计算 | 核心依赖 |
| mcp ≥1.20,<2（实测 1.30.0） | MIT | MCP 服务器 | 2.x API 不兼容，故固定 1.x |
| pypdf ≥4（实测 6.21） | BSD-3 | PDF 文字提取 | |
| Pillow ≥10 | MIT-CMU | SVG 导出（ezdxf drawing 插件需要）、图片预览 | 核心依赖（uvx/pipx 直接安装也能导出 SVG）；`[preview]` extra 保留以兼容旧命令 |

| FreeCAD 1.1（可选，实测 1.1.4） | LGPL-2.1+ | 三维参数化零件（`.FCStd`）的几何内核 | 独立进程运行（`backends/freecad.py`），不链接；见 [part-3d.md](part-3d.md) |
| CadQuery ≥2.3（可选，实测 2.8.0） | Apache-2.0 | `run_script` 用 CadQuery 脚本建三维零件 | `[cadquery]` extra；在 AgentCAD 自己的解释器的子进程里运行，实体以 BREP 交给 FreeCAD |

核心不依赖 AutoCAD、ODA、FreeCAD，也不调用任何模型 API。**可选**：安装了 AutoCAD 时（自动发现，或设置 `AGENTCAD_ACCORECONSOLE`），可以启用 DWG 导入/导出和 AutoCAD AUDIT（`backends/autocad.py`，通过无头的 accoreconsole 运行）。

## 已知限制

1. **AutoCAD 验证范围**：已在 AutoCAD 2027（中文版，accoreconsole）中验证文件可读性、往返和 27 个编辑命令（见 [research/autocad-observations.md](research/autocad-observations.md)）。没有在 GUI 中目视检查，也没有覆盖其它 AutoCAD 版本或 LT 版。
2. **DWG**：只能通过可选的 AutoCAD 后端处理（需要用户自己的 AutoCAD 授权，每次转换约 3–4 秒）。没有 AutoCAD 时不支持。ODA File Converter 是专有软件，LibreDWG 是 GPL-3.0 且写入版本有限。
3. **约束**：没有联立求解器。`enforce` 逐条修改，冲突时拒绝保存，不会"尽量满足"。
4. **文档提取**：内置提取器是规则式的，只覆盖板件常见措辞，不认识的说法会被报告为缺失，而不是被猜测。复杂文档应由外部 Agent 理解后，通过引文核验路线提交。
5. **零件族**：规格编译器目前只支持矩形板 + 孔（四角、单孔）+ 圆角。其它零件需要用 `kind:"plan"` 或直接调用 `apply_operations`。
6. **规格修订与手工编辑的交互**：如果手工修改了带规格标签的实体，之后的 `revise_drawing` 会按规格把它覆盖回去（这是协调模式的设计）。未打标签的实体不受影响。
7. **R12 导出** 会丢失单位（R12 没有 `$INSUNITS`），结果中会给出警告。
8. **LibreOffice 渲染** 中看不到 MTEXT（标注数字、注释），这是第三方导入的差异，DXF 本身正确。
9. **标注样式**：内置工程标注主要使用 `AGENTCAD` 样式（按单位换算尺寸），可以读取外来图纸样式，但没有完整的 ISO/ANSI 标注样式库。
10. **并发**：使用操作系统锁实现单写者；长任务不会因超过 120 s 被抢锁，进程退出后锁自动释放。旧版 `lock` 标记保守拒绝，不能混用新旧运行时；外部编辑器仍需哈希冲突检查。见[运行边界](release-verification.md#http-and-long-running-writers)。
11. **字节级可复现**：几何和 handle 是确定的，但 DXF 头部的时间戳和 GUID 每次保存都会变（研究中 E 实验已确认），所以要用几何等价性来比较。
12. **AutoCAD 后端的运行条件**：工作目录必须能映射到纯 ASCII 路径（后端会自动退回系统临时目录）；只能从 Python 进程启动（在 Git Bash 中直接启动会挂起，原因未知）；后端不会修改 AutoCAD 的任何持久设置。

13. **图纸空间布局**：已能读取、编辑和校验（`layout` 参数），并能新建布局和视口（`create_layout`、`add_viewport`）（2026-10-28）。仍未处理：视口对模型的投影关系（不会自动判断图纸上的副本与模型是否一致，只会提醒去检查），以及外部参照的内容。
14. **动态块**：ezdxf 保存时丢弃 `ACDB_BLOCKREPRESENTATION_DATA`，动态块的参数化行为可能失效（AutoCAD 审核结果不变）。
15. **标注修改**：`modify` 已支持 DIMENSION 文字、高度、比例及数值公差，并重新渲染；线性/半径/直径公差可读回。角度/坐标公差尚不支持，ISO 配合查表仅覆盖已核验范围，见[工程工作流](engineering-workflows.md)。
18. **`run_script`**：默认关闭。静态检查加独立进程只防误操作，不是安全沙箱；开启后 Agent 等于能以当前用户身份运行受限的 Python。
16. **版面与制图规范不检查**：标注互相重叠、文字压线、轴类的台阶/倒角轮廓线等，验证器发现不了，需要出图目视检查（`examples/trials/render_png.py`）。
17. **字体**：新图默认 `gbenor.shx` + `gbcbig.shx`。没有安装这两个字体的 CAD 软件会做字体替换。

19. **三维零件**（2026-10-29）：一个零件一个 Body，没有装配；不能从三维生成二维工程图（预览图已有：`export_drawing` 的 png）；Agent 三维实验目前只有 BenchCAD Vision2Code 的 100 题试点（每题一次，见 [examples/benchcad/README.md](../examples/benchcad/README.md)），图纸到零件（T1）还没跑。详见 [part-3d.md](part-3d.md)。
20. **三维脚本与参考图比较**（2026-10-30）：`run_script` 可以用 CadQuery / FreeCAD Part 脚本建零件的基体，之后的操作建在它上面；基体本身不是特征树（`SCRIPT_BASE_SOLID` 警告，CADBench 会拒收），只能整段重跑脚本来改。和二维脚本一样默认关闭，检查只防误操作，不是沙箱。`export_drawing(..., reference=...)` 比较轮廓和轮廓里的边线（整体尺寸不比较），看不到任何视图都看不出的差别（空心内部、正面背后的壁厚）；参考图必须按预览的网格排法，且有大小上限（32 MB、2500 万像素、每格不超过 8:1，每格先缩到 1024 px）。Agent 实测见 [examples/benchcad/README.md](../examples/benchcad/README.md)。

## 路线图

- **三维**：从模型投影出二维工程图（DXF，接现有标注和出图）；装配；用 CADBench / BenchCAD 测 Agent，包括"CadQuery 脚本 + 参考图比较"这条路线和纯代码对照组的对比；参考图比较可加不按轮廓、保留整体尺寸的对齐方式。

- **实测暴露的问题**（[trials-report.md](trials-report.md)、[comparison-hard-tasks.md](comparison-hard-tasks.md)）：图纸空间读取、脚本出口和 DIMENSION 修改已实现；判断图纸副本与模型是否一致、标注重叠检测、保留动态块数据仍待补齐。历史实测保持原记录。
- **P1 收尾**：HATCH、MLEADER、坐标标注已实现；两线角度标注创建及更多 mirror/偏移的 AutoCAD 差分验证仍待补齐。
- **P2**：更多零件族（法兰、L 形支架、长圆孔、孔阵列图案）；ISO/ANSI 标注样式与图层标准模板；块属性模板库；批量处理多图纸的工具；增量读取（按 handle 范围或修改时间）；规格修订时检测"手工修改过的标签实体"并要求确认。
- **P3**：不依赖 AutoCAD 的 DWG 方案（ODA File Converter，许可证由用户自行确认）；为 mirror 作用于标注/椭圆、HATCH 等补充 AutoCAD 差分用例；联立约束求解（可评估 SolveSpace 求解库，GPL，需要隔离）；3D 与参数化建模。

## 实时 AutoCAD 会话（2026-10-29）

`autocad_live`（`backends/acad_live.py`）通过 COM 连接用户正在运行的 AutoCAD（Windows，需要 pywin32，在 AgentCAD 目录里 `pip install -e ".[live]"`）：打开图纸、在每次修改后重新载入（`AGENTCAD_LIVE_SYNC=1`）、缩放到实体，以及用 `pull` 把用户在 AutoCAD 里的修改作为一次普通变更提交（检查点、日志、差异、验证）。限制：

- 初期 GUI 验证曾停在 Autodesk 许可证/登录界面，COM 调用被拒绝（`RPC_E_CALL_REJECTED`）；遇到这种情况返回 `AUTOCAD_BUSY`，提示用户先处理 AutoCAD 中的对话框。后续已在登录后的 AutoCAD 2027 完成两张原生 DWG 转出 DXF 的实机复核：四套流程、12 次连续编辑同步通过，并覆盖回传、冲突与恢复，见[实验报告](comparison-native-dwg.md#实时编辑文件锁修复复核)。自动化回归仍使用模拟 COM 对象，其他 AutoCAD 版本尚未验证。
- `open` 新打开的 DXF 使用 AutoCAD 只读模式，避免 Windows 文件锁阻止 AgentCAD 原子替换；GUI 仍能编辑，用 `pull` 回传。用户已经以写入方式打开的文档不会被自动关闭或转换；保存或回传编辑后显式 `reload` 才会转为只读。
- AutoCAD 2027 只注册了带版本号的 ProgID（`AutoCAD.Application.26`），后端会从注册表中查找；可用 `AGENTCAD_ACAD_PROGID` 指定。
- AutoCAD 只持有它打开时读到的版本。运行时会记录这个版本（open / reload 时）；如果之后 Agent 又提交了修改，`pull` 会拒绝（`LIVE_CONFLICT`），除非 `force=true`（被覆盖的版本留在检查点里）。不是由运行时打开的图纸同样需要 `force`。
- `pull` 期间 AutoCAD 中的文档会先另存为临时 DXF，再关闭并从提交后的文件重新打开（保留视图）。如果提交失败，临时 DXF 保留下来（结果里的 `autocad_copy`），它就是 AutoCAD 当前打开的文档。视图恢复仅保留中心和缩放，不保证多视口、窗口位置或完整相机状态；非世界 UCS 下可能偏移。`reload` 可重载普通二维世界坐标系下仅含视图/窗口变化的未保存状态（`DBMOD` 8/16/24），避免恢复视图本身阻塞下一次编辑；图元、图层、变量、字段、未知修改及不支持的视图状态继续拒绝，除非显式传 `discard=true`。
- `command` 发送原始命令行，默认关闭（`AGENTCAD_ALLOW_LIVE_COMMANDS=1` 开启），其效果只在 AutoCAD 中，需要 `pull` 才会进入图纸。

## 行业库（2026-10-29）

`library` 类操作（`ops/library.py`，数据在 `stdlib.py`）和 `standard_library` 工具。限制：

- **P&ID**：24 个常用符号（ISO 10628 / ISA-5.1 风格），不是完整符号库；单个符号插入不自动连接设备。`draw_pid` 工作流已支持命名端口连接和管线编号，`read_engineering` 从保存几何重建连通性并检查断连；不是完整管道等级表或任意外来符号识别器。
- **GD&T**：特征控制框用直线、圆和文字绘制（不是 AutoCAD 的 TOLERANCE 实体），所以任何查看器都能显示，但 AutoCAD 的 TOLERANCE 编辑命令不能编辑它。不检查公差标注本身是否合理（例如位置度是否该带 Ø）。
- **标准件**：ISO 4014/4017、4032、7089、4762 对应的已列尺寸（M3–M24 中的 11 个规格）和深沟球轴承 6000–6010、6200–6210、6300–6310。螺栓头部高度用公称尺寸，螺母高度用最大尺寸，视图为简化画法（无倒角）。孔包括 ISO 273 尺寸系列通孔、切削丝锥推荐底孔和沉孔尺寸。M14 沉孔采用已核对的 GOST 12876-67 表4公称直径24、深度15，通孔继续采用 ISO 273；不表示完整 DIN/GOST 符合性，其他规格的深度仍为建议值。具体来源、年版和非认证范围见[尺寸表审计](standard-tables.md)。
- 同一个零件画两个视图时，第二个视图应传 `count_in_bom=false`，否则明细表会数两次。
