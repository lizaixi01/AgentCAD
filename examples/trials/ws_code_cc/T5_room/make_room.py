import ezdxf

L, W = 6000, 4000          # 轴线尺寸
T = 120                    # 半墙厚
DOOR, WIN = 900, 1500
cx = L / 2
d1, d2 = cx - DOOR / 2, cx + DOOR / 2      # 门洞 2550..3450
w1, w2 = cx - WIN / 2, cx + WIN / 2        # 窗洞 2250..3750

doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4                # mm
doc.header["$LTSCALE"] = 20
doc.layers.add("AXIS", color=1, linetype="DASHDOT")
doc.layers.add("WALL", color=7, lineweight=50)
doc.layers.add("WINDOW", color=4)
doc.layers.add("DIM", color=3)

ds = doc.dimstyles.new("ARCH")
ds.dxf.dimtxt = 250
ds.dxf.dimasz = 150
ds.dxf.dimtsz = 120         # 建筑斜短线
ds.dxf.dimexe = 150
ds.dxf.dimexo = 200
ds.dxf.dimgap = 80
ds.dxf.dimdec = 0
ds.dxf.dimtad = 1
ds.dxf.dimclrd = 3
ds.dxf.dimclre = 3

msp = doc.modelspace()

# ---- 轴线 ----
ext = 800
for x in (0, L):
    msp.add_line((x, -T - ext), (x, W + T + ext), dxfattribs={"layer": "AXIS"})
for y in (0, W):
    msp.add_line((-T - ext, y), (L + T + ext, y), dxfattribs={"layer": "AXIS"})

# ---- 墙线 ----
def wl(p, q):
    msp.add_line(p, q, dxfattribs={"layer": "WALL"})

xo0, xo1, yo0, yo1 = -T, L + T, -T, W + T      # 外墙线
xi0, xi1, yi0, yi1 = T, L - T, T, W - T        # 内墙线
# 西墙、东墙（完整）
wl((xo0, yo0), (xo0, yo1)); wl((xi0, yi0), (xi0, yi1))
wl((xo1, yo0), (xo1, yo1)); wl((xi1, yi0), (xi1, yi1))
# 南墙：门洞处断开
for y, xa, xb in ((yo0, xo0, xo1), (yi0, xi0, xi1)):
    wl((xa, y), (d1, y)); wl((d2, y), (xb, y))
# 北墙：窗洞处断开
for y, xa, xb in ((yo1, xo0, xo1), (yi1, xi0, xi1)):
    wl((xa, y), (w1, y)); wl((w2, y), (xb, y))
# 洞口封口
for x in (d1, d2):
    wl((x, yo0), (x, yi0))
for x in (w1, w2):
    wl((x, yi1), (x, yo1))

# ---- 窗：四条平行线 ----
for y in (yo1, W + T / 3, W - T / 3, yi1):
    msp.add_line((w1, y), (w2, y), dxfattribs={"layer": "WINDOW"})

# ---- 尺寸标注 ----
da = {"layer": "DIM"}
msp.add_linear_dim(base=(0, -1300), p1=(0, 0), p2=(L, 0), dimstyle="ARCH", dxfattribs=da).render()
msp.add_linear_dim(base=(0, -650), p1=(d1, -T), p2=(d2, -T), dimstyle="ARCH", dxfattribs=da).render()
msp.add_linear_dim(base=(-1300, 0), p1=(0, 0), p2=(0, W), angle=90, dimstyle="ARCH", dxfattribs=da).render()
msp.add_linear_dim(base=(0, W + 650), p1=(w1, W + T), p2=(w2, W + T), dimstyle="ARCH", dxfattribs=da).render()

doc.saveas("room.dxf")
print("saved room.dxf")
