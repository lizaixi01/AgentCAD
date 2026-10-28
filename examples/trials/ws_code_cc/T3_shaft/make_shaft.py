import ezdxf

doc = ezdxf.new("R2010", setup=True)  # setup=True 加载 CENTER 线型和标准标注样式
doc.header["$INSUNITS"] = 4  # mm
doc.layers.add("OUTLINE", color=7, lineweight=50)
doc.layers.add("CENTER", color=1, linetype="CENTER", lineweight=25)
doc.layers.add("DIM", color=3, lineweight=25)
msp = doc.modelspace()

# 各段：(直径, 长度)
segments = [(30, 50), (40, 80), (30, 70)]
C = 2  # 倒角 C2
L = sum(l for _, l in segments)

# 上半轮廓点（从左下端面上方开始，沿上边到右端）
xs = [0]
for _, l in segments:
    xs.append(xs[-1] + l)
r = [d / 2 for d, _ in segments]

upper = [(0, r[0] - C), (C, r[0])]
for i in range(len(segments)):
    x0, x1 = xs[i], xs[i + 1]
    if i > 0:
        upper.append((x0, r[i]))
    end_x = x1 - C if i == len(segments) - 1 else x1
    upper.append((end_x, r[i]))
upper.append((L, r[-1] - C))
lower = [(x, -y) for x, y in reversed(upper)]
outline = upper + lower  # 闭合外轮廓（含两端面）
msp.add_lwpolyline(outline, close=True, dxfattribs={"layer": "OUTLINE"})

# 倒角棱线和台阶面线（主视图可见轮廓线）
for x, h in [(C, r[0]), (L - C, r[-1])]:
    msp.add_line((x, h), (x, -h), dxfattribs={"layer": "OUTLINE"})
for i in range(1, len(segments)):
    h = max(r[i - 1], r[i])
    msp.add_line((xs[i], h), (xs[i], -h), dxfattribs={"layer": "OUTLINE"})

# 轴线（两端各伸出 5）
msp.add_line((-5, 0), (L + 5, 0), dxfattribs={"layer": "CENTER", "ltscale": 0.5})

dim_attr = {"layer": "DIM"}
ov = {"dimtxt": 3.5, "dimasz": 3, "dimexe": 2, "dimexo": 1}

# 直径标注（竖直线性标注，文字加 Ø）
for i, (d, _) in enumerate(segments):
    xm = (xs[i] + xs[i + 1]) / 2
    if i == 1:
        xm = xs[1] + 15  # 避开中间
    msp.add_linear_dim(
        base=(xm, 0), p1=(xm, d / 2), p2=(xm, -d / 2), angle=90,
        text=f"%%c{d}", dimstyle="EZDXF", override=ov, dxfattribs=dim_attr,
    ).render()

# 分段长度标注（轴下方第一排）
y1 = -max(r) - 10
for i in range(len(segments)):
    msp.add_linear_dim(
        base=(0, y1), p1=(xs[i], -r[i] if i == 0 else -max(r[i - 1], r[i])),
        p2=(xs[i + 1], -r[i] if i == len(segments) - 1 else -max(r[i], r[i + 1])),
        angle=0, dimstyle="EZDXF", override=ov, dxfattribs=dim_attr,
    ).render()

# 总长标注（第二排）
y2 = y1 - 10
msp.add_linear_dim(
    base=(0, y2), p1=(0, -(r[0] - C)), p2=(L, -(r[-1] - C)),
    angle=0, dimstyle="EZDXF", override=ov, dxfattribs=dim_attr,
).render()

doc.saveas("shaft.dxf")
print("saved, outline:", outline)
