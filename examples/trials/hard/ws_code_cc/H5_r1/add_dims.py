import ezdxf

FN = "part.dxf"
doc = ezdxf.readfile(FN)
print("version", doc.dxfversion, "codepage", doc.header.get("$DWGCODEPAGE"))
msp = doc.modelspace()

# 不允许重复运行时叠加尺寸
assert not list(msp.query("DIMENSION")), "part.dxf already contains dimensions"

# 机械制图尺寸样式：字高 3.5，箭头 3，整数显示
if "MECH" not in doc.dimstyles:
    ds = doc.dimstyles.duplicate_entry("EZDXF", "MECH")
    ds.dxf.dimtxt = 3.5
    ds.dxf.dimasz = 3.0
    ds.dxf.dimexo = 1.0
    ds.dxf.dimexe = 2.0
    ds.dxf.dimgap = 1.0
    ds.dxf.dimdec = 0
    ds.dxf.dimtad = 1      # 文字在尺寸线上方
    ds.dxf.dimtih = 0      # 文字与尺寸线平行
    ds.dxf.dimtoh = 0
    ds.dxf.dimzin = 8      # 去掉尾随零
    ds.dxf.dimlfac = 1.0
    ds.dxf.dimscale = 1.0

ATTR = {"layer": "DIM"}
STYLE = "MECH"


def lin(p1, p2, base, angle=0, text="<>"):
    d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=text,
                           dimstyle=STYLE, dxfattribs=ATTR)
    d.render()
    return d


# ---- 底部：孔的水平定位 25、孔距 110；总长 160 ----
lin((0, 0), (25, 14), base=(0, -12))                 # 左孔中心距左边 25
lin((25, 14), (135, 14), base=(0, -12))              # 孔距 110
lin((0, 0), (160, 0), base=(0, -26))                 # 总长 160

# ---- 左侧：孔的竖直定位 25、腰形槽中心高 62；总高 90 ----
lin((0, 0), (14, 25), base=(-12, 0), angle=90)       # 孔中心距底边 25
lin((0, 0), (56, 62), base=(-24, 0), angle=90)       # 槽中心线距底边 62
lin((0, 90), (0, 0), base=(-38, 0), angle=90)        # 总高 90

# ---- 腰形槽：水平位置 60、长度 40、宽度 12（标在零件内部空白处）----
lin((0, 62), (60, 62), base=(0, 46))                 # 槽左端距左边 60
lin((60, 62), (100, 62), base=(0, 78))               # 槽长 40
lin((94, 56), (94, 68), base=(110, 0), angle=90)     # 槽宽 12

# ---- 右上角倒角 10×10（45°）----
lin((150, 90), (160, 90), base=(0, 100))             # 倒角水平边 10
lin((160, 80), (160, 90), base=(172, 0), angle=90)   # 倒角竖直边 10

# ---- 孔径：2×Φ14（两孔相同，只标一次）----
# ezdxf 的直径标注会自动在 <> 前加 Φ，这里只补 "2×"；文字水平放置
d = msp.add_diameter_dim(center=(25, 25), radius=7, location=(46, 38),
                         text="2×<>", dimstyle=STYLE,
                         override={"dimtih": 1, "dimtoh": 1},
                         dxfattribs=ATTR)
d.render()

doc.saveas(FN)
print("saved")
