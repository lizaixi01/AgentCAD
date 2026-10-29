# 三维参数化零件（FreeCAD 后端）

AgentCAD 用同一组工具处理二维图纸（`.dxf`）和三维零件（`.FCStd`）。路径以 `.FCStd` 结尾时，`create_drawing`、
`apply_operations`、`read_drawing`、`inspect_entities`、`validate_drawing`、`get_diff`、`export_drawing`、
`rollback`、`list_checkpoints`、`history`、`recover` 都按三维零件处理。检查点、journal、写锁、原子提交和结果信封
都与图纸共用。

## 为什么用 FreeCAD

- 产出原生 `.FCStd`：一个 PartDesign Body，特征树（Sketch → Pad/Pocket/Hole/Fillet…）完整可编辑，参数改了能重建。
  CADBench（V3 用 FreeCAD 1.1.0 评分）只接受这种文件：评分器先检查"恰好一个非空 Body、一个实体、全部是原生
  PartDesign 特征"，不满足直接 0 分。build123d/OCP 这类库能做实体，但存不出特征树。
- 草图约束用 FreeCAD Sketcher 的联立求解器。
- FreeCAD 是 LGPL-2.1+，作为**独立进程**运行，AgentCAD 不链接它，核心仍是 MIT、无 FreeCAD 也能用（只是不能做三维）。

## 安装

装 FreeCAD 1.1（实测 1.1.4，OCCT 7.8.1，与 CADBench 官方二进制同一内核版本）。如果不在标准位置，设置
`AGENTCAD_FREECAD` 为它的安装目录、`bin` 目录、自带的 `python` 或 `freecadcmd`。也认 freecad-validator 用的
`FREECAD_LIB`。`agentcad mcp-config --write` 会把这两个环境变量写进 MCP 配置。没装时三维工具返回
`dependency/DEPENDENCY_MISSING`。

用 CadQuery 脚本建模（`run_script`，见下）还要在 AgentCAD 自己的 Python 里装 CadQuery：
`pip install "agentcad-runtime[cadquery]"`（实测 CadQuery 2.8，OCP 7.9.3）。FreeCAD 自带的 Python 不装它。

## 进程模型

每次调用起一个 FreeCAD 进程（冷启动约 1.5 s，一次调用通常 0.5–1 s 完成）运行 `part/_fc_runner.py`：

1. 零件文件复制进系统临时目录下的短路径作业目录（FreeCAD 存盘时路径超过 Windows 260 字符会失败）；
2. 在副本上依次执行操作，每步之后重算，有特征出错就整批失败（结构化错误带 `op_index`、FreeCAD 原始信息和提示）；
3. 存成候选文件，**关闭文档再从磁盘重新打开**、重算、验证（一次进程里完成，验证读的是存下来的文件）；
4. AgentCAD 再按图纸的流程提交：检查点 → pending → 原子替换 → journal。`strict=true` 时验证不过不提交，候选存进
   `failed/`。

作业目录只放 `job.json`（数据）和文件副本；调用方的任何字符串都不会成为代码或命令行参数。

## 操作

`list_operations()` 的 `part_operations` 是紧凑索引，`list_operations(category="part")` 给完整 schema。
完整参数见 [operations.md](operations.md) 的 `part_*` 类别。

| 类别 | 操作 |
|---|---|
| part_sketch | `add_sketch`：放在原点平面（plane + offset）、实体的平面上（on_face）或任意 origin + normal |
| part_feature | `pad` `pocket` `revolve` `groove` `hole`（沉头/埋头/ISO 螺纹）`fillet` `chamfer` `thickness`（抽壳）`linear_pattern` `polar_pattern` `mirror` `primitive`（加/减 box、cylinder…）`loft` `sweep` `helix` |
| part_edit | `set_parameters`（参数表）`modify_feature`（改已有特征的参数，后续特征跟着重建）`delete_feature` |

草图形状：rectangle、circle、polygon/polyline（点可带 bulge，和二维多段线一样）、regular_polygon、slot、line、arc、
point。形状自动完全约束，端点相接的自动加重合约束。

### 参数和表达式

任何 `dim` 类型的值可以是数字（mm）、带单位字符串（`"0.5in"`）或表达式（`"=Params.width * 2"`）。
`set_parameters` 在名为 `Params` 的电子表格里建参数；之后改参数，所有引用它的草图尺寸、拉伸长度、孔径等都会重算。
参数名不能是 FreeCAD 的单位或保留字（`t`、`m`、`mm`、`deg`、`pi`）。

