import math
import ezdxf

D_OUT, D_HOLE, PCD, D_BOLT, N = 150.0, 60.0, 110.0, 12.0, 6

doc = ezdxf.new("R2010", setup=True)
doc.units = ezdxf.units.MM
doc.header["$INSUNITS"] = 4
doc.header["$LTSCALE"] = 0.5
msp = doc.modelspace()

doc.layers.add("OUTLINE", color=7, lineweight=50)
doc.layers.add("CENTER", color=1, linetype="CENTER", lineweight=25)
doc.layers.add("DIM", color=3, lineweight=18)

# 轮廓
msp.add_circle((0, 0), D_OUT / 2, dxfattribs={"layer": "OUTLINE"})
msp.add_circle((0, 0), D_HOLE / 2, dxfattribs={"layer": "OUTLINE"})
holes = []
for k in range(N):
    a = math.radians(90 + k * 360 / N)  # 第一个孔在正上方
    c = (PCD / 2 * math.cos(a), PCD / 2 * math.sin(a))
    holes.append((c, a))
    msp.add_circle(c, D_BOLT / 2, dxfattribs={"layer": "OUTLINE"})

# 中心线
ext = D_OUT / 2 + 10
msp.add_line((-ext, 0), (ext, 0), dxfattribs={"layer": "CENTER"})
msp.add_line((0, -ext), (0, ext), dxfattribs={"layer": "CENTER"})
msp.add_circle((0, 0), PCD / 2, dxfattribs={"layer": "CENTER"})
# 螺栓孔径向短中心线（竖直/水平中心线已覆盖的孔除外）
r_in, r_out = PCD / 2 - D_BOLT / 2 - 3, PCD / 2 + D_BOLT / 2 + 3
for (c, a) in holes:
    if abs(math.cos(a)) < 1e-9:  # 上下两孔在竖直中心线上
        continue
    msp.add_line((r_in * math.cos(a), r_in * math.sin(a)),
                 (r_out * math.cos(a), r_out * math.sin(a)),
                 dxfattribs={"layer": "CENTER"})

# 标注
ovr = {"dimtxt": 3.5, "dimasz": 3.0, "dimtad": 0, "dimtmove": 0,
       "dimdec": 0, "dimzin": 8, "dimdsep": ord("."),
       "dimlfac": 1.0}  # EZDXF 样式默认 dimlfac=100（m→cm），图纸单位为 mm 需改回 1
attr = {"layer": "DIM"}

def pol(r, deg):
    return (r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)))

dims = [
    # (圆心, 半径, 角度, 文字位置, 文字)
    ((0, 0), D_OUT / 2, -15, pol(D_OUT / 2 + 18, -15), "<>"),
    ((0, 0), D_HOLE / 2, 45, pol(D_HOLE / 2 + 10, 45), "<>"),
    ((0, 0), PCD / 2, 135, pol(D_OUT / 2 + 18, 135), "<>"),
    (holes[0][0], D_BOLT / 2, 45,
     (holes[0][0][0] + 25, holes[0][0][1] + 25), "6×%%C12"),
]
for center, r, ang, loc, txt in dims:
    d = msp.add_diameter_dim(center=center, radius=r, angle=ang, location=loc,
                             text=txt, dimstyle="EZDXF", override=ovr,
                             dxfattribs=attr)
    d.render()

doc.saveas("flange.dxf")
print("saved flange.dxf")
