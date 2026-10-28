import os
import shutil
import ezdxf

SRC = "part.dxf"
BAK = "part_orig.dxf"
if not os.path.exists(BAK):
    shutil.copyfile(SRC, BAK)

doc = ezdxf.readfile(BAK)  # 总是从原图开始，避免重复添加
msp = doc.modelspace()

# 机械制图用尺寸样式：字高 3.5，箭头 3
if "MECH" not in doc.dimstyles:
    ds = doc.dimstyles.new("MECH")
else:
    ds = doc.dimstyles.get("MECH")
ds.dxf.dimtxt = 3.5
ds.dxf.dimasz = 3.0
ds.dxf.dimexo = 1.0     # 尺寸界线起点偏移
ds.dxf.dimexe = 2.0     # 尺寸界线超出尺寸线
ds.dxf.dimgap = 1.0
ds.dxf.dimdec = 0
ds.dxf.dimtad = 1       # 文字在尺寸线上方
ds.dxf.dimtih = 0       # 文字与尺寸线平行
ds.dxf.dimtoh = 0
ds.dxf.dimclrd = 3
ds.dxf.dimclre = 3
ds.dxf.dimclrt = 3
ds.dxf.dimlunit = 2
ds.dxf.dimzin = 8

ATTR = {"layer": "DIM"}
STYLE = "MECH"


def hdim(p1, p2, y):
    d = msp.add_linear_dim(base=((p1[0] + p2[0]) / 2, y), p1=p1, p2=p2,
                           angle=0, dimstyle=STYLE, dxfattribs=ATTR)
    d.render()


def vdim(p1, p2, x):
    d = msp.add_linear_dim(base=(x, (p1[1] + p2[1]) / 2), p1=p1, p2=p2,
                           angle=90, dimstyle=STYLE, dxfattribs=ATTR)
    d.render()


# ---- 下方：孔定位、孔距、总长 ----
hdim((0, 0), (25, 25), -10)        # 左孔水平定位 25
hdim((25, 25), (135, 25), -10)     # 孔距 110
hdim((0, 0), (160, 0), -22)        # 总长 160

# ---- 左侧：孔高度定位、槽高度定位、总高 ----
vdim((0, 0), (25, 25), -10)        # 孔中心高 25
vdim((0, 0), (60, 62), -20)        # 槽中心线高 62
vdim((0, 0), (0, 90), -32)         # 总高 90

# ---- 上方：槽水平定位、槽长、倒角水平边 ----
hdim((0, 90), (60, 62), 100)       # 槽左端距左边 60
hdim((60, 62), (100, 62), 100)     # 槽总长 40
hdim((150, 90), (160, 80), 100)    # 倒角水平 10

# ---- 右侧：倒角竖直边 ----
vdim((160, 80), (150, 90), 172)    # 倒角竖直 10

# ---- 槽宽（零件内部空白处）----
vdim((94, 56), (94, 68), 112)      # 槽宽 12

# ---- 孔径：2×Ø14 ----
d = msp.add_diameter_dim(center=(25, 25), radius=7, angle=45,
                         location=(40, 40), text="2×<>",
                         dimstyle=STYLE, override={"dimtoh": 1, "dimtad": 0},
                         dxfattribs=ATTR)
d.render()

doc.saveas(SRC)
print("saved")
