# 在 AgentCAD 里画装配图

## 零件 → 部件 → 总装

1. **零件**：每个零件用 `define_block` 定义一个图块，`base_point` 放在它的装配基准上（轴肩端面、轴承端面、轮毂端面、座孔端面）。
   用属性记录零件信息，明细栏可以直接从这些属性生成：
   `"attributes": [{"tag": "NO", "insert": [0,0], "height": 0.01, "default": "19"}, {"tag": "NAME", ...}, {"tag": "SPEC", ...}]`
2. **部件**：用 `insert_block` 把零件插到它的基准位置（每个都带同一个前缀的 tag，如 `a1:shaft`），
   再用 `block_from_entities(name="A1_GEAR_ON_SHAFT", target={"tag_prefix": "a1:"})` 打包成部件图块，
   然后 `delete` 同一个 target，删掉原来那几个散的插入。部件里还可以再嵌套部件。
3. **总装**：插入箱体，把部件插到轴承座（中心距 a），再插调整环、端盖、密封件。
   对称的零件画在上侧，插到下侧时 `rotation: 180`，以座孔端面为基准。

画之前，用一个脚本或一张表把第 1~4 步的尺寸算好；位置都从这些尺寸算出来，不要从图片上量。

## 剖面线

- `add_hatch` 的 `points` 用零件剖面的闭合轮廓（可以带 bulge 圆弧），`pattern: "ANSI31"`。
- `pattern_angle: 0` 是 45°，`90` 是 135°；`pattern_scale` 0.3~0.8 控制间距。
- 先给每个零件定一种（角度, 间距），再检查相邻的零件是否不同。
- 齿轮剖面只画到齿根线；齿带用不填充的折线另画轮廓。
- 毡圈等非金属件用 `ANSI37`。
- 剖面轮廓不能自相交（例如局部剖的波浪线穿过键槽边）：自相交的边界可能一条剖面线都画不出来，检查也不报错。每个局部剖都放大 png 看一眼。

## 尺寸

- 配合：`add_linear_dim` 的 `text: "%%c<>H7/k6"`，`<>` 显示实际测量值，图画错了标注也会跟着变，能看出来。
- 偏差：`"tolerance": {"lower": -0.023, "upper": 0.023}`。
- 尺寸的 p1、p2 要落在几何上（端点、轮廓线上），否则检查会报 DIMENSION_NOT_ATTACHED。
- 断开画法的轴：尺寸文字写实际长度（`text: "202"`）。检查会把它报成 DIMENSION_TEXT_MISMATCH 错误，验证不通过（`strict: true` 时不会保存，所以这一批不要用 strict）。在报告里说明这是断开画法造成的。

## 表格和文字

- 中文：先用 `create_text_style`（gbenor.shx + gbcbig.shx）把 Standard 设成能显示中文。
- 明细栏、技术特性表：`add_table`（rows、col_widths、row_height）。

## 核对

- `export_drawing` 导出 png；从图片重画时，把重画结果和原图局部放大后并排对比（`inspect_image` 看原图局部）。
- 按 SKILL.md 的“最常犯的错”逐条查。
- 保存结果里的 validation 只检查文件和几何是否合理，不检查是否符合制图标准，这一项要靠上面的核对。
