import math, os, glob
import ezdxf
from make_flanges import DATA, check

ok_all = True
for line in DATA.splitlines()[1:]:
    f = line.split(",")
    part, mat = f[0], f[6]
    D, c, P, n, d = float(f[1]), float(f[2]), float(f[3]), int(f[4]), float(f[5])
    exists = os.path.exists(f"{part}.dxf")
    if check(D, c, P, n, d):
        print(part, "不成立, 文件存在?", exists)
        ok_all &= not exists
        continue
    doc = ezdxf.readfile(f"{part}.dxf")
    msp = doc.modelspace()
    errs = []
    circles = msp.query("CIRCLE")
    outl = [e for e in circles if e.dxf.layer == "OUTLINE"]
    cen = [e for e in circles if e.dxf.layer == "CENTER"]
    def has(r, ctr=(0, 0), lst=outl):
        return any(abs(e.dxf.radius - r) < 1e-6 and e.dxf.center.isclose((*ctr, 0), abs_tol=1e-6) for e in lst)
    if not has(D / 2): errs.append("外圆")
    if not has(c / 2): errs.append("中心孔")
    if not (len(cen) == 1 and has(P / 2, lst=cen) and cen[0].dxf.linetype == "CENTER"): errs.append("节圆")
    holes = [e for e in outl if abs(e.dxf.radius - d / 2) < 1e-6 and e.dxf.center.magnitude > 1e-6]
    if len(holes) != n: errs.append(f"孔数{len(holes)}")
    for e in holes:
        if abs(e.dxf.center.magnitude - P / 2) > 1e-6: errs.append("孔不在节圆")
    if not has(d / 2, (0, P / 2)): errs.append("顶孔")
    angs = sorted(math.degrees(math.atan2(e.dxf.center.y, e.dxf.center.x)) % 360 for e in holes)
    gaps = [(angs[(i + 1) % n] - angs[i]) % 360 for i in range(n)]
    if any(abs(g - 360 / n) > 1e-6 for g in gaps): errs.append("不均布")
    lines = [e for e in msp.query("LINE") if e.dxf.layer == "CENTER" and e.dxf.linetype == "CENTER"]
    hz = any(abs(e.dxf.start.y) < 1e-9 and abs(e.dxf.end.y) < 1e-9 and abs(e.dxf.end.x - e.dxf.start.x) > D for e in lines)
    vt = any(abs(e.dxf.start.x) < 1e-9 and abs(e.dxf.end.x) < 1e-9 and abs(e.dxf.end.y - e.dxf.start.y) > D for e in lines)
    if not (hz and vt): errs.append("中心线")
    dims = []
    for dm in msp.query("DIMENSION"):
        dims.append((dm.dxf.text, round(dm.get_measurement(), 4), dm.dimtype))
    want = {("%%c<>", D), ("<>", P), ("<>", c), (f"{n}×%%c{d:g}", d)}
    got = {(t, m) for t, m, _ in dims}
    if want != got: errs.append(f"标注 {dims}")
    texts = [t.dxf.text for t in msp.query("TEXT")]
    tx = msp.query("TEXT")[0]
    if texts != [f"{part}  材料 {mat}"] or tx.dxf.align_point.y >= -D / 2: errs.append(f"文字 {texts}")
    # 渲染出的标注块中的文字
    blk_txt = []
    for dm in msp.query("DIMENSION"):
        blk = doc.blocks.get(dm.dxf.geometry)
        blk_txt += [e.dxf.text for e in blk.query("MTEXT TEXT")] if blk else []
    if sorted(blk_txt) != sorted([f"%%c{D:g}", f"%%c{P:g}", f"%%c{c:g}", f"{n}×%%c{d:g}"]):
        errs.append(f"渲染文字 {blk_txt}")
    # 文字框碰撞检查（按 MIDDLE_CENTER、字宽≈0.75 字高估算，外扩 0.5mm）
    R = D / 2
    boxes = []
    for dm in msp.query("DIMENSION"):
        for e in doc.blocks.get(dm.dxf.geometry).query("MTEXT"):
            s = e.dxf.text.replace("%%c", "Ø")
            h = e.dxf.char_height
            boxes.append((s, e.dxf.insert.x, e.dxf.insert.y, len(s) * 0.75 * h / 2 + 0.5, h / 2 + 0.5))
    lab = msp.query("TEXT")[0]
    s = lab.dxf.text
    boxes.append((s, lab.dxf.align_point.x, lab.dxf.align_point.y, len(s.encode("gbk")) * 0.5 * 5 / 2, 3))
    for s, x, y, hw, hh in boxes:
        for e in outl + cen:
            cx, cy, r = e.dxf.center.x, e.dxf.center.y, e.dxf.radius
            dmin = math.hypot(max(abs(x - cx) - hw, 0), max(abs(y - cy) - hh, 0))
            dmax = math.hypot(abs(x - cx) + hw, abs(y - cy) + hh)
            if dmin < r < dmax:
                errs.append(f"文字'{s}'压圆 r={r:g}")
        if abs(y) < hh and abs(x) - hw < R + 6: errs.append(f"文字'{s}'压水平中心线")
        if abs(x) < hw and abs(y) - hh < R + 6: errs.append(f"文字'{s}'压竖直中心线")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b_ = boxes[i], boxes[j]
            if abs(a[1] - b_[1]) < a[3] + b_[3] and abs(a[2] - b_[2]) < a[4] + b_[4]:
                errs.append(f"文字重叠 {a[0]} / {b_[0]}")
    print(part, "OK" if not errs else errs, "| 标注:", blk_txt, "|", texts[0])
    ok_all &= not errs
print("ALL OK" if ok_all else "有错误", sorted(glob.glob("*.dxf")))
