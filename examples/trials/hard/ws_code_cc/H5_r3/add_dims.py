import ezdxf

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

# 可重复运行：先清掉本脚本之前加的尺寸（原图没有任何 DIMENSION）及其匿名块
for e in list(msp.query("DIMENSION")):
    blk = e.dxf.get("geometry")
    msp.delete_entity(e)
    if blk and blk in doc.blocks:
        doc.blocks.delete_block(blk, safe=False)

# 机械制图尺寸样式：字高3.5，箭头3，文字在尺寸线上方并与尺寸线平行
if "MECH" not in doc.dimstyles:
    ds = doc.dimstyles.new("MECH")
    ds.dxf.dimtxt = 3.5
    ds.dxf.dimasz = 3.0
    ds.dxf.dimexo = 1.0
    ds.dxf.dimexe = 2.0
    ds.dxf.dimgap = 1.0
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimdec = 0
    ds.dxf.dimzin = 8
    ds.dxf.dimscale = 1.0
    ds.dxf.dimlunit = 2
    ds.dxf.dimclrd = 0
    ds.dxf.dimclre = 0
    ds.dxf.dimclrt = 0

A = {"layer": "DIM"}
S = "MECH"


def hdim(p1, p2, y, **kw):
    d = msp.add_linear_dim(base=((p1[0] + p2[0]) / 2, y), p1=p1, p2=p2,
                           angle=0, dimstyle=S, dxfattribs=A, **kw)
    d.render()


def vdim(p1, p2, x, **kw):
    d = msp.add_linear_dim(base=(x, (p1[1] + p2[1]) / 2), p1=p1, p2=p2,
                           angle=90, dimstyle=S, dxfattribs=A, **kw)
    d.render()


# ---- 下方：孔的水平定位、孔距、总长 ----
hdim((0, 0), (25, 25), -12)          # 左孔中心到左边 25
hdim((25, 25), (135, 25), -12)       # 孔距 110
hdim((0, 0), (160, 0), -24)          # 总长 160

# ---- 左侧：孔的高度定位、槽高度定位、总高（基准为底边）----
vdim((0, 0), (25, 25), -12)          # 孔中心高 25
vdim((0, 0), (60, 62), -24)          # 槽中心线高 62
vdim((0, 0), (0, 90), -36)           # 总高 90

# ---- 上方：槽水平定位、槽长、倒角 ----
hdim((0, 90), (66, 68), 112)         # 槽左圆弧中心到左边 66
hdim((60, 62), (100, 62), 100)       # 槽总长 40
hdim((150, 90), (160, 80), 100, text="10×45°")  # 右上角倒角（右界线从右竖边引出）

# ---- 槽宽：放在槽右侧零件内部空白处 ----
vdim((94, 56), (94, 68), 110)        # 槽宽 12

# ---- 孔径：两孔相同，标 2×Ø14 ----
d = msp.add_diameter_dim(center=(25, 25), radius=7, angle=45,
                         location=(42, 44), text="2×<>",
                         dimstyle=S, dxfattribs=A,
                         override={"dimtoh": 1})  # 引出文字水平
d.render()

doc.saveas("part.dxf")
print("saved")
