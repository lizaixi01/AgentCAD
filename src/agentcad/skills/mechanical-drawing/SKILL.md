---
name: mechanical-drawing
description: 机械制图（GB 国标）规则与装配图画法：剖视和剖面线、齿轮及啮合、滚动轴承、键和螺纹、端盖与密封、装配图的序号/明细栏/尺寸，以及齿轮箱的设计顺序。在 AgentCAD 里画或检查机械零件图、装配图，或把一张机械图片重画成 CAD 时使用。Mechanical drafting rules (Chinese GB standards) for part and assembly drawings.
---
<!-- written by agentcad setup -->

# 机械制图（GB）

画机械图之前先读这一页，再按需要打开下面的参考文件。这些规则是画出来“对不对”的标准，图片或参考图只是线索。

## 工作顺序

1. **先认零件，再画图。** 列出每个零件：名称、标准件型号、和谁配合、靠哪个面定位。原图上的配合代号能说明零件，比如 Ø62K7 是轴承外圈，Ø30k6 是轴承内圈。
2. **按设计顺序定尺寸，不要对着整张图量。** 齿轮箱：传动比 → 齿轮（模数、齿数、变位、齿宽）→ 轴（各段直径和长度）→ 键、轴承 → 挡油环、套筒、端盖、密封 → 箱体 → 总装。每个尺寸记下来源：公式、标准表、经验值，或“按原图取”。见 [gearbox-design.md](references/gearbox-design.md)。
3. **零件 → 部件 → 总装。** 每个零件单独成块，基准点放在它的装配面上；部件由零件组装而成，再装进箱体的轴承座。见 [agentcad-recipes.md](references/agentcad-recipes.md)。
4. **按国标画法画每个零件**，参考文件见下表。
5. **核对。** 导出 png，局部放大，和原图逐处对比；再对照下面的检查清单。

## 参考文件

| 画到什么 | 打开 |
|---|---|
| 线型、剖视、剖面线、接触面、不剖的零件 | [sections-and-lines.md](references/sections-and-lines.md) |
| 齿轮、齿轮轴、啮合、变位 | [gears.md](references/gears.md) |
| 滚动轴承、端盖、调整环、挡油环、毡圈 | [bearings-and-seals.md](references/bearings-and-seals.md) |
| 键、螺纹、螺栓连接 | [keys-threads-fasteners.md](references/keys-threads-fasteners.md) |
| 装配图：序号、明细栏、技术特性、必须标的尺寸、配合 | [assembly-drawing.md](references/assembly-drawing.md) |
| 齿轮箱设计顺序和经验公式 | [gearbox-design.md](references/gearbox-design.md) |
| 在 AgentCAD 里怎么做（图块、部件、剖面线、尺寸） | [agentcad-recipes.md](references/agentcad-recipes.md) |

## 最常犯的错（画完逐条查）

- 剖面线：相邻零件方向相同、间距也相同。同一零件在不同视图中的剖面线不一致。
- 齿轮：剖切平面通过齿轮轴线时，**轮齿按不剖处理**。剖面线只画到齿根线，齿顶到齿根之间留白；齿根线用粗实线，分度线用细点画线画在留白带里。
- 啮合区：分度线重合；一个齿轮的齿顶线画粗实线，另一个的齿顶线画虚线（被挡住）；两齿轮之间留出 0.25m 的顶隙。
- 齿轮轴的轮齿端部倒角，从端面上的齿根圆倒到齿顶。
- z < 17 的标准直齿轮会根切：要正变位，并在技术特性表里写出变位系数。
- 实心件（轴、键、销、螺栓、螺母、垫圈、滚动体）在纵向剖切时按不剖画；要表达键、销时，用局部剖，以波浪线为界。
- 接触面只画一条线；不接触的面即使间隙很小也画两条线，例如螺栓和通孔、轴和透盖孔。
- 嵌入式端盖的凸缘要嵌在箱体的槽里；调整环是单独的零件。
- 别的零件的线不能穿过一个被剖开零件的剖面。
- 装配图要有序号、明细栏，还要标出规格性能、配合、安装、外形四类尺寸；减速器还要标中心距及其偏差，并附技术特性表。
- 图片往往不按比例，像素尺寸和图上的标注会对不上：以标注和设计推算为准，并把差异告诉用户。
