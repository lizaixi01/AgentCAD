# Round 5: title block REV -> C, add revision note below the plate.
# Always rebuilds from part_r4_backup.dxf (round-4 state).
import os
import shutil
import ezdxf
from ezdxf.enums import MTextEntityAlignment

W = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(W, "part.dxf")
BAK = os.path.join(W, "part_r4_backup.dxf")
if not os.path.exists(BAK):
    shutil.copy2(SRC, BAK)

doc = ezdxf.readfile(BAK)
msp = doc.modelspace()

tb = doc.entitydb["ED"]
assert tb.dxftype() == "INSERT" and tb.dxf.name == "TB"
rev = tb.get_attrib("REV")
assert rev is not None and rev.dxf.handle == "F0"
rev.dxf.text = "C"

# Free area: right of notes MTEXT E0 (x<=29.34), left of title block (x>=130),
# below width dimension (y>=-16.25). Top aligned with the notes (y=-30).
note = msp.add_mtext(
    "REV C: 宽度 150，增加中心孔 %%c30",
    # explicit width keeps it a single line (x 35..120, left of title block)
    dxfattribs={"layer": "NOTES", "style": "Standard", "char_height": 3.5, "width": 85},
)
note.set_location((35, -30), attachment_point=MTextEntityAlignment.TOP_LEFT)

doc.saveas(SRC)
print("saved, REV =", rev.dxf.text, "note handle =", note.dxf.handle)