### 选择器（拓扑命名问题）

FreeCAD 1.1.4 自带的拓扑命名修复在脚本建模时不可靠：实测改草图宽度后，圆角引用的边变成 `?Edge2`，特征失效。
所以 AgentCAD 不让 FreeCAD 保存会漂移的引用：

- 草图只附着在原点平面上（`on_face` 也是：解析一次面的位置，存为绝对位置）；
- 圆角/倒角的边、抽壳的面、`on_face` 的面都以**几何选择器**存在特征上（`AgentCADRef`），每次编辑后按特征顺序
  逐个重新解析，解析结果再写回 FreeCAD。

边选择器：`"all"`、`"Edge3"`，或对象 `{type, direction, axis, radius|diameter, length, x|y|z, box, face, near, count}`，
列表表示并集。面选择器：`"top"|"bottom"|"front"|"back"|"left"|"right"`、`"Face2"`，或对象
`{type, normal, extreme, axis, radius|diameter, inner, x|y|z, box, near, count}`。
`inspect_entities(filter={"kind": "edges", "selector": {...}})` 能先预览选择器选到哪些边。

## 脚本建模（`run_script`）

操作建出的是可编辑的特征树（参数表、`modify_feature`，CADBench 只认这种）。有些形状用 CadQuery 一段程序写出来更快，
模型也更熟悉它：BenchCAD Vision2Code 的对照试验里，直接写 CadQuery 的 Agent 得分高于用 AgentCAD 操作的 Agent。
`run_script` 把两者接起来：脚本建出实体，AgentCAD 照常管检查点、journal、验证、撤销和预览，之后还能接着用操作改。

```python
run_script("part.FCStd", code="""
import cadquery as cq
result = cq.Workplane("XY").box(40, 20, 10).faces(">Z").workplane().hole(6)
""")
apply_operations("part.FCStd", [{"op": "fillet", "edges": {"type": "line", "direction": "z"}, "radius": 2}])
```

- **语言**：`language="cadquery"`（默认）：程序把 `result` 设成 `cq.Workplane`、`Shape` 或 `Assembly`（`cq` 已导入，
  也认 `show_object(x)`）；`language="freecad"`：FreeCAD Part 代码（给了 `Part`、`App`、`Vector`），`result` 是
  `Part.Shape`。`result` 里的多个实体会先合并；合并后仍是分开的几块就报 `NOT_SINGLE_SOLID`。数字按零件单位
  （英寸零件里 `box(1, 1, 1)` 是 25.4 mm 的立方体）。零件不存在时按 mm 新建。
- **实体存在哪**：脚本的实体放进 Body 外的一个 `Part::Feature`（`ScriptSolid`，脚本全文和 sha256 也存在它的
  `AgentCADScript` 属性里），作为 Body 的 `BaseFeature`；FreeCAD 在 Body 开头放一个 `PartDesign::FeatureBase`。
  之后的 `fillet`、`hole`、`pocket`、`on_face` 草图、`set_parameters` 驱动的尺寸都建在它上面，选择器照常每次重新解析。
- **修改**：改脚本，整段重新运行。默认零件变成新实体本身（原来的 Body 和特征删掉，留在检查点里）；
  `keep_features=true` 保留 Body 里已有的特征，在新实体上按顺序重建（选择器重新解析，重建失败则整次不提交）。
  基体不能用 `modify_feature`/`delete_feature` 改，结果提示重新运行脚本。
- **事务**：和 `apply_operations` 一样：检查点 → 运行 → 候选文件 → FreeCAD 重新打开并验证 → 原子提交 → journal
  （记录完整脚本和哈希，`history(seq=[n])` 可取回）→ 查看器进度事件；`dry_run`、`strict`、`requirements`、
  `rollback` 都照常。失败时文件不变。
- **错误**：`SCRIPT_FAILED`（脚本抛异常；`details.script_lines` 是出错的脚本行，`details.traceback` 是回溯的末尾）、
  `NO_RESULT`（没设 `result`）、`NOT_A_SOLID`（只有草图、线或面）、`NOT_SINGLE_SOLID`、`SCRIPT_TIMEOUT`、
  `SCRIPT_REJECTED`（静态检查不过）、`DEPENDENCY_MISSING`（没装 CadQuery）。
- **验证**：基体来自脚本时 `validate_drawing` 报一条警告 `SCRIPT_BASE_SOLID`，不是错误：导出 STEP/STL 没问题，
  但要求原生特征树的评分器（CADBench）会拒收。

