import math
import os
import ezdxf
from gen_flanges import DATA, check

ok_all = True
for line in DATA.splitlines():
    pn, D, c, P, n, d, mat = line.split(",")
    D, c, P, d = map(float, (D, c, P, d))
    n = int(n)
    fn = f"{pn}.dxf"
    if check(D, c, P, n, d):
        print(pn, "无效行, 文件存在?", os.path.exists(fn))
        ok_all &= not os.path.exists(fn)
        continue
    doc = ezdxf.readfile(fn)
    msp = doc.modelspace()
    circles = msp.query("CIRCLE")
    centered = sorted(round(e.dxf.radius * 2, 3) for e in circles
                      if e.dxf.center.isclose((0, 0, 0)))
    pitch = [e for e in circles if e.dxf.center.isclose((0, 0, 0)) and e.dxf.linetype == "CENTER"]
    holes = [e for e in circles if not e.dxf.center.isclose((0, 0, 0))]
    top = max(holes, key=lambda e: e.dxf.center.y)
    angs = sorted(round(math.degrees(math.atan2(e.dxf.center.y, e.dxf.center.x)) % 360, 3) for e in holes)
    steps = {round((angs[(i + 1) % n] - angs[i]) % 360, 3) for i in range(n)}
    pr = {round(e.dxf.center.magnitude * 2, 3) for e in holes}
    hd = {round(e.dxf.radius * 2, 3) for e in holes}
    lines = msp.query("LINE")
    hv = [l for l in lines if l.dxf.linetype == "CENTER" and
          (l.dxf.start.isclose((-(D/2+8), 0, 0)) or l.dxf.start.isclose((0, -(D/2+8), 0)))]
    dimtexts = [dm.dxf.text for dm in msp.query("DIMENSION")]
    meas = [round(dm.get_measurement(), 3) for dm in msp.query("DIMENSION")]
    txt = [t.dxf.text for t in msp.query("TEXT")]
    exp_texts = [f"Ø{D:g}", f"Ø{P:g}", f"Ø{c:g}", f"{n}×Ø{d:g}"]
    good = (centered == sorted([c, P, D]) and len(pitch) == 1 and len(holes) == n
            and math.isclose(top.dxf.center.x, 0, abs_tol=1e-9) and top.dxf.center.y > 0
            and steps == {round(360 / n, 3)} and pr == {P} and hd == {d} and len(hv) == 2
            and dimtexts == exp_texts and meas == [D, P, c, d]
            and txt == [f"{pn}  材料 {mat}"])
    ok_all &= good
    print(pn, "OK" if good else "FAIL", centered, f"孔{len(holes)} 间隔{steps} 节径{pr} 孔径{hd}",
          dimtexts, meas, txt, f"top=({top.dxf.center.x:.3f},{top.dxf.center.y:.3f})")
print("ALL OK" if ok_all else "有问题")
