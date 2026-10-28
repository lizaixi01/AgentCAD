import ezdxf
from ezdxf.math import Vec3
from ezdxf.lldxf import const

TOL = 1e-6
doc = ezdxf.readfile("part.dxf")
msp = doc.modelspace()

# 1. layer standard
STD = {
    "OUTLINE": (7, "Continuous", 50),
    "CENTER": (1, "CENTER", 25),
    "DIM": (3, "Continuous", 25),
    "TEXT": (4, "Continuous", 25),
}
for name, (color, lt, lw) in STD.items():
    if name in doc.layers:
        layer = doc.layers.get(name)
    else:
        layer = doc.layers.add(name)
    layer.color = color
    layer.dxf.linetype = lt
    layer.dxf.lineweight = lw

deleted = []

# 2. zero-length lines
for e in list(msp.query("LINE")):
    if Vec3(e.dxf.start).isclose(Vec3(e.dxf.end), abs_tol=TOL):
        deleted.append(f"{e.dxf.handle} LINE 零长度 at {tuple(e.dxf.start)}")
        msp.delete_entity(e)

# 3. exact duplicates
def seg_key(a, b):
    a, b = Vec3(a).round(6), Vec3(b).round(6)
    return tuple(sorted([tuple(a), tuple(b)]))

seen = {}
for e in list(msp):
    t = e.dxftype()
    if t == "CIRCLE":
        key = ("CIRCLE", tuple(Vec3(e.dxf.center).round(6)), round(e.dxf.radius, 6))
    elif t == "LINE":
        key = ("SEG",) + seg_key(e.dxf.start, e.dxf.end)
    else:
        continue
    if key in seen:
        deleted.append(f"{e.dxf.handle} {t} 与 {seen[key]} 完全重合 {key}")
        msp.delete_entity(e)
    else:
        seen[key] = e.dxf.handle

# lines lying exactly on a straight polyline edge (fully coincident)
for pl in msp.query("LWPOLYLINE"):
    pts = [Vec3(p[0], p[1]) for p in pl.get_points("xyb")]
    bulges = [p[2] for p in pl.get_points("xyb")]
    n = len(pts)
    edges = set()
    for i in range(n if pl.closed else n - 1):
        if abs(bulges[i]) < TOL:
            edges.add(seg_key(pts[i], pts[(i + 1) % n]))
    for e in list(msp.query("LINE")):
        if seg_key(e.dxf.start, e.dxf.end) in edges:
            deleted.append(f"{e.dxf.handle} LINE 与多段线 {pl.dxf.handle} 的边完全重合 "
                           f"{tuple(e.dxf.start)}->{tuple(e.dxf.end)}")
            msp.delete_entity(e)

# 4. assign layers, set properties ByLayer
def target_layer(e):
    t = e.dxftype()
    if t in ("LWPOLYLINE", "CIRCLE", "ARC", "POLYLINE"):
        return "OUTLINE"
    if t == "LINE":
        # remaining lines: red ones are center lines; others would be outline
        return "CENTER" if e.dxf.get("color") == 1 else "OUTLINE"
    if t == "DIMENSION":
        return "DIM"
    if t in ("TEXT", "MTEXT"):
        return "TEXT"
    raise ValueError(f"unhandled {t} {e.dxf.handle}")

for e in msp:
    e.dxf.layer = target_layer(e)
    e.dxf.color = const.BYLAYER
    e.dxf.linetype = "BYLAYER"
    e.dxf.lineweight = const.LINEWEIGHT_BYLAYER
    for attr in ("true_color", "color_name", "transparency"):
        if e.dxf.hasattr(attr):
            e.dxf.discard(attr)

# dimension block contents: hard-coded color 3 -> BYBLOCK so they follow the
# DIMENSION entity (ByLayer -> DIM). Geometry untouched.
for dim in msp.query("DIMENSION"):
    blk = doc.blocks.get(dim.dxf.geometry)
    for be in blk:
        if be.dxf.layer != "Defpoints":
            be.dxf.color = const.BYBLOCK

# 5. remove empty layers
used = set()
for layout in doc.layouts:
    for e in layout:
        used.add(e.dxf.layer.upper())
for blk in doc.blocks:
    for e in blk:
        used.add(e.dxf.layer.upper())
    used.add(blk.block.dxf.layer.upper())
removed_layers = []
for layer in list(doc.layers):
    name = layer.dxf.name
    if name.upper() in ("0", "DEFPOINTS") or name in STD:
        continue
    if name.upper() not in used:
        doc.layers.remove(name)
        removed_layers.append(name)

if doc.header.get("$CLAYER", "0") not in doc.layers:
    doc.header["$CLAYER"] = "0"
doc.header["$LWDISPLAY"] = 1

doc.saveas("part.dxf")
print("deleted entities:")
for d in deleted:
    print("  ", d)
print("removed layers:", removed_layers)
