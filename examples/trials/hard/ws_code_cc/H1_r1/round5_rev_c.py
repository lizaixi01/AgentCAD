import shutil
import ezdxf

shutil.copyfile("part.dxf", "part_before_r5.bak")

doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

tb = [e for e in msp.query("INSERT") if e.dxf.name == "TB"][0]
rev = tb.get_attrib("REV")
print("REV before:", rev.dxf.text)
rev.dxf.text = "C"

# free area below the plate: right of the notes MTEXT (x 0..~30), left of the
# title block (x >= 130), below the width dim (y >= -16.25); baseline aligned
# with the first notes line
txt = msp.add_text(
    "REV C: 宽度 150，增加中心孔 %%c30",
    height=3.5,
    dxfattribs={"layer": "NOTES", "style": "Standard"},
)
txt.set_placement((40, -33.5))
print("new TEXT handle:", txt.dxf.handle)

doc.saveas("part.dxf")
