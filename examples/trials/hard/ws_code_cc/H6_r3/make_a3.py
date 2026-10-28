import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

if "A3" in doc.layouts:
    doc.layouts.delete("A3")

# layers / style
for name, color, lw, plot in [
    ("FRAME", 7, 50, True),
    ("TITLE", 7, 25, True),
    ("TITLE_TEXT", 7, 25, True),
    ("VPORT", 8, 13, False),
]:
    if name not in doc.layers:
        layer = doc.layers.add(name, color=color, lineweight=lw)
        layer.dxf.plot = 1 if plot else 0
if "CN" not in doc.styles:
    doc.styles.add("CN", font="simfang.ttf")

# A3 landscape layout, paper 420x297, no margins -> layout origin == paper corner
a3 = doc.layouts.new("A3")
a3.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm",
              scale=(1, 1), name="ISO_A3_(420.00_x_297.00_MM)")

# frame
W, H = 420, 297
L, R, B, T = 25, 415, 5, 292
a3.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                  dxfattribs={"layer": "FRAME", "lineweight": 25})
a3.add_lwpolyline([(L, B), (R, B), (R, T), (L, T)], close=True,
                  dxfattribs={"layer": "FRAME", "lineweight": 70})

# title block 180x40 in lower right corner of inner frame
tx0, ty0 = R - 180, B          # 235, 5
tx1, ty1 = R, B + 40           # 415, 45
cols = [tx0, tx0 + 25, tx0 + 90, tx0 + 115, tx1]   # 235 260 325 350 415
rows = [ty0, ty0 + 10, ty0 + 20, ty0 + 30, ty1]    # 5 15 25 35 45
thin = {"layer": "TITLE", "lineweight": 25}
a3.add_lwpolyline([(tx0, ty0), (tx1, ty0), (tx1, ty1), (tx0, ty1)], close=True,
                  dxfattribs={"layer": "TITLE", "lineweight": 70})
# horizontal lines (left block rows 25..45 merged for drawing name)
for y in rows[1:3]:
    a3.add_line((tx0, y), (tx1, y), dxfattribs=thin)
a3.add_line((cols[2], rows[3]), (tx1, rows[3]), dxfattribs=thin)
for x in cols[1:4]:
    a3.add_line((x, ty0), (x, ty1), dxfattribs=thin)


def cell_text(text, x0, x1, y0, y1, h=3.5):
    t = a3.add_text(text, height=h, dxfattribs={"layer": "TITLE_TEXT", "style": "CN"})
    t.set_placement(((x0 + x1) / 2, (y0 + y1) / 2), align=TextEntityAlignment.MIDDLE_CENTER)


c, r = cols, rows
cell_text("图名", c[0], c[1], r[2], r[4])
cell_text("底板", c[1], c[2], r[2], r[4], h=7)
cell_text("图号", c[2], c[3], r[3], r[4])
cell_text("BP-300", c[3], c[4], r[3], r[4], h=5)
cell_text("比例", c[2], c[3], r[2], r[3])
cell_text("1:2", c[3], c[4], r[2], r[3], h=5)
cell_text("材料", c[0], c[1], r[1], r[2])
cell_text("Q235", c[1], c[2], r[1], r[2], h=5)
cell_text("数量", c[2], c[3], r[1], r[2])
cell_text("1", c[3], c[4], r[1], r[2])
cell_text("制图", c[0], c[1], r[0], r[1])
cell_text("审核", c[2], c[3], r[0], r[1])

# viewport at 1:2, part (incl. dimensions) centred on the frame
ext = bbox.extents(msp)
mcx, mcy = ext.center.x, ext.center.y
vp_cx, vp_cy = (L + R) / 2, (B + T) / 2           # 220, 148.5 (inner frame centre)
vp_w = (R - 5) - (L + 5)                          # 380
vp_h = 2 * (vp_cy - (ty1 + 5))                    # symmetric, keeps 5 mm above title block
scale = 0.5
vp = a3.add_viewport(center=(vp_cx, vp_cy), size=(vp_w, vp_h),
                     view_center_point=(mcx, mcy), view_height=vp_h / scale,
                     dxfattribs={"layer": "VPORT"})
vp.dxf.flags = vp.dxf.flags | 16384  # display locked

doc.saveas("part.dxf")
print("model extents", ext.extmin, ext.extmax, "vp size", vp_w, vp_h)
