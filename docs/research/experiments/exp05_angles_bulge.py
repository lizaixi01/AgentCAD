"""exp05: 圆弧角度约定（CCW、度、跨 0°）、bulge 符号、ezdxf 对非规范角度的解释。"""
import ezdxf, math
from ezdxf.math import bulge_to_arc, arc_to_bulge, arc_angle_span_deg, Vec2

doc = ezdxf.new("R2010"); msp = doc.modelspace()
for sa, ea in ((-90, 450), (370, 10), (350, 10), (10, 350), (0, 0), (0, 360), (90, 90.0000001)):
    a = msp.add_arc((0, 0), 1, sa, ea)
    print(f"ARC 50={sa:>6} 51={ea:>11}: stored=({a.dxf.start_angle},{a.dxf.end_angle}) "
          f"start_point={tuple(round(v,6) for v in a.start_point)[:2]} end_point={tuple(round(v,6) for v in a.end_point)[:2]} "
          f"arc_angle_span_deg={arc_angle_span_deg(sa, ea):.6f}")
for b in (1.0, -1.0, math.tan(math.radians(90) / 4)):
    c, s, e, r = bulge_to_arc(Vec2(0, 0), Vec2(10, 0), b)
    print(f"bulge={b:+.6f}: center={tuple(round(v,6) for v in c)} r={r:.6f} start={math.degrees(s):.3f}deg end={math.degrees(e):.3f}deg (arc is CCW from start to end)")
print("arc_to_bulge(center=(0,0), start=0, end=90deg, r=1):", tuple(round(v, 6) if isinstance(v, float) else tuple(round(x,6) for x in v) for v in arc_to_bulge(Vec2(0, 0), 0, math.pi / 2, 1)))
