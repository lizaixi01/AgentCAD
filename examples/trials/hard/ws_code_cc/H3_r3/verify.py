import math, os
import ezdxf
import ezdxf.bbox
from gen_flanges import parse, check

ok_all = True
for r in parse():
    fn = f"{r['pn']}.dxf"
    if check(r):
        assert not os.path.exists(fn), fn
        print(f"{r['pn']}: 不成立，未出图 ✓")
        continue
    doc = ezdxf.readfile(fn)
    msp = doc.modelspace()
    D, dc, P, n, d = r["D"], r["dc"], r["P"], r["n"], r["d"]
    errs = []
    circ = list(msp.query("CIRCLE"))
    def has(rad, layer, cx=0, cy=0):
        return [c for c in circ if abs(c.dxf.radius - rad) < 1e-6 and c.dxf.layer == layer
                and abs(c.dxf.center.x - cx) < 1e-6 and abs(c.dxf.center.y - cy) < 1e-6]
    if len(has(D / 2, "OUTLINE")) != 1: errs.append("外圆")
    if len(has(dc / 2, "OUTLINE")) != 1: errs.append("中心孔")
    pc = has(P / 2, "CENTER")
    if len(pc) != 1 or doc.layers.get("CENTER").dxf.linetype != "CENTER": errs.append("节圆线型")
    bh = [c for c in circ if abs(c.dxf.radius - d / 2) < 1e-6 and c.dxf.layer == "OUTLINE"]
    if len(bh) != n: errs.append(f"孔数{len(bh)}")
    for c in bh:
        if abs(math.hypot(c.dxf.center.x, c.dxf.center.y) - P / 2) > 1e-6: errs.append("孔不在节圆")
    angs = sorted((math.degrees(math.atan2(c.dxf.center.y, c.dxf.center.x)) - 90) % 360 for c in bh)
    if any(abs(a - k * 360 / n) > 1e-6 for k, a in enumerate(angs)): errs.append("非均布/首孔不在正上方")
    lines = [l for l in msp.query("LINE") if l.dxf.layer == "CENTER"]
    hz = any(abs(l.dxf.start.y) < 1e-9 and abs(l.dxf.end.y) < 1e-9 and l.dxf.start.x < -D / 2 for l in lines)
    vt = any(abs(l.dxf.start.x) < 1e-9 and abs(l.dxf.end.x) < 1e-9 and l.dxf.start.y < -D / 2 for l in lines)
    if not (hz and vt): errs.append("中心线")
    dims = {}
    for dm in msp.query("DIMENSION"):
        blk = doc.blocks.get(dm.dxf.geometry)
        shown = [e.plain_text() for e in blk if e.dxftype() == "MTEXT"]
        dims[round(dm.get_measurement(), 6)] = shown[0] if shown else None
    exp = {D: f"Ø{D:g}", dc: f"Ø{dc:g}", P: f"Ø{P:g}", d: f"{n}×Ø{d:g}"}
    for k, t in exp.items():
        if dims.get(k) != t:
            errs.append(f"尺寸Ø{k:g}:{dims.get(k)}")
    lo = ezdxf.bbox.extents(msp)
    if lo.extmin.x < -D / 2 - 40 or lo.extmax.x > D / 2 + 40: errs.append(f"范围异常{lo}")
    txt = [t.dxf.text for t in msp.query("TEXT") if t.dxf.layer == "TEXT"]
    want = f"{r['pn']}  材料 {r['mat']}"
    tpos = [t for t in msp.query("TEXT") if t.dxf.text == want and t.dxf.align_point.y < -D / 2]
    if not tpos: errs.append(f"文字{txt}")
    ok_all &= not errs
    print(f"{r['pn']}: 孔{len(bh)} 尺寸{sorted(dims.items())} 文字{txt} -> {'OK' if not errs else errs}")
print("ALL OK" if ok_all else "有错误")
