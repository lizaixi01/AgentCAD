import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment

import os
import shutil

FN = "part.dxf"
if not os.path.exists("part_backup.dxf"):
    shutil.copy(FN, "part_backup.dxf")
doc = ezdxf.readfile(FN)
msp = doc.modelspace()

if "A3" in doc.layouts.names():
    doc.layouts.delete("A3")

# 模型空间范围（含尺寸标注），只读不改
ext = bbox.extents(msp)
mx0, my0 = ext.extmin.x, ext.extmin.y
mx1, my1 = ext.extmax.x, ext.extmax.y
mcx, mcy = (mx0 + mx1) / 2, (my0 + my1) / 2

# 图层与文字样式
for name, color, lw, plot in [("FRAME", 7, 50, True), ("TITLE", 7, 25, True), ("VPORT", 8, 13, False)]:
    if name not in doc.layers:
        doc.layers.add(name, color=color, lineweight=lw)
    doc.layers.get(name).dxf.plot = 1 if plot else 0
if "HZ" not in doc.styles:
    doc.styles.add("HZ", font="simsun.ttc")

# A3 横向布局
lay = doc.layouts.new("A3")
lay.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")

# 图框
W, H = 420, 297
L, R, B, T = 25, 5, 5, 5
ix0, iy0, ix1, iy1 = L, B, W - R, H - T
lay.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                   dxfattribs={"layer": "FRAME", "lineweight": 25})
lay.add_lwpolyline([(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)], close=True,
                   dxfattribs={"layer": "FRAME", "lineweight": 50})

# 标题栏 180x40，内框右下角
TW, TH = 180, 40
tx0, ty0 = ix1 - TW, iy0
tx1, ty1 = ix1, iy0 + TH
lay.add_lwpolyline([(tx0, ty0), (tx1, ty0), (tx1, ty1), (tx0, ty1)], close=True,
                   dxfattribs={"layer": "TITLE", "lineweight": 50})
ymid = ty0 + TH / 2
cols = [tx0, tx0 + 25, tx0 + 90, tx0 + 115, tx1]  # 标签25 / 值65 / 标签25 / 值65
lay.add_line((tx0, ymid), (tx1, ymid), dxfattribs={"layer": "TITLE"})
for x in cols[1:-1]:
    lay.add_line((x, ty0), (x, ty1), dxfattribs={"layer": "TITLE"})


def cell_text(txt, c, row, h):
    x = (cols[c] + cols[c + 1]) / 2
    y = ymid + TH / 4 if row == 0 else ty0 + TH / 4
    lay.add_text(txt, height=h, dxfattribs={"layer": "TITLE", "style": "HZ"}).set_placement(
        (x, y), align=TextEntityAlignment.MIDDLE_CENTER)


cell_text("图名", 0, 0, 3.5)
cell_text("底板", 1, 0, 7)
cell_text("图号", 2, 0, 3.5)
cell_text("BP-300", 3, 0, 5)
cell_text("比例", 0, 1, 3.5)
cell_text("1:2", 1, 1, 5)
cell_text("材料", 2, 1, 3.5)
cell_text("Q235", 3, 1, 5)

# 视口：1:2，置于内框中部、标题栏上方
SCALE = 0.5
margin = 10  # 纸面留白
vw = (mx1 - mx0) * SCALE + 2 * margin
vh = (my1 - my0) * SCALE + 2 * margin
vcx = (ix0 + ix1) / 2
vcy = max((iy0 + iy1) / 2, ty1 + vh / 2 + 5)  # 不与标题栏重叠
vp = lay.add_viewport(center=(vcx, vcy), size=(vw, vh),
                      view_center_point=(mcx, mcy), view_height=vh / SCALE,
                      dxfattribs={"layer": "VPORT"})
vp.dxf.status = 2

doc.saveas(FN)
print("model ext", ext.extmin, ext.extmax)
print("viewport center", (vcx, vcy), "size", (vw, vh))
