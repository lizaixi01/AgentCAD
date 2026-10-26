"""exp02: 错误与恢复：不存在文件 / 垃圾文件 / 截断文件 / ezdxf.recover / audit。"""
import sys, pathlib, traceback
import ezdxf
from ezdxf import recover

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
good = out / "exp01_r2010.dxf"

def attempt(label, fn):
    try:
        r = fn()
        print(f"[{label}] OK -> {r}")
    except Exception as e:
        print(f"[{label}] {type(e).__module__}.{type(e).__name__}: {str(e)[:160]}")
        print(f"      MRO: {[c.__name__ for c in type(e).__mro__][:6]}")

attempt("readfile missing", lambda: ezdxf.readfile(out / "no_such.dxf"))
garbage = out / "garbage.dxf"; garbage.write_bytes(b"this is not a dxf file\nhello\n\x00\x01\x02")
attempt("readfile garbage", lambda: ezdxf.readfile(garbage))
empty = out / "empty.dxf"; empty.write_bytes(b"")
attempt("readfile empty", lambda: ezdxf.readfile(empty))

data = good.read_bytes()
for frac in (0.3, 0.6, 0.95):
    trunc = out / f"trunc_{int(frac*100)}.dxf"
    trunc.write_bytes(data[: int(len(data) * frac)])
    attempt(f"readfile trunc {int(frac*100)}%", lambda: ezdxf.readfile(trunc))
    def rec():
        doc, auditor = recover.readfile(trunc)
        msp = doc.modelspace()
        return (f"recovered: ver={doc.dxfversion} msp_entities={len(msp)} types={sorted({e.dxftype() for e in msp})} "
                f"auditor.errors={len(auditor.errors)} fixes={len(auditor.fixes)} has_errors={auditor.has_errors}")
    attempt(f"recover trunc {int(frac*100)}%", rec)
attempt("recover garbage", lambda: recover.readfile(garbage))

# audit on a valid doc with a dangling layer reference
doc = ezdxf.new("R2010")
msp = doc.modelspace()
msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "UNDEFINED_LAYER"})
auditor = doc.audit()
print("[audit undefined layer] errors:", len(auditor.errors), "fixes:", [(f.code, f.message[:80]) for f in auditor.fixes][:3])
print("   layer now in table?:", "UNDEFINED_LAYER" in doc.layers)
# invalid layer name
attempt("layers.add('A<B')", lambda: doc.layers.add("A<B"))
attempt("is_valid_layer_name('A<B')", lambda: ezdxf.is_valid_layer_name("A<B"))
attempt("add_line with layer 'A<B' (dxfattribs)", lambda: msp.add_line((0,0),(1,1), dxfattribs={"layer": "A<B"}).dxf.layer)
# invalid geometry
attempt("add_circle radius=-1", lambda: msp.add_circle((0, 0), radius=-1).dxf.radius)
attempt("add_circle radius=0", lambda: msp.add_circle((0, 0), radius=0).dxf.radius)
attempt("add_line zero length", lambda: msp.add_line((0, 0), (0, 0)).dxf.handle)
attempt("add_line with NaN", lambda: msp.add_line((float('nan'), 0), (1, 0)).dxf.start)

# 精确截断：找到 ENTITIES 段字节偏移，截在段中间
txt = data
for name in (b"HEADER", b"CLASSES", b"TABLES", b"BLOCKS", b"ENTITIES", b"OBJECTS"):
    i = txt.find(b"\n" + name)
    print(f"section {name.decode():8s} starts at byte {i} ({i/len(txt):.0%})")
ent_start = txt.find(b"\nENTITIES"); obj_start = txt.find(b"\nOBJECTS")
mid = (ent_start + obj_start) // 2
trunc = out / "trunc_mid_entities.dxf"; trunc.write_bytes(txt[:mid])
def rec_mid():
    doc, auditor = recover.readfile(trunc)
    msp = doc.modelspace()
    return (f"msp entities={len(msp)} handles={[e.dxf.handle for e in msp]} errors={len(auditor.errors)} fixes={len(auditor.fixes)} "
            f"objects-section dict ok={doc.rootdict is not None}")
attempt("readfile trunc mid-ENTITIES", lambda: ezdxf.readfile(trunc))
attempt("recover trunc mid-ENTITIES", rec_mid)
doc, auditor = recover.readfile(trunc)
print("entitydb has 8B (LINE)?", "8B" in doc.entitydb, "| entities in entitydb by type:",
      sorted({e.dxftype() for e in doc.entitydb.values()} & {"LINE","CIRCLE","ARC","LWPOLYLINE","TEXT"}))
print("modelspace block_record handle:", doc.modelspace().block_record.dxf.handle)
