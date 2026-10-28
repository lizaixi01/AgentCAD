import os, shutil
import ezdxf
from ezdxf import const

SRC = "part.dxf"
BAK = "part_orig.dxf"
if not os.path.exists(BAK):
    shutil.copy(SRC, BAK)

doc = ezdxf.readfile(BAK)
msp = doc.modelspace()

STD = {  # name: (color, linetype, lineweight in 1/100 mm)
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

R = 6  # rounding for geometry comparison


def pt(v):
    return tuple(round(c, R) for c in v)


def key(e):
    t = e.dxftype()
    if t == "LINE":
        a, b = sorted([pt(e.dxf.start), pt(e.dxf.end)])
        return (t, a, b)
    if t == "CIRCLE":
        return (t, pt(e.dxf.center), round(e.dxf.radius, R))
    if t == "ARC":
        return (t, pt(e.dxf.center), round(e.dxf.radius, R),
                round(e.dxf.start_angle % 360, R), round(e.dxf.end_angle % 360, R))
    if t == "LWPOLYLINE":
        return (t, e.closed, tuple(tuple(round(c, R) for c in p) for p in e.get_points("xyb")))
    if t == "TEXT":
        return (t, e.dxf.text, pt(e.dxf.insert), round(e.dxf.height, R))
    if t == "MTEXT":
        return (t, e.text, pt(e.dxf.insert), round(e.dxf.char_height, R))
    if t == "DIMENSION":
        return (t, e.dxf.dimtype, pt(e.dxf.defpoint), pt(e.dxf.defpoint2),
                pt(e.dxf.defpoint3), pt(e.dxf.defpoint4), pt(e.dxf.text_midpoint), e.dxf.text)
    return (t, e.dxf.handle)  # unknown type: never treated as duplicate


def describe(e):
    t = e.dxftype()
    if t == "LINE":
        return f"LINE #{e.dxf.handle} {pt(e.dxf.start)[:2]}->{pt(e.dxf.end)[:2]}"
    if t == "CIRCLE":
        return f"CIRCLE #{e.dxf.handle} c={pt(e.dxf.center)[:2]} r={e.dxf.radius}"
    return f"{t} #{e.dxf.handle}"


removed = []

# 1) zero-length lines
for e in list(msp.query("LINE")):
    if (e.dxf.end - e.dxf.start).magnitude < 1e-9:
        removed.append((describe(e), "长度为0的线"))
        msp.delete_entity(e)

# 2) exact duplicates (same type + same geometry), keep the first one
seen = {}
for e in list(msp):
    k = key(e)
    if k in seen:
        removed.append((describe(e), f"与 #{seen[k]} 完全重合"))
        msp.delete_entity(e)
    else:
        seen[k] = e.dxf.handle

# 3) lines lying exactly on a straight segment of a polyline
segs = {}
for pl in msp.query("LWPOLYLINE"):
    pts = list(pl.get_points("xyb"))
    n = len(pts)
    for i in range(n if pl.closed else n - 1):
        p, q = pts[i], pts[(i + 1) % n]
        if abs(p[2]) < 1e-12:
            a = (round(p[0], R), round(p[1], R), 0.0)
            b = (round(q[0], R), round(q[1], R), 0.0)
            segs[tuple(sorted([a, b]))] = pl.dxf.handle
for e in list(msp.query("LINE")):
    k = key(e)[1:]
    if k in segs:
        removed.append((describe(e), f"与多段线 #{segs[k]} 的一条边完全重合"))
        msp.delete_entity(e)

# 4) assign layers, set color/linetype/lineweight to ByLayer
circle_centers = [pt(c.dxf.center)[:2] for c in msp.query("CIRCLE ARC")]


def is_centerline(line):
    s, t = line.dxf.start, line.dxf.end
    mid = ((s.x + t.x) / 2, (s.y + t.y) / 2)
    return line.dxf.color == 1 or any(
        abs(mid[0] - c[0]) < 1e-6 and abs(mid[1] - c[1]) < 1e-6 for c in circle_centers)


for e in msp:
    t = e.dxftype()
    if t in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE"):
        layer = "OUTLINE"
    elif t == "LINE":
        layer = "CENTER" if is_centerline(e) else "OUTLINE"
    elif t == "DIMENSION":
        layer = "DIM"
    elif t in ("TEXT", "MTEXT"):
        layer = "TEXT"
    else:
        raise RuntimeError(f"未处理的实体类型 {t}")
    e.dxf.layer = layer
    e.dxf.color = const.BYLAYER
    e.dxf.linetype = "BYLAYER"
    e.dxf.lineweight = const.LINEWEIGHT_BYLAYER

# 5) dimension blocks: hard-coded colors -> ByBlock so they follow the DIM layer
for dim in msp.query("DIMENSION"):
    blk = doc.blocks.get(dim.dxf.geometry)
    for be in blk:
        if be.dxf.layer != "Defpoints":
            be.dxf.color = const.BYBLOCK
            if be.dxf.hasattr("linetype"):
                be.dxf.linetype = "BYBLOCK"
            if be.dxf.hasattr("lineweight"):
                be.dxf.lineweight = const.LINEWEIGHT_BYBLOCK
ds = doc.dimstyles.get("EZDXF")
for attr in ("dimclrd", "dimclre", "dimclrt"):
    print("EZDXF", attr, ds.dxf.get(attr))
    ds.dxf.set(attr, 0)  # ByBlock

# 6) center line pattern: lines are only 20..48 mm, scale the CENTER pattern so it is visible
doc.header["$LTSCALE"] = 0.3

# 7) purge empty layers (keep 0 / Defpoints / standard layers)
used = {e.dxf.layer for e in doc.entitydb.values() if e.dxf.hasattr("layer")}
keep = {"0", "DEFPOINTS"} | set(STD)
removed_layers = []
for layer in list(doc.layers):
    name = layer.dxf.name
    if name.upper() in keep:
        continue
    if name not in used:
        removed_layers.append(name)
        doc.layers.remove(name)

doc.saveas(SRC)

print("删除的对象:")
for d, why in removed:
    print("  ", d, "-", why)
print("删除的图层:", removed_layers)
