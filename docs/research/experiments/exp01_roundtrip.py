"""exp01: 写 R2010 DXF（LINE/CIRCLE/ARC/LWPOLYLINE(bulge)/TEXT/MTEXT/线性标注/半径标注），保存、重载，比较句柄与组码。"""
import sys, pathlib, math
import ezdxf
from ezdxf.math import bulge_to_arc

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
fn = out / "exp01_r2010.dxf"

doc = ezdxf.new("R2010", setup=True)
print("ezdxf", ezdxf.__version__, "| new() acadver:", doc.dxfversion, doc.acad_release)
print("header defaults: $INSUNITS=", doc.header.get("$INSUNITS"), "$MEASUREMENT=", doc.header.get("$MEASUREMENT"),
      "$LUNITS=", doc.header.get("$LUNITS"), "$AUNITS=", doc.header.get("$AUNITS"),
      "$ANGBASE=", doc.header.get("$ANGBASE"), "$ANGDIR=", doc.header.get("$ANGDIR"),
      "$DIMASSOC=", doc.header.get("$DIMASSOC"), "$MIRRTEXT=", doc.header.get("$MIRRTEXT"))
print("doc.units =", doc.units)
msp = doc.modelspace()
doc.layers.add("WALL", color=1, linetype="DASHED")
ents = {}
ents["line"] = msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALL"})
ents["circle"] = msp.add_circle((50, 50), radius=25)
ents["arc"] = msp.add_arc((0, 0), radius=10, start_angle=-90, end_angle=450)  # 非规范化角度
ents["arc2"] = msp.add_arc((0, 0), radius=10, start_angle=370, end_angle=10)  # >360
pl = msp.add_lwpolyline([(0, 0, 0, 0, 1.0), (10, 0, 0, 0, 0), (10, 10)], format="xyseb")  # 第一段 bulge=1 (半圆)
ents["lwpoly"] = pl
ents["text"] = msp.add_text("Hello 中文", height=2.5, dxfattribs={"rotation": 30}).set_placement((5, 5))
ents["mtext"] = msp.add_mtext(r"Line1\PLine2", dxfattribs={"char_height": 2.5, "insert": (0, -20)})
d1 = msp.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(100, 0), dimstyle="EZDXF")
d1.render()
ents["dimlin"] = d1.dimension
d2 = msp.add_radius_dim(center=(50, 50), radius=25, angle=45, dimstyle="EZ_RADIUS")
d2.render()
ents["dimrad"] = d2.dimension
handles_before = {k: e.dxf.handle for k, e in ents.items()}
print("handles before save:", handles_before)
print("$HANDSEED before save:", doc.header["$HANDSEED"] if "$HANDSEED" in doc.header else "(not set until save)")
print("arc dxf angles as stored:", ents["arc"].dxf.start_angle, ents["arc"].dxf.end_angle, "|", ents["arc2"].dxf.start_angle, ents["arc2"].dxf.end_angle)
print("dimlin: geometry block =", ents["dimlin"].dxf.geometry, " actual_measurement(42) =", ents["dimlin"].dxf.get("actual_measurement"),
      " get_measurement() =", ents["dimlin"].get_measurement())
print("dimrad: geometry block =", ents["dimrad"].dxf.geometry, " 42 =", ents["dimrad"].dxf.get("actual_measurement"))
# bulge 数学
s, e, b = (0, 0), (10, 0), 1.0
c, sa, ea, r = bulge_to_arc(s, e, b)
print(f"bulge_to_arc(start=(0,0), end=(10,0), bulge=1) -> center={tuple(round(v,6) for v in c)}, start_angle(rad)={sa:.6f}, end_angle(rad)={ea:.6f}, r={r}")
doc.saveas(fn)
print("saved", fn.name, "size", fn.stat().st_size, "bytes; $HANDSEED after save:", doc.header["$HANDSEED"])

doc2 = ezdxf.readfile(fn)
msp2 = doc2.modelspace()
by_handle = {e.dxf.handle: e for e in msp2}
for k, h in handles_before.items():
    e2 = doc2.entitydb.get(h)
    print(f"reload {k:7s} handle {h:>4s} -> {e2.dxftype() if e2 else None}")
print("reloaded acadver:", doc2.dxfversion, " $HANDSEED:", doc2.header["$HANDSEED"], " $INSUNITS:", doc2.header.get("$INSUNITS"))
a2 = doc2.entitydb[handles_before["arc"]]
print("reloaded arc angles:", a2.dxf.start_angle, a2.dxf.end_angle)
dl = doc2.entitydb[handles_before["dimlin"]]
print("reloaded dimlin 42:", dl.dxf.get("actual_measurement"), " block:", dl.dxf.geometry,
      " block exists:", dl.dxf.geometry in doc2.blocks, " block entity types:", sorted({x.dxftype() for x in doc2.blocks[dl.dxf.geometry]}))
lw = doc2.entitydb[handles_before["lwpoly"]]
print("reloaded lwpoly points (x,y,sw,ew,bulge):", list(lw.get_points("xyseb")), " closed:", lw.closed)
t2 = doc2.entitydb[handles_before["text"]]
print("reloaded text:", ascii(t2.dxf.text), " insert:", t2.dxf.insert, " rotation:", t2.dxf.rotation)

# 组码级转储（从文本文件读取原始 tag）
from ezdxf.lldxf.tagger import ascii_tags_loader
raw = fn.read_text(encoding="utf8")
def dump_entity(handle, maxtags=60):
    tags = list(ascii_tags_loader(__import__("io").StringIO(raw)))
    for i, t in enumerate(tags):
        if t.code == 5 and t.value == handle:
            j = i - 1
            out_tags = [tags[j]]
            k = i
            while k < len(tags) and tags[k].code != 0 and len(out_tags) < maxtags:
                out_tags.append(tags[k]); k += 1
            return out_tags
    return []
for k in ("line", "circle", "arc", "lwpoly", "text", "dimlin"):
    print(f"--- raw group codes for {k} ({handles_before[k]}) ---")
    print("  " + " | ".join(f"{t.code}:{ascii(t.value) if t.code==1 else t.value}" for t in dump_entity(handles_before[k])))
