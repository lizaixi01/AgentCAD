import math
import ezdxf

TABLE = """零件号,外径,中心孔,节圆,孔数,孔径,材料
FL-101,150,60,110,6,12,Q235
FL-102,180,75,135,8,14,Q235
FL-103,120,40,90,4,11,45钢
FL-104,200,90,160,8,18,Q345
FL-105,160,60,120,6,14,Q235
FL-106,100,30,70,4,9,304不锈钢
FL-107,220,110,180,12,14,Q235
FL-108,140,50,105,6,11,45钢
FL-109,130,60,118,6,14,Q235
FL-110,250,120,200,16,18,Q345
FL-111,90,40,66,16,14,Q235
FL-112,170,80,130,8,13,304不锈钢"""


def parse():
    rows = []
    for line in TABLE.strip().splitlines()[1:]:
        pn, D, dc, P, n, d, mat = [s.strip() for s in line.split(",")]
        rows.append(dict(pn=pn, D=float(D), dc=float(dc), P=float(P),
                         n=int(n), d=float(d), mat=mat))
    return rows


def check(r):
    """返回不成立原因列表（空表示几何成立）。"""
    D, dc, P, n, d = r["D"], r["dc"], r["P"], r["n"], r["d"]
    rp, rh = P / 2, d / 2
    errs = []
    if not (dc < P < D):
        errs.append(f"节圆Ø{P:g}不在中心孔Ø{dc:g}与外圆Ø{D:g}之间")
    if rp + rh >= D / 2:
        errs.append(f"螺栓孔外缘半径 {rp:g}+{rh:g}={rp + rh:g} ≥ 外圆半径 {D / 2:g}，超出/相切外圆")
    if rp - rh <= dc / 2:
        errs.append(f"螺栓孔内缘半径 {rp:g}-{rh:g}={rp - rh:g} ≤ 中心孔半径 {dc / 2:g}，碰到中心孔")
    if n >= 2:
        chord = 2 * rp * math.sin(math.pi / n)
        if chord <= d:
            errs.append(f"相邻孔心距 2×{rp:g}×sin(180°/{n})={chord:.2f} ≤ 孔径 {d:g}，相邻孔重叠")
    return errs


def make_doc():
    doc = ezdxf.new("R2010", setup=True)  # setup=True 载入 CENTER 等线型
    doc.header["$INSUNITS"] = 4  # mm
    doc.styles.add("CN", font="simsun.ttc")
    doc.layers.add("OUTLINE", color=7, lineweight=50)
    doc.layers.add("CENTER", color=1, linetype="CENTER", lineweight=25)
    doc.layers.add("DIM", color=3)
    doc.layers.add("TEXT", color=7)
    ds = doc.dimstyles.duplicate_entry("EZ_RADIUS", "FL_DIA")
    ds.dxf.dimtxsty = "CN"
    ds.dxf.dimtxt = 3.5
    ds.dxf.dimasz = 3.0
    ds.dxf.dimdec = 0
    ds.dxf.dimlfac = 1.0  # EZ_* 样式默认 dimlfac=100，图纸单位 mm 需改为 1
    ds.dxf.dimtmove = 0  # 文字移动时尺寸线随动
    return doc


def draw(r):
    D, dc, P, n, d = r["D"], r["dc"], r["P"], r["n"], r["d"]
    doc = make_doc()
    msp = doc.modelspace()
    R, rp = D / 2, P / 2
    ltscale = max(0.4, D / 250)

    # 轮廓
    msp.add_circle((0, 0), R, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), dc / 2, dxfattribs={"layer": "OUTLINE"})
    holes = []
    for k in range(n):
        a = math.radians(90 + k * 360 / n)  # 第一个孔在正上方
        c = (rp * math.cos(a), rp * math.sin(a))
        holes.append((c, a))
        msp.add_circle(c, d / 2, dxfattribs={"layer": "OUTLINE"})

    # 中心线：节圆、水平/竖直中心线、各螺栓孔径向短中心线
    ca = {"layer": "CENTER", "ltscale": ltscale}
    msp.add_circle((0, 0), rp, dxfattribs=ca)
    ext = R + 8
    msp.add_line((-ext, 0), (ext, 0), dxfattribs=ca)
    msp.add_line((0, -ext), (0, ext), dxfattribs=ca)
    e = d / 2 + 3
    for (cx, cy), a in holes:
        ux, uy = math.cos(a), math.sin(a)
        msp.add_line((cx - ux * e, cy - uy * e), (cx + ux * e, cy + uy * e), dxfattribs=ca)

    # 尺寸标注（角度取在相邻孔之间，避开螺栓孔）
    mids = [(90 + 180 / n + k * 360 / n) % 360 for k in range(n)]
    mids = [m for m in mids if min(abs(m - q) % 360 for q in (0, 90, 180, 270, 360)) > 5]

    def pick(target, used):
        cand = [m for m in mids if all(abs(m - u) % 180 > 1 for u in used)] or mids
        return min(cand, key=lambda m: min(abs(m - target), 360 - abs(m - target)))

    da = {"layer": "DIM"}
    used = []
    for radius, target in ((R, 150), (rp, 210), (dc / 2, 330)):
        a = pick(target, used)
        used.append(a)
        ar = math.radians(a)
        if radius == R:  # 外径文字放在外圆外侧
            loc = ((R + 10) * math.cos(ar), (R + 10) * math.sin(ar))
        else:  # 节圆文字放在中心孔与螺栓孔之间，中心孔文字放在孔内
            rt = (dc / 2 + rp - d / 2) / 2 if radius == rp else dc / 4
            loc = (rt * math.cos(ar), rt * math.sin(ar))
        dim = msp.add_diameter_dim(center=(0, 0), radius=radius, location=loc,
                                   dimstyle="FL_DIA", dxfattribs=da)
        dim.render()
    # 螺栓孔 n×Ød，标在第一个孔（正上方）上，指向右上方并把文字引出到外圆之外
    (hx, hy), _ = holes[0]
    a_h = 45
    loc = (hx + (R - hy + 15) * math.cos(math.radians(a_h)),
           R + 15 * math.sin(math.radians(a_h)))
    dim = msp.add_diameter_dim(center=(hx, hy), radius=d / 2, location=loc,
                               text=f"{n}×%%c{d:g}", dimstyle="FL_DIA",
                               dxfattribs=da)
    dim.render()

    # 零件号与材料
    msp.add_text(f"{r['pn']}  材料 {r['mat']}", height=5,
                 dxfattribs={"layer": "TEXT", "style": "CN"}).set_placement(
        (0, -R - 22), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    fn = f"{r['pn']}.dxf"
    doc.saveas(fn)
    return fn


def main():
    bad = []
    for r in parse():
        errs = check(r)
        if errs:
            bad.append((r["pn"], errs))
            print(f"SKIP {r['pn']}: " + "；".join(errs))
        else:
            print("OK  ", draw(r))
    return bad


if __name__ == "__main__":
    main()
