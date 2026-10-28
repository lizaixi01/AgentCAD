"""Round 5: TB block REV attribute A -> C, add revision note below the plate."""
import os
import shutil
import sys

import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "part.dxf")
BACKUP = os.path.join(HERE, "part_r4_final.dxf")
NOTE = "REV C: 宽度 150，增加中心孔 %%c30"

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()

if any(e.dxftype() == "TEXT" and e.dxf.text.startswith("REV C") for e in msp):
    sys.exit("round 5 already applied - refusing to run twice")

shutil.copyfile(SRC, BACKUP)

tb = [e for e in msp.query("INSERT") if e.dxf.name == "TB"]
assert len(tb) == 1, tb
rev = tb[0].get_attrib("REV")
assert rev is not None and rev.dxf.text == "A", rev
rev.dxf.text = "C"

# free band between the lowest dimension (y=-16.25) and the notes/title block (y=-25)
msp.add_text(
    NOTE,
    height=3.5,
    dxfattribs={"layer": "NOTES", "style": "Standard", "insert": (0, -24)},
)

doc.saveas(SRC)
print("saved", SRC, "backup", BACKUP)
