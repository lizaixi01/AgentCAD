import os
import sys
import ezdxf
from ezdxf import bbox

sys.stdout.reconfigure(encoding="utf-8")
W = os.path.dirname(os.path.abspath(__file__))
doc = ezdxf.readfile(os.path.join(W, "part.dxf"))
msp = doc.modelspace()

ins = doc.entitydb["ED"]
print("REV attrib:", repr(ins.get_attrib_text("REV")), "PART_NO:", repr(ins.get_attrib_text("PART_NO")))

notes = [e for e in msp.query("MTEXT") if e.dxf.handle != "E0"]
assert len(notes) == 1, notes
n = notes[0]
print("note:", n.dxf.handle, n.dxf.layer, repr(n.text), "plain:", repr(n.plain_text()),
      "ins", tuple(n.dxf.insert), "h", n.dxf.char_height, "style", n.dxf.style)
nb = bbox.extents([n], fast=False)
print(f"note bbox x[{nb.extmin.x:.2f},{nb.extmax.x:.2f}] y[{nb.extmin.y:.2f},{nb.extmax.y:.2f}]")

plate = bbox.extents([doc.entitydb["91"]])
assert nb.extmax.y < plate.extmin.y, "note must be below plate"
clash = []
for e in msp:
    if e is n:
        continue
    b = bbox.extents([e], fast=False)
    if not b.has_data:
        continue
    if (b.extmin.x < nb.extmax.x and b.extmax.x > nb.extmin.x
            and b.extmin.y < nb.extmax.y and b.extmax.y > nb.extmin.y):
        clash.append((e.dxftype(), e.dxf.handle))
print("bbox overlaps with note:", clash or "none")
print("audit errors:", len(doc.audit().errors))
