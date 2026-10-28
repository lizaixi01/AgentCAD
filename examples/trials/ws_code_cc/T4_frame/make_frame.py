import ezdxf
from ezdxf.enums import TextEntityAlignment

doc = ezdxf.new("R2010", setup=True)
doc.units = ezdxf.units.MM
doc.header["$INSUNITS"] = 4
doc.header["$MEASUREMENT"] = 1
doc.styles.add("HZ", font="simfang.ttf")  # 仿宋，支持中文

doc.layers.add("FRAME_THIN", color=7, lineweight=25)
doc.layers.add("FRAME_THICK", color=7, lineweight=70)
doc.layers.add("TABLE", color=7, lineweight=25)
doc.layers.add("TABLE_THICK", color=7, lineweight=50)
doc.layers.add("TEXT", color=7)

msp = doc.modelspace()

# 外框与内框
W, H = 420, 297
L, M = 25, 10
msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                   dxfattribs={"layer": "FRAME_THIN"})
ix0, iy0, ix1, iy1 = L, M, W - M, H - M  # 25,10,410,287
msp.add_lwpolyline([(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)], close=True,
                   dxfattribs={"layer": "FRAME_THICK"})


def line(p1, p2, layer="TABLE"):
    msp.add_line(p1, p2, dxfattribs={"layer": layer})


def text(s, cx, cy, h=3.5):
    msp.add_text(s, height=h, dxfattribs={"layer": "TEXT", "style": "HZ"}) \
        .set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)


# 标题栏：180 x 30，右下角与内框右下角重合
TW, RH = 180, 10
tx0, tx1 = ix1 - TW, ix1          # 230 .. 410
ty0, ty1 = iy0, iy0 + 3 * RH      # 10 .. 40
cols = [tx0, tx0 + 25, tx0 + 90, tx0 + 115, tx1]  # 标签25 值65 标签25 值65
line((tx0, ty1), (tx1, ty1), "TABLE_THICK")        # 上边
line((tx0, ty0), (tx0, ty1), "TABLE_THICK")        # 左边
for i in (1, 2):
    line((tx0, ty0 + i * RH), (tx1, ty0 + i * RH))
line((cols[1], ty0), (cols[1], ty1))               # 第一列分隔贯通三行
for x in cols[2:4]:
    line((x, ty0 + RH), (x, ty1))                  # 第三行右侧合并
rows_tb = [
    ["名称", "法兰盘", "图号", "FL-001"],
    ["材料", "Q235", "比例", "1:1"],
]
for r, row in enumerate(rows_tb):
    cy = ty1 - (r + 0.5) * RH
    for c, s in enumerate(row):
        text(s, (cols[c] + cols[c + 1]) / 2, cy, 5 if s == "法兰盘" else 3.5)
cy = ty0 + 0.5 * RH
text("单位", (cols[0] + cols[1]) / 2, cy)
text("mm", (cols[1] + tx1) / 2, cy)

# 明细表：紧贴标题栏上方，按 GB/T 10609.2 表头在下，序号自下而上
PH = 8
pcols = [tx0, tx0 + 15, tx0 + 100, tx0 + 120, tx1]  # 序号15 名称85 数量20 材料60
prows = [
    ["序号", "名称", "数量", "材料"],
    ["1", "法兰盘", "1", "Q235"],
    ["2", "螺栓 M10×40", "6", "8.8级"],
]
py0, py1 = ty1, ty1 + len(prows) * PH   # 40 .. 64
line((tx0, py1), (tx1, py1))
line((tx0, py0 + PH), (tx1, py0 + PH), "TABLE_THICK")  # 表头上线
line((tx0, py0 + 2 * PH), (tx1, py0 + 2 * PH))
for i, x in enumerate(pcols):
    line((x, py0), (x, py1), "TABLE_THICK" if i in (0,) else "TABLE")
for r, row in enumerate(prows):
    cy = py0 + (r + 0.5) * PH
    for c, s in enumerate(row):
        text(s, (pcols[c] + pcols[c + 1]) / 2, cy)

doc.saveas("frame_a3.dxf")
print("saved")
