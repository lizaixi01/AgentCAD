"""exp03: 精度、句柄分配/复用、镜像与 OCS、XDATA/XRECORD、R12 兼容、输出确定性。"""
import sys, pathlib, math, io, hashlib
import ezdxf
from ezdxf.math import Matrix44, Vec3, OCS

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
def attempt(label, fn):
    try: print(f"[{label}] OK -> {fn()}")
    except Exception as e: print(f"[{label}] {type(e).__name__}: {str(e)[:150]}")

# 1) 浮点精度 round-trip
doc = ezdxf.new("R2010"); msp = doc.modelspace()
vals = [0.1 + 0.2, math.pi, 1e-12, 123456789.123456789, 1/3]
ln = msp.add_line((vals[0], vals[1]), (vals[3], vals[4]))
s = io.StringIO(); doc.write(s); txt = s.getvalue()
i = txt.find("AcDbLine\n");print("raw LINE coordinate tags:", txt[i:i+150].replace("\n", "|"))
doc2 = ezdxf.read(io.StringIO(txt)); l2 = doc2.entitydb[ln.dxf.handle]
print("float round-trip exact:", tuple(l2.dxf.start)[:2] == (vals[0], vals[1]) and tuple(l2.dxf.end)[:2] == (vals[3], vals[4]))

# 2) 句柄分配与删除后是否复用
doc = ezdxf.new("R2010"); msp = doc.modelspace()
a = msp.add_line((0, 0), (1, 0)); h_a = a.dxf.handle
msp.delete_entity(a)
b = msp.add_line((0, 0), (2, 0))
print(f"handle deleted={h_a}, next new={b.dxf.handle}, reused={h_a == b.dxf.handle}")
c = b.copy(); msp.add_entity(c)
print(f"copy() handle before add: assigned on add -> {c.dxf.handle} (orig {b.dxf.handle})")
print("is_alive after delete:", a.is_alive)

# 3) 镜像（MIRROR 等价）：圆弧/文字经过 scale(-1,1,1) 变换
doc = ezdxf.new("R2010"); msp = doc.modelspace()
arc = msp.add_arc((10, 0), 5, start_angle=0, end_angle=90)
txt_e = msp.add_text("ABC", height=1).set_placement((10, 0))
circ = msp.add_circle((10, 0), 5)
m = Matrix44.scale(-1, 1, 1)
for e in (arc, txt_e, circ): e.transform(m)
print("mirrored ARC: center", arc.dxf.center, "extrusion", arc.dxf.extrusion, "angles", round(arc.dxf.start_angle, 6), round(arc.dxf.end_angle, 6))
print("  ARC WCS start/end points:", [tuple(round(v, 6) for v in p) for p in (arc.start_point, arc.end_point)])
print("mirrored CIRCLE: center(OCS)", circ.dxf.center, "extrusion", circ.dxf.extrusion)
print("mirrored TEXT: insert", txt_e.dxf.insert, "rotation", txt_e.dxf.rotation, "text_generation_flag(71)", txt_e.dxf.get("text_generation_flag"), "extrusion", txt_e.dxf.extrusion)
# OCS: extrusion (0,0,-1) 时 OCS x 轴
ocs = OCS((0, 0, -1)); print("OCS(0,0,-1) ux,uy,uz =", ocs.ux, ocs.uy, ocs.uz, "| to_wcs((15,0,0)) =", ocs.to_wcs((15, 0, 0)))

# 4) XDATA / 字典 / XRECORD
doc = ezdxf.new("R2010"); msp = doc.modelspace()
doc.appids.add("AGENTCAD")
e = msp.add_line((0, 0), (1, 1))
e.set_xdata("AGENTCAD", [(1000, "op:42"), (1040, 3.14), (1071, 7)])
xd = doc.rootdict.add_new_dict("AGENTCAD_META")
xr = xd.add_xrecord("RUN")
xr.reset([(1, "schema=1"), (40, 1.5), (90, 12345)])
s = io.StringIO(); doc.write(s); t = s.getvalue()
d2 = ezdxf.read(io.StringIO(t))
print("xdata round-trip:", d2.entitydb[e.dxf.handle].get_xdata("AGENTCAD"))
print("xrecord round-trip:", list(d2.rootdict["AGENTCAD_META"]["RUN"].tags))
attempt("set_xdata with unregistered appid", lambda: (msp.add_line((0,0),(1,0)).set_xdata("NOT_REG", [(1000,"x")]), "accepted")[1])
big = msp.add_line((0, 0), (1, 0))
big.set_xdata("AGENTCAD", [(1000, "x" * 255)] * 70)
attempt("audit >16KB xdata", lambda: (lambda a: [(f.message[:70]) for f in a.errors + a.fixes][:2] or "no complaints")(doc.audit()))

# 5) R12: LWPOLYLINE 支持?
d12 = ezdxf.new("R12"); m12 = d12.modelspace()
attempt("R12 add_lwpolyline", lambda: m12.add_lwpolyline([(0, 0), (1, 0)]).dxftype())
attempt("R12 add_polyline2d", lambda: m12.add_polyline2d([(0, 0), (1, 0)]).dxftype())
attempt("R12 add_mtext", lambda: m12.add_mtext("x").dxftype())
d10 = ezdxf.new("R2010"); d10.modelspace().add_lwpolyline([(0,0),(1,0)])
attempt("saveas R2010 doc as R12 via dxfversion change", lambda: (setattr(d10, "dxfversion", "R12"), d10.saveas(out / "downgrade.dxf"))[1] or "written: " + str(sorted({ln for ln in (out/'downgrade.dxf').read_text().split() if ln in ('LWPOLYLINE','POLYLINE','VERTEX')})))
print("  entities in downgraded R12 file:", [e.dxftype() for e in ezdxf.readfile(out / "downgrade.dxf").modelspace()])
print("supported versions:", ezdxf.const.versions_supported_by_new)

# 6) 输出确定性：同样内容两次 new()+write 是否字节相同
def build():
    d = ezdxf.new("R2010"); d.modelspace().add_line((0, 0), (1, 1)); s = io.StringIO(); d.write(s); return s.getvalue()
o1, o2 = build(), build()
print("two identical builds byte-identical:", o1 == o2)
if o1 != o2:
    diffs = [(a, b) for a, b in zip(o1.splitlines(), o2.splitlines()) if a != b]
    print("  differing lines (first 6):", diffs[:6])

ezdxf.options.write_fixed_meta_data_for_testing = True
o1, o2 = build(), build()
print("with options.write_fixed_meta_data_for_testing=True byte-identical:", o1 == o2)
# 未注册 APPID 的 audit
d = ezdxf.new("R2010"); l = d.modelspace().add_line((0,0),(1,0)); l.set_xdata("NOT_REG", [(1000, "x")])
a = d.audit(); print("audit unregistered appid: errors", [f.message[:80] for f in a.errors], "fixes", [f.message[:80] for f in a.fixes], "| appid now registered:", "NOT_REG" in d.appids)

# 7) 正确的 R12 导出路径：ezdxf.addons.r12export；DWG 转换器 odafc 是否可用
from ezdxf.addons import r12export, odafc
d = ezdxf.new("R2010"); d.modelspace().add_lwpolyline([(0, 0), (1, 0, 0, 0, 1), (1, 1)], format="xyseb")
s = io.StringIO(); r12export.write(d, s); d12 = ezdxf.read(io.StringIO(s.getvalue()))
print("r12export ->", d12.dxfversion, [e.dxftype() for e in d12.modelspace()])
print("odafc (ODA File Converter) installed:", odafc.is_installed())