**进程模型**：CadQuery 装不进 FreeCAD 的 Python（OCP 与 FreeCAD 各带一份 OCCT），所以 CadQuery 脚本在 AgentCAD
自己解释器的子进程里运行（`python -I part/_cq_runner.py <作业目录>`，不经 shell，`AGENTCAD_SCRIPT_TIMEOUT` 限时，
默认 60 s，含 CadQuery 启动的约 3–4 s；工作目录是工作区状态目录 `.agentcad/freecad/` 下的作业目录），实体写成
BREP 交给 FreeCAD 进程导入。BREP 是 OCCT 自己的格式，两边都用 OCCT，几何原样过去，不像 STEP 要经过一次翻译。
FreeCAD 脚本直接在 FreeCAD 进程里运行（限时为脚本限时 + 60 s）。

**安全**：和二维脚本同一套策略：默认关闭（`AGENTCAD_ALLOW_SCRIPTS=1` 或 CLI `--allow-scripts` 开启）；先做静态检查
（只能导入 cadquery / FreeCAD Part、numpy 和标准数学/数据模块；不能打开、导入、导出或保存文件，不能用
`cq.exporters`/`importers`、`exportStep` 一类方法，不能 eval/exec/getattr/双下划线访问），运行时只给精简的内置函数和
同一份导入白名单。这些检查防的是误操作，不是安全沙箱：只对你愿意让它以你的身份运行 Python 的 Agent 开启。

## 验证

`validate_drawing` 对零件：FreeCAD 重新打开、重算，然后检查

- 特征错误（`FEATURE_ERROR`，带 FreeCAD 原始信息和提示）；
- CADBench 的零件约定：恰好一个非空 Body（`NO_BODY`、`EMPTY_BODY`、`MULTIPLE_BODIES`）、一个实体
  （`NOT_SINGLE_SOLID`，FreeCAD 1.1 本身允许一次 pad 出两个实体）、只有原生 PartDesign 特征
  （`NON_PARAMETRIC_GEOMETRY`），实现照 freecad-validator 的 integrity gates；
- B-rep 有效性、Tip 之后的特征（`FEATURES_AFTER_TIP`）、草图冲突/冗余约束。

需求：`bbox {size}`、`volume`/`area {value, rel_tolerance}`、`hole {diameter, count}`（按内圆柱面识别、同轴合并）、
`hole_count`、`solid_count`、`parameter {name, value}`、`center_of_mass`、`feature_count {feature_type, count|min}`。零件参数按零件单位报告和比较，几何（体积、尺寸、包围盒）一律按 mm。

## 导出

`export_drawing` 对零件支持 `step`（BenchCAD 等按 STEP 评分）、`iges`、`brep`、`stl`、`obj` 和 `png`（预览图，见下）。

Body 不是恰好一个有效实体（或有特征出错）时拒绝导出（`NOT_EXPORTABLE`）：评分器会照样体素化一个坏文件，而不是拒收。STEP/IGES/BREP 写完后用 `Part.read` 读回，和零件比较实体数、有效性、体积和尺寸，结果在 `readback` 里；不一致时报 `EXPORT_MISMATCH`。

## 预览图

`export_drawing(part.FCStd, out.png, "png", views=[...], image_size=..., fit="view")` 给 Agent 看它做出的实体：
着色、平行投影、画出可见的 B-rep 边（不画圆柱面的参数接缝）。`image_size` 是每个视图的像素数，默认单视图 512、
多视图拼图每格 256（2×2 拼图为 512×512，和常见参考图同量级；图片在之后每一轮都占上下文，越大越贵）。

- **视图方向**：`views` 的每一项是视图名或向量 `[x, y, z]`，表示**从零件指向相机的方向**（相机位置），相机看向零件中心。
  视图名：`front` = `[0,-1,0]`（从 −Y 看，+X 向右、+Z 向上），`back` = `[0,1,0]`，`right` = `[1,0,0]`（+Y 向右），
  `left` = `[-1,0,0]`，`top` = `[0,0,1]`（+X 向右、+Y 向上），`bottom` = `[0,0,-1]`，`iso` = `[1,-1,1]`，
  `iso_back` = `[-1,1,1]`，`iso_bottom` = `[1,-1,-1]`。屏幕向上取 +Z（看向 ±Z 时取 +Y）。
