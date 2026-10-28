# Round 4: revert round 2 (holes Dia.12 -> Dia.10 and the 4X callout), keep rounds 1 and 3.
# Restores exactly the attributes round 2 changed, taking the values from the round-1 state
# (part_r1_backup.dxf). Always rebuilds from the round-3 backup so re-running is safe.
import os
import shutil
import ezdxf
from ezdxf.math import Vec3

D = r"C:\Users\HUAWEI\AppData\Local\Temp\claude\D--Projects-AgentCAD\d6ee3478-e055-493d-8b14-3ab652e01571\scratchpad\cc_hardB\H1_r2"
SRC = DST = os.path.join(D, "part.dxf")
BACKUP = os.path.join(D, "part_r3_backup.dxf")
R1 = os.path.join(D, "part_r1_backup.dxf")
R2 = os.path.join(D, "part_r2_backup.dxf")

if not os.path.exists(BACKUP):
    shutil.copyfile(SRC, BACKUP)

doc = ezdxf.readfile(BACKUP)
r1 = ezdxf.readfile(R1).entitydb
r2 = ezdxf.readfile(R2).entitydb
db = doc.entitydb

# (handle, attribute) pairs touched by round 2 (see modify_r2.py / diff r1 vs r2)
ROUND2 = [
    ("92", "radius"), ("93", "radius"), ("94", "radius"), ("95", "radius"),
    ("D2", "defpoint"), ("D2", "defpoint4"),          # diameter DIMENSION
    ("D6", "insert"), ("D8", "insert"),               # *D5 arrows
    ("DA", "start"), ("DA", "end"),                   # *D5 dimension line
    ("DB", "start"),                                  # *D5 leader
    ("DF", "location"),                               # *D5 defpoint marker
]


def same(a, b):
    if isinstance(a, float):
        return abs(a - b) < 1e-9
    return Vec3(a).isclose(Vec3(b), abs_tol=1e-9)


for h, attr in ROUND2:
    cur = doc.entitydb[h].dxf.get(attr)
    # must still be the round-2 value (round 3 did not touch it)
    assert same(cur, r2[h].dxf.get(attr)), (h, attr, cur)
    db[h].dxf.set(attr, r1[h].dxf.get(attr))

assert db["DD"].text == "4X %%c12", db["DD"].text
db["DD"].text = r1["DD"].text  # "4X %%c10"

doc.saveas(DST)
print("saved")
