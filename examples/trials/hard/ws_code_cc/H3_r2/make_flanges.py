import math
import ezdxf

DATA = """零件号,外径,中心孔,节圆,孔数,孔径,材料
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


def check(D, c, P, n, d):
    """返回不成立原因列表（空列表表示几何成立）"""
    errs = []
    R, rc, rp, rh = D / 2, c / 2, P / 2, d / 2
    if rp + rh >= R:
        errs.append(f"螺栓孔超出外圆：节圆半径{rp:g}+孔半径{rh:g}={rp + rh:g} ≥ 外圆半径{R:g}")
    if rp - rh <= rc:
        errs.append(f"螺栓孔碰到中心孔：节圆半径{rp:g}-孔半径{rh:g}={rp - rh:g} ≤ 中心孔半径{rc:g}")
    chord = P * math.sin(math.pi / n)
    if chord <= d:
        errs.append(f"相邻螺栓孔重叠：孔心距 {P:g}×sin(180°/{n})={chord:.2f} ≤ 孔径{d:g}")
    if c >= D:
        errs.append("中心孔不小于外径")
    return errs


def make(part, D, c, P, n, d, mat):
    doc = ezdxf.new("R2010", setup=True)  # setup=True 载入 CENTER 线型和标准样式
    doc.header["$INSUNITS"] = 4  # mm
    doc.styles.add("CN", font="simsun.ttc")
    for name, color, lt in [("OUTLINE", 7, "CONTINUOUS"), ("CENTER", 1, "CENTER"),
                            ("DIM", 3, "CONTINUOUS"), ("TEXT", 7, "CONTINUOUS")]:
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    R = D / 2
    lts = D / 150  # 线型比例随图形大小变化

    # 轮廓
    msp.add_circle((0, 0), R, dxfattribs={"layer": "OUTLINE"})
    msp.add_circle((0, 0), c / 2, dxfattribs={"layer": "OUTLINE"})
    holes = []
    for i in range(n):
        a = math.radians(90 - i * 360 / n)  # 第一个孔在正上方，顺时针排列
        p = (P / 2 * math.cos(a), P / 2 * math.sin(a))
        holes.append(p)
        msp.add_circle(p, d / 2, dxfattribs={"layer": "OUTLINE"})

    # 中心线、节圆
    cattr = {"layer": "CENTER", "linetype": "CENTER", "ltscale": lts}
    ext = R + 6
    msp.add_line((-ext, 0), (ext, 0), dxfattribs=cattr)
    msp.add_line((0, -ext), (0, ext), dxfattribs=cattr)
    msp.add_circle((0, 0), P / 2, dxfattribs=cattr)

    # 标注
    dattr = {"layer": "DIM"}
    # EZDXF 样式默认 dimlfac=100（m→cm），mm 图纸须改回 1
    ov = {"dimtxt": 3.5, "dimasz": 3, "dimlfac": 1, "dimdec": 2, "dimzin": 12, "dimtxsty": "CN"}
    # 外径：水平线性标注，放在图形下方
    msp.add_linear_dim(base=(0, -R - 12), p1=(-R, 0), p2=(R, 0), angle=0,
                       text="%%c<>", override=ov, dxfattribs=dattr).render()
    def polar(r, a):
        return (r * math.cos(math.radians(a)), r * math.sin(math.radians(a)))

    # 节圆直径：沿第1、2孔之间的方向（右上），避开螺栓孔，文字放在外圆外
    ap = 90 - 180 / n
    msp.add_diameter_dim((0, 0), radius=P / 2, location=polar(R + 12, ap),
                         override=ov, dxfattribs=dattr).render()
    # 中心孔直径：沿第1孔与最后一孔之间的方向（左上），文字放在中心孔与螺栓孔之间的环带内
    ac = 90 + 180 / n
    msp.add_diameter_dim((0, 0), radius=c / 2, location=polar((c / 2 + P / 2 - d / 2) / 2, ac),
                         override=ov, dxfattribs=dattr).render()
    # 螺栓孔：取最接近左下 225° 的孔，沿 225° 方向引出到外圆外，文字 n×Ød
    k = min(range(n), key=lambda i: abs(((90 - i * 360 / n) - 225 + 180) % 360 - 180))
    hx, hy = holes[k]
    ux, uy = polar(1, 225)
    b = hx * ux + hy * uy  # 解 |hole + t·u| = R + 12
    t = -b + math.sqrt(b * b - (P / 2) ** 2 + (R + 12) ** 2)
    msp.add_diameter_dim((hx, hy), radius=d / 2, location=(hx + t * ux, hy + t * uy),
                         text=f"{n}×%%c{d:g}", override=ov, dxfattribs=dattr).render()

    # 零件号、材料
    msp.add_text(f"{part}  材料 {mat}", height=5,
                 dxfattribs={"layer": "TEXT", "style": "CN"}
                 ).set_placement((0, -R - 30), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    doc.saveas(f"{part}.dxf")


if __name__ == "__main__":
    rejected = []
    for line in DATA.splitlines()[1:]:
        f = line.split(",")
        part, mat = f[0], f[6]
        D, c, P, n, d = float(f[1]), float(f[2]), float(f[3]), int(f[4]), float(f[5])
        errs = check(D, c, P, n, d)
        if errs:
            rejected.append((part, errs))
            continue
        make(part, D, c, P, n, d, mat)
        print("OK", part)
    for part, errs in rejected:
        print("REJECT", part, "；".join(errs))
