import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

# model extents incl. dimensions
ext = bbox.extents(msp)
mcx = (ext.extmin.x + ext.extmax.x) / 2
mcy = (ext.extmin.y + ext.extmax.y) / 2
print("model extents", ext.extmin, ext.extmax, "center", (mcx, mcy))

if "A3" in doc.layouts.names():
    doc.layouts.delete("A3")
layout = doc.layouts.new("A3")
layout.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm",
                  offset=(0, 0), rotation=0, scale=1)
# page_setup leaves the paper-space main viewport (id 1) with odd huge
# values; reset it to the sheet so the layout opens showing the A3 sheet
main_vp = layout.main_viewport()
if main_vp is not None:
    main_vp.dxf.center = (210, 148.5)
    main_vp.dxf.width = 420
    main_vp.dxf.height = 297
    main_vp.dxf.view_center_point = (210, 148.5)
    main_vp.dxf.view_height = 297

for name, color in (("FRAME", 7), ("TITLE", 7), ("VPORT", 8)):
    if name not in doc.layers:
        doc.layers.add(name, color=color)
doc.layers.get("VPORT").dxf.plot = 0  # viewport border not plotted

if "HZ" not in doc.styles:
    doc.styles.add("HZ", font="simsun.ttc")

# frames
W, H = 420, 297
L, R, B, T = 25, 415, 5, 292
layout.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True,
                      dxfattribs={"layer": "FRAME", "const_width": 0})
layout.add_lwpolyline([(L, B), (R, B), (R, T), (L, T)], close=True,
                      dxfattribs={"layer": "FRAME", "const_width": 0.7})

# title block 180 x 40 at inner bottom-right
tx0, ty0, tx1, ty1 = R - 180, B, R, B + 40
layout.add_lwpolyline([(tx0, ty0), (tx1, ty0), (tx1, ty1), (tx0, ty1)], close=True,
                      dxfattribs={"layer": "TITLE", "const_width": 0.5})
# columns: label 25 | value 65 | label 25 | value 65; rows of 20
xs = [tx0, tx0 + 25, tx0 + 90, tx0 + 115, tx1]
ym = ty0 + 20
layout.add_line((tx0, ym), (tx1, ym), dxfattribs={"layer": "TITLE"})
for x in xs[1:-1]:
    layout.add_line((x, ty0), (x, ty1), dxfattribs={"layer": "TITLE"})

cells = [
    # (col index, row top?, text, height)
    (0, True, "图名", 5), (1, True, "底板", 7),
    (2, True, "图号", 5), (3, True, "BP-300", 6),
    (0, False, "比例", 5), (1, False, "1:2", 6),
    (2, False, "材料", 5), (3, False, "Q235", 6),
]
for col, top, text, h in cells:
    cx = (xs[col] + xs[col + 1]) / 2
    cy = ym + 10 if top else ty0 + 10
    t = layout.add_text(text, height=h, dxfattribs={"layer": "TITLE", "style": "HZ"})
    t.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)

# viewport: 1:2 -> view height = 2 * paper height
vw, vh = 260, 180
vcx, vcy = (L + R) / 2, 165  # y range 75..255, above title block (top at 45)
vp = layout.add_viewport(center=(vcx, vcy), size=(vw, vh),
                         view_center_point=(mcx, mcy), view_height=vh * 2,
                         dxfattribs={"layer": "VPORT"})
vp.dxf.flags |= 16384  # display locked

doc.saveas("part.dxf")
print("saved")
