import math
import ezdxf
from ezdxf.enums import TextEntityAlignment

DATA = """FL-101,150,60,110,6,12,Q235
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


def check(D, c, P, n, d):
    errs = []
    if P / 2 + d / 2 >= D / 2:
        errs.append(f"螺栓孔超出外圆：节圆半径+孔半径={P/2+d/2:g} ≥ 外圆半径 {D/2:g}")
    if P / 2 - d / 2 <= c / 2:
        errs.append(f"螺栓孔碰到中心孔：节圆半径-孔半径={P/2-d/2:g} ≤ 中心孔半径 {c/2:g}")
    chord = P * math.sin(math.pi / n)
    if chord <= d:
        errs.append(f"相邻螺栓孔重叠：相邻孔心距={chord:.2f} ≤ 孔径 {d:g}")
    return errs


def polar(r, deg):
    return (r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)))


def make(pn, D, c, P, n, d, mat):
    doc = ezdxf.new("R2010", setup=True, units=4)
    doc.header["$LTSCALE"] = 0.5
    doc.styles.add("CN", font="simsun.ttc")
    for name, color, lt in [("OUTLINE", 7, "Continuous"), ("CENTER", 1, "CENTER"),
                            ("DIM", 3, "Continuous"), ("TEXT", 7, "Continuous")]:
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    cl = {"layer": "CENTER", "linetype": "CENTER"}
    R = D / 2

    msp.add_circle((0, 0), R, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), c / 2, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), P / 2, dxfattribs=cl)
    ext = R + 8
    msp.add_line((-ext, 0), (ext, 0), dxfattribs=cl)
    msp.add_line((0, -ext), (0, ext), dxfattribs=cl)

    holes = []
    for i in range(n):
        a = math.pi / 2 - 2 * math.pi * i / n  # 第一个孔在正上方
        cx, cy = P / 2 * math.cos(a), P / 2 * math.sin(a)
        holes.append((cx, cy))
        msp.add_circle((cx, cy), d / 2, dxfattribs={"layer": "OUTLINE"})
        # 螺栓孔径向中心线（切向已由节圆点画线表示）
        e = d / 2 + 3
        ux, uy = math.cos(a), math.sin(a)
        msp.add_line((cx - ux * e, cy - uy * e), (cx + ux * e, cy + uy * e), dxfattribs=cl)

    ov = {"dimtxt": 3.5, "dimasz": 3.0, "dimtxsty": "CN"}

    def ddim(center, r, loc, text):
        dim = msp.add_diameter_dim(center=center, radius=r, location=loc, text=text,
                                   dimstyle="EZ_RADIUS", override=ov,
                                   dxfattribs={"layer": "DIM"})
        dim.render()

    ddim((0, 0), R, polar(R + 15, 30), f"Ø{D:g}")
    ddim((0, 0), P / 2, polar(R + 15, 150), f"Ø{P:g}")
    ddim((0, 0), c / 2, polar(R + 15, 210), f"Ø{c:g}")
    hx, hy = holes[0]
    ddim((hx, hy), d / 2, (hx + 25, hy + 18), f"{n}×Ø{d:g}")

    msp.add_text(f"{pn}  材料 {mat}", height=5,
                 dxfattribs={"layer": "TEXT", "style": "CN"}
                 ).set_placement((0, -R - 28), align=TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(f"{pn}.dxf")


if __name__ == "__main__":
    skipped = []
    for line in DATA.splitlines():
        pn, D, c, P, n, d, mat = line.split(",")
        D, c, P, d = map(float, (D, c, P, d))
        n = int(n)
        errs = check(D, c, P, n, d)
        if errs:
            skipped.append((pn, errs))
            continue
        make(pn, D, c, P, n, d, mat)
        print("生成", pn)
    for pn, errs in skipped:
        print("跳过", pn, "；".join(errs))
