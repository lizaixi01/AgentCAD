# 已知限制、依赖与路线图

## 依赖

| 依赖 | 许可证 | 用途 | 说明 |
|---|---|---|---|
| ezdxf ≥1.3,<2（实测 1.4.5） | MIT | DXF 读写、标注渲染、范围计算 | 核心依赖 |
| mcp ≥1.20,<2（实测 1.30.0） | MIT | MCP 服务器 | 2.x API 不兼容，故固定 1.x |
| pypdf ≥4（实测 6.21） | BSD-3 | PDF 文字提取 | |
| Pillow（可选 `[preview]`） | MIT-CMU | SVG 导出（ezdxf drawing 插件需要） | 未安装时返回 `dependency/DEPENDENCY_MISSING` |

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
9. **标注样式**：只有一个 `AGENTCAD` 样式（按单位换算尺寸），没有 ISO/ANSI 样式库。
10. **并发**：使用文件锁实现单写者；锁超过 120 s 视为过期。不支持多进程同时写同一图纸。
11. **字节级可复现**：几何和 handle 是确定的，但 DXF 头部的时间戳和 GUID 每次保存都会变（研究中 E 实验已确认），所以要用几何等价性来比较。
12. **AutoCAD 后端的运行条件**：工作目录必须能映射到纯 ASCII 路径（后端会自动退回系统临时目录）；只能从 Python 进程启动（在 Git Bash 中直接启动会挂起，原因未知）；后端不会修改 AutoCAD 的任何持久设置。

13. **图纸空间布局**：已能读取、编辑和校验（`layout` 参数），并能新建布局和视口（`create_layout`、`add_viewport`）（2026-10-28）。仍未处理：视口对模型的投影关系（不会自动判断图纸上的副本与模型是否一致，只会提醒去检查），以及外部参照的内容。
14. **动态块**：ezdxf 保存时丢弃 `ACDB_BLOCKREPRESENTATION_DATA`，动态块的参数化行为可能失效（AutoCAD 审核结果不变）。
15. **`modify` 不支持 DIMENSION**：改标注只能删除后重建（或用 `run_script`）。
18. **`run_script`**：默认关闭。静态检查加独立进程只防误操作，不是安全沙箱；开启后 Agent 等于能以当前用户身份运行受限的 Python。
16. **版面与制图规范不检查**：标注互相重叠、文字压线、轴类的台阶/倒角轮廓线等，验证器发现不了，需要出图目视检查（`examples/trials/render_png.py`）。
17. **字体**：新图默认 `gbenor.shx` + `gbcbig.shx`。没有安装这两个字体的 CAD 软件会做字体替换。

## 路线图

- **实测暴露的问题**（[trials-report.md](trials-report.md)、[comparison-hard-tasks.md](comparison-hard-tasks.md)）：~~读取图纸空间布局~~（已完成）；~~脚本出口~~（已完成，`run_script`）；判断图纸副本与模型是否一致；`modify` 支持标注；标注重叠检测；保留动态块数据。
- **P1 收尾**：两线角度标注创建、HATCH、MLEADER、坐标标注；为 `mirror` 作用于标注/块、开口多段线偏移补测试。
- **P2**：更多零件族（法兰、L 形支架、长圆孔、孔阵列图案）；ISO/ANSI 标注样式与图层标准模板；块属性模板库；批量处理多图纸的工具；增量读取（按 handle 范围或修改时间）；规格修订时检测"手工修改过的标签实体"并要求确认。
- **P3**：不依赖 AutoCAD 的 DWG 方案（ODA File Converter，许可证由用户自行确认）；为 mirror 作用于标注/椭圆、HATCH 等补充 AutoCAD 差分用例；联立约束求解（可评估 SolveSpace 求解库，GPL，需要隔离）；3D 与参数化建模。

## 行业库（2026-10-29）

`library` 类操作（`ops/library.py`，数据在 `stdlib.py`）和 `standard_library` 工具。限制：

- **P&ID**：24 个常用符号（ISO 10628 / ISA-5.1 风格），不是完整符号库；没有管道等级表、管线自动编号或连通性检查。符号放到管道上时会切断管道，但不会自动连到设备接口。
- **GD&T**：特征控制框用直线、圆和文字绘制（不是 AutoCAD 的 TOLERANCE 实体），所以任何查看器都能显示，但 AutoCAD 的 TOLERANCE 编辑命令不能编辑它。不检查公差标注本身是否合理（例如位置度是否该带 Ø）。
- **标准件**：ISO 4014/4017、4032、7089、4762（M3–M24）和 ISO 15 深沟球轴承 60xx/62xx/63xx。螺栓/螺母头部用的是最大尺寸，视图为简化画法（无倒角）。孔：ISO 273 通孔、ISO 2306 底孔、DIN 974-1 沉孔。
- 同一个零件画两个视图时，第二个视图应传 `count_in_bom=false`，否则明细表会数两次。
