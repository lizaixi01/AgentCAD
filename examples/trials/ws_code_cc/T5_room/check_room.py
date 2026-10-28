import ezdxf
from collections import Counter

doc = ezdxf.readfile("room.dxf")
msp = doc.modelspace()
print("AXIS linetype:", doc.layers.get("AXIS").dxf.linetype)
print("counts:", Counter((e.dxftype(), e.dxf.layer) for e in msp))
for lay in ("AXIS", "WALL", "WINDOW"):
    print(f"--- {lay}")
    for e in msp.query(f'LINE[layer=="{lay}"]'):
        s, t = e.dxf.start, e.dxf.end
        print(f"  ({s.x:.0f},{s.y:.0f}) -> ({t.x:.0f},{t.y:.0f})  len={s.distance(t):.0f}")
print("--- DIMENSION")
for d in msp.query("DIMENSION"):
    print(f"  p1={tuple(round(v) for v in d.dxf.defpoint2)} p2={tuple(round(v) for v in d.dxf.defpoint3)} "
          f"measure={d.get_measurement():.1f} block={d.dxf.geometry}")

# 端点连通检查：WALL 线的每个端点应恰好被 2 条线共享（闭合轮廓）
pts = Counter()
for e in msp.query('LINE[layer=="WALL"]'):
    for p in (e.dxf.start, e.dxf.end):
        pts[(round(p.x), round(p.y))] += 1
bad = {p: n for p, n in pts.items() if n != 2}
print("WALL dangling/over-shared endpoints:", bad or "none")
