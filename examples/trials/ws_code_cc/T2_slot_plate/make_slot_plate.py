import math
import ezdxf

W, H, R = 160.0, 100.0, 8.0
SLOT_L, SLOT_W = 30.0, 10.0
SLOT_CENTERS = [(40.0, 50.0), (120.0, 50.0)]
HOLE_C, HOLE_D = (80.0, 50.0), 20.0

doc = ezdxf.new("R2010", setup=True)
doc.units = ezdxf.units.MM
for name, color in [("OUTLINE", 7), ("HOLES", 1), ("CENTER", 3), ("DIM", 4)]:
    doc.layers.add(name, color=color)
doc.layers.get("CENTER").dxf.linetype = "CENTER"
msp = doc.modelspace()

# 外形：带 R8 圆角的矩形（逆时针，90° 圆弧 bulge = tan(90°/4)）
b = math.tan(math.radians(90) / 4)
outline = [
    (R, 0, 0), (W - R, 0, b),
    (W, R, 0), (W, H - R, b),
    (W - R, H, 0), (R, H, b),
    (0, H - R, 0), (0, R, b),
]
msp.add_lwpolyline(outline, format="xyb", close=True, dxfattribs={"layer": "OUTLINE"})

# 长圆孔：直线段长 = 30 - 10 = 20，两端 R5 半圆
r = SLOT_W / 2
half = (SLOT_L - SLOT_W) / 2
for cx, cy in SLOT_CENTERS:
    pts = [
        (cx - half, cy - r, 0), (cx + half, cy - r, 1),
        (cx + half, cy + r, 0), (cx - half, cy + r, 1),
    ]
    msp.add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": "HOLES"})
    # 中心线
    msp.add_line((cx - SLOT_L / 2 - 4, cy), (cx + SLOT_L / 2 + 4, cy), dxfattribs={"layer": "CENTER"})
    msp.add_line((cx, cy - r - 4), (cx, cy + r + 4), dxfattribs={"layer": "CENTER"})

# 中心圆孔
msp.add_circle(HOLE_C, HOLE_D / 2, dxfattribs={"layer": "HOLES"})
hx, hy = HOLE_C
msp.add_line((hx - 14, hy), (hx + 14, hy), dxfattribs={"layer": "CENTER"})
msp.add_line((hx, hy - 14), (hx, hy + 14), dxfattribs={"layer": "CENTER"})

# ---------- 标注 ----------
# 注意：setup=True 生成的 "EZDXF" 标注样式 dimlfac=100（米→厘米），这里改用 Standard
da = {"layer": "DIM"}
ov = {"dimtxt": 3.5, "dimasz": 3.0, "dimdec": 0, "dimzin": 8, "dimlfac": 1.0, "dimtad": 1, "dimgap": 1.0}

# 总长 160
msp.add_linear_dim(base=(0, -15), p1=(0, 0), p2=(W, 0), angle=0,
                   dimstyle="Standard", override=ov, dxfattribs=da).render()
# 总宽 100
msp.add_linear_dim(base=(W + 15, 0), p1=(W, 0), p2=(W, H), angle=90,
                   dimstyle="Standard", override=ov, dxfattribs=da).render()
# 圆角 R8（左上角圆角，圆心 (8, 92)）
msp.add_radius_dim(center=(R, H - R), radius=R, angle=135,
                   dimstyle="Standard", override=ov, dxfattribs=da).render()
# 长圆孔长 30（左孔，标在上方）
c1x, c1y = SLOT_CENTERS[0]
msp.add_linear_dim(base=(0, c1y + 20), p1=(c1x - SLOT_L / 2, c1y), p2=(c1x + SLOT_L / 2, c1y),
                   angle=0, dimstyle="Standard", override=ov, dxfattribs=da).render()
# 长圆孔宽 10（左孔，标在左侧）
msp.add_linear_dim(base=(c1x - SLOT_L / 2 - 8, 0), p1=(c1x - half, c1y - r), p2=(c1x - half, c1y + r),
                   angle=90, dimstyle="Standard", override=ov, dxfattribs=da).render()
# 两长圆孔中心距 80
c2x, c2y = SLOT_CENTERS[1]
msp.add_linear_dim(base=(0, 20), p1=(c1x, c1y), p2=(c2x, c2y),
                   angle=0, dimstyle="Standard", override=ov, dxfattribs=da).render()
# 中心孔 Ø20
msp.add_diameter_dim(center=HOLE_C, radius=HOLE_D / 2, angle=45,
                     dimstyle="Standard", override=ov, dxfattribs=da).render()

doc.saveas("slot_plate.dxf")
print("saved slot_plate.dxf")