- **取景**：零件包围盒的中心放在画面中心。`fit="view"`（默认）：包围盒在该视图的投影撑满画面的 90%，所以每个视图、
  每个零件各自缩放，图上**不带固定比例**，不能用像素量尺寸（尺寸看 `read_drawing` 或 `validate_drawing`）。
  `fit="uniform"`：所有视图用同一比例（包围盒对角线 = 画面的 90%），视图之间可比大小。
- 多个视图拼成一张带标签的网格（≤4 个为 2 列，最多 9 个）。
- **MCP 直接返回图片**：通过 MCP 导出 png 时，结果里先是普通的 JSON，再附上这张图片本身（`inline_image`，默认开，超过 2 MB 不附），
  Agent 不需要另外的看图工具就能看到预览。CLI 和 Python API 照旧只写文件。
- 球体、圆锥顶点这类没有曲线的**退化边**（FreeCAD 读它的 `Curve` 会报 `undefined curve type`）在预览和边选择里都会跳过。
- 预览**不要求**零件可导出：Body 有多个实体或特征出错时照样渲染当前的形状（导出 STEP 会拒绝），方便看清哪里出了问题。

### 与参考图比较

`export_drawing(part.FCStd, cmp.png, "png", views=[...], reference="ref.png")`：`reference` 是工作区里的一张图，
按和预览一样的网格排好视图（顺序同 `views`；单视图一格，4 个以内 2 列，更多 3 列）。对每个视图：

1. **参考轮廓**：和背景色不同的像素（背景色取格子边框一圈像素的中位数，所以背景是什么颜色都行；图带透明通道时
   取不透明像素），再做一次约为格宽 1/128 的开运算，去掉网格线、标签、引线这类细线。开运算后几乎什么都不剩时，
   当作线框图：先闭合轮廓再填充。
2. **我们的渲染**：用这个视图的相机渲染零件，轮廓取自深度缓冲（加上轮廓边线）。
3. **对齐**：把我们的轮廓按**同一个**比例缩放（保持长宽比），对齐到参考轮廓的包围盒中心。所以取景（缩放、
   偏移、留白）不影响结果，**整体尺寸也不比较**，比的是形状和比例。参考轮廓碰到格子边缘时当作被裁切：
   比例只按没被裁的方向算，并对齐到没被裁的一侧（结果里 `reference_cropped`）。
4. **得分**：两边做同样的开运算后算轮廓 IoU（交集 / 并集）。

输出图每个视图一行：参考格、对齐后的我们的渲染、差异图（红：只在参考里，蓝：只在我们的零件里，灰：两边都有）。
每格高 `image_size`（默认 256 px）。结果里 `compare.views[]` 给每个视图的 `iou` 和对齐比例，`mean_iou` 是平均值。
不传 `reference` 时预览行为不变。比较用 numpy + Pillow 在 AgentCAD 进程里做（`part/compare.py`），FreeCAD 进程
只返回每个视图的渲染图和轮廓。

注意包围盒对齐把整体尺寸误差藏起来了：零件整体大一倍，IoU 照样接近 1。尺寸看 `validation.shape`。

无 GUI 的 FreeCAD 不能离屏渲染，所以预览在 runner 里自己光栅化：OCC 三角化 → 逐三角形扫描线填充的 numpy z-buffer →
平面着色（光源靠近视线方向）→ 2 倍超采样。1024 px 四视图约 2.5 s（另加 FreeCAD 启动约 1.5 s）。用 FreeCAD 自带的
numpy 和 PIL；纯 `FREECAD_LIB` 解释器没有 PIL 时用 zlib 直接写 PNG（不带标签）。

## 已知限制

- 一个零件一个 Body（CADBench 的要求）；多零件装配还没有。
- 脚本建的基体是一个整块实体，不是特征树：之后的操作是可编辑的特征，但基体本身只能整段重新运行脚本来改。
- 参考图比较只看轮廓（剪影），看不出轮廓内部的差别（例如盲孔、台阶面）；网格必须和预览的排法一致。
- 没有从三维生成二维工程图（投影视图 → DXF）；这是下一步，接上之后三维模型能直接出图。
- `on_face` 的草图是绝对定位：面移动时由 AgentCAD 的重新解析跟上，直接用 FreeCAD GUI 改模型则不会跟。
- 非 mm 零件里，`set_parameters` 的裸数字按长度（零件单位）换算；计数类参数（如阵列个数）请直接写在操作里。
- Agent 三维实验目前只有 BenchCAD Vision2Code 的 100 题试点（每题一次，见 [examples/benchcad/README.md](../examples/benchcad/README.md)），图纸到零件（T1）还没跑。
