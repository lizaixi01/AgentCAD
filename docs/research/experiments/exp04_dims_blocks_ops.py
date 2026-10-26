"""exp04: 标注（测量值/块/覆盖/过期块）、块与属性、编辑操作在 ezdxf 中的可用性。"""
import sys, pathlib, io, math
import ezdxf
from ezdxf.math import Matrix44, Vec2, offset_vertices_2d

def attempt(label, fn):
    try: print(f"[{label}] OK -> {fn()}")
    except Exception as e: print(f"[{label}] {type(e).__name__}: {str(e)[:150]}")

doc = ezdxf.new("R2010", setup=True); msp = doc.modelspace()
print("EZDXF dimstyle dimlfac=", doc.dimstyles.get("EZDXF").dxf.dimlfac, "| Standard dimlfac=", doc.dimstyles.get("Standard").dxf.dimlfac)
# 各类标注
dl = msp.add_aligned_dim(p1=(0, 0), p2=(30, 40), distance=5, dimstyle="EZDXF"); dl.render()
dd = msp.add_diameter_dim(center=(0, 0), radius=10, angle=30, dimstyle="EZ_RADIUS"); dd.render()
da = msp.add_angular_dim_2l(base=(10, 10), line1=((0, 0), (10, 0)), line2=((0, 0), (0, 10)), dimstyle="EZ_CURVED"); da.render()
for name, d in (("aligned", dl), ("diameter", dd), ("angular2l", da)):
    e = d.dimension
    print(f"{name:9s}: dimtype(70)={e.dxf.dimtype} type&7={e.dimtype} block={e.dxf.geometry} get_measurement()={e.get_measurement()!s:.12} 42={e.dxf.get('actual_measurement')} text(1)={e.dxf.get('text')!r}")
# 文本覆盖 / 后缀
ov = msp.add_linear_dim(base=(0, 20), p1=(0, 0), p2=(12.3456, 0), text="L=<> mm", override={"dimdec": 2}); ov.render()
print("override dim text(1):", ov.dimension.dxf.text, "| XDATA ACAD (DSTYLE):", ov.dimension.get_xdata("ACAD")[:6])
mt = [x for x in doc.blocks[ov.dimension.dxf.geometry] if x.dxftype() == "MTEXT"][0]
print("rendered MTEXT inside dim block:", repr(mt.text))
# 修改定义点而不重新 render：块会过期吗？
e = ov.dimension
e.dxf.defpoint2 = (0, 0); e.dxf.defpoint3 = (50, 0)  # 组码 13/14 = p1/p2
mt2 = [x for x in doc.blocks[e.dxf.geometry] if x.dxftype() == "MTEXT"][0]
print("after moving p2 (group 14) to x=50 without re-render: get_measurement()=", e.get_measurement(), " block text still:", repr(mt2.text))
# DIMASSOC：ezdxf 是否写反应器/关联对象
print("$DIMASSOC=", doc.header.get("$DIMASSOC"), "| dim reactors:", e.reactors.handles if e.reactors else None,
      "| ACAD_DIMASSOC objects:", sum(1 for o in doc.objects if o.dxftype() == "DIMASSOC"))

# 块 / 属性
blk = doc.blocks.new("TAG")
blk.add_circle((0, 0), 1)
blk.add_attdef("NO", insert=(0, -2), dxfattribs={"height": 0.5, "prompt": "Number"})
ref = msp.add_blockref("TAG", (100, 100), dxfattribs={"xscale": 2, "rotation": 45})
ref.add_auto_attribs({"NO": "A-01"})
print("INSERT attribs:", [(a.dxf.tag, a.dxf.text, tuple(round(v, 4) for v in a.dxf.insert)) for a in ref.attribs])
print("virtual_entities (explode preview):", [(v.dxftype(), tuple(round(c, 4) for c in v.dxf.center), round(v.dxf.radius, 4)) if v.dxftype()=="CIRCLE" else v.dxftype() for v in ref.virtual_entities()])
attempt("delete block in use", lambda: (doc.blocks.delete_block("TAG", safe=True), "deleted")[1])
attempt("add_blockref undefined block", lambda: msp.add_blockref("NOPE", (0, 0)).dxf.name)
attempt("delete layer in use (doc.layers.remove)", lambda: (doc.layers.add("USED"), msp.add_line((0,0),(1,1),dxfattribs={"layer":"USED"}), doc.layers.remove("USED"), "removed")[-1])

# 编辑运算可用性
line = msp.add_line((0, 0), (10, 0))
line.transform(Matrix44.z_rotate(math.radians(90)) @ Matrix44.translate(5, 0, 0))
print("rotate90 then translate(5,0): line", line.dxf.start, line.dxf.end)
c = msp.add_circle((0, 0), 1)
attempt("non-uniform scale CIRCLE.transform(scale(2,1,1))", lambda: c.transform(Matrix44.scale(2, 1, 1)).dxftype())
attempt("CIRCLE.to_ellipse() then transform", lambda: c.to_ellipse(replace=True).transform(Matrix44.scale(2, 1, 1)).dxftype())
print("offset_vertices_2d square by 1 (closed):", [tuple(round(x, 6) for x in v) for v in offset_vertices_2d([(0, 0), (10, 0), (10, 10), (0, 10)], offset=1, closed=True)])
print("ezdxf has trim/extend/fillet API on entities?:", any(hasattr(line, n) for n in ("trim", "extend", "fillet", "chamfer", "offset")))
print("doc.units setter:", (setattr(doc, "units", ezdxf.units.MM), doc.header["$INSUNITS"])[1], "| $MEASUREMENT unchanged:", doc.header["$MEASUREMENT"])
print("ezdxf.units.conversion_factor(MM->IN):", ezdxf.units.conversion_factor(ezdxf.units.MM, ezdxf.units.IN))
