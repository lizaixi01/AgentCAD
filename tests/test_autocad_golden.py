"""Differential tests against AutoCAD 2027 behaviour.

tests/golden/autocad_ops.json holds what AutoCAD itself produced for each case
(recorded headless by research/autocad/exp_ops_oracle.py). Here the same case
runs through AgentCAD and the resulting geometry must match. No AutoCAD is
needed to run these tests.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "research" / "autocad"))
from exp_ops_oracle import CASES, ours_setup_ops  # noqa: E402

from conftest import ok, reread  # noqa: E402

GOLDEN = json.loads((Path(__file__).parent / "golden" / "autocad_ops.json").read_text("utf-8"))["cases"]
ND = 5  # decimals compared (AutoCAD and ezdxf differ in the last float bits)


def rn(v: float) -> float:
    x = round(v, ND)
    return 0.0 if x == 0 else x


def rp(p) -> tuple:
    return (rn(p[0]), rn(p[1]))


def canon_poly(verts: list[tuple[float, float, float]], closed: bool) -> tuple:
    """Start/direction-independent polyline form."""
    def rev(vs):
        n = len(vs)
        pts = [v[:2] for v in reversed(vs)]
        segs = n if closed else n - 1
        bul = [0.0] * n
        for i in range(segs):  # segment i of the original goes v_i -> v_{i+1}
            j = (n - 1 - ((i + 1) % n)) if closed else n - 2 - i
            bul[j] = -vs[i][2]
        return [(p[0], p[1], b) for p, b in zip(pts, bul)]
    cands = []
    for vs in (verts, rev(verts)):
        vs = [(rn(x), rn(y), rn(b)) for x, y, b in vs]
        if closed:
            cands += [tuple(vs[k:] + vs[:k]) for k in range(len(vs))]
        else:
            cands.append(tuple(vs))
    return ("LWPOLYLINE", closed, min(cands))


def parse_acad(line: str) -> tuple:
    parts = line.split("|")
    t = parts[0]
    kv = []
    for p in parts[1:]:
        c, v = p.split(":", 1)
        if not c.isdigit():  # e.g. "tb" (text box), handled separately
            continue
        vals = v.split(",")
        try:
            num = [float(x) for x in vals]
            kv.append((int(c), num if len(num) > 1 else num[0]))
        except ValueError:
            kv.append((int(c), v))
    g = {}
    for c, v in kv:
        g.setdefault(c, v)
    neg = 210 in g and isinstance(g[210], list) and g[210][2] < 0
    if t == "LINE":
        return ("LINE", tuple(sorted([rp(g[10]), rp(g[11])])))
    if t == "CIRCLE":
        c = g[10]
        return ("CIRCLE", rp((-c[0], c[1]) if neg else c), rn(g[40]))
    if t == "ARC":
        c = g[10]
        a1, a2 = math.degrees(g[50]), math.degrees(g[51])  # entget returns radians
        if neg:
            c, a1, a2 = (-c[0], c[1]), 180 - a2, 180 - a1
        return ("ARC", rp(c), rn(g[40]), rn(a1 % 360), rn(a2 % 360))
    if t == "LWPOLYLINE":
        verts = []
        for c, v in kv:
            if c == 10:
                verts.append([v[0], v[1], 0.0])
            elif c == 42 and verts:
                verts[-1][2] = v
        if neg:
            verts = [[-x, y, -b] for x, y, b in verts]
        return canon_poly([tuple(v) for v in verts], bool(int(g.get(70, 0)) & 1))
    if t == "TEXT":
        tb = [float(x) for x in line.split("|tb:")[1].split(",")] if "|tb:" in line else [0.0, 0.0]
        return ("TEXT", g[1], {"insert": g[10][:2], "height": g[40], "h": int(g.get(72, 0)), "v": int(g.get(73, 0)),
                               "ink": tb, "rot": math.degrees(g.get(50, 0.0)), "neg": neg})
    if t == "DIMENSION":
        kind = int(g[70]) & 0x0F
        m = g[42]
        return ("DIMENSION", rn(math.degrees(m) if kind in (2, 5) else m))  # angular: radians in AutoCAD
    if t == "INSERT":
        return canon_insert(g[2], g[10], g.get(41, 1.0), g.get(42, 1.0), math.degrees(g.get(50, 0.0)))
    return (t,)


def canon_insert(name, ins, sx, sy, rot_deg) -> tuple:
    a = math.radians(rot_deg)
    mat = (rn(sx * math.cos(a)), rn(-sy * math.sin(a)), rn(sx * math.sin(a)), rn(sy * math.cos(a)))
    return ("INSERT", name, rp(ins), mat)


def canon_ours(e) -> tuple:
    t = e.dxftype()
    x = e.dxf
    if t == "LINE":
        return ("LINE", tuple(sorted([rp(x.start), rp(x.end)])))
    if t == "CIRCLE":
        return ("CIRCLE", rp(x.center), rn(x.radius))
    if t == "ARC":
        return ("ARC", rp(x.center), rn(x.radius), rn(x.start_angle % 360), rn(x.end_angle % 360))
    if t == "LWPOLYLINE":
        return canon_poly([tuple(p) for p in e.get_points("xyb")], bool(e.closed))
    if t == "TEXT":
        h, v = x.get("halign", 0), x.get("valign", 0)
        anchor = x.insert if (h == 0 and v == 0) else x.get("align_point", x.insert)
        return ("TEXT", x.text, {"anchor": (anchor.x, anchor.y), "height": x.height, "h": h, "v": v,
                                 "rot": x.get("rotation", 0.0), "neg": tuple(x.extrusion)[2] < 0})
    if t == "DIMENSION":
        from agentcad.model import measure_dimension
        return ("DIMENSION", rn(measure_dimension(e)))
    if t == "INSERT":
        return canon_insert(x.name, x.insert, x.xscale, x.yscale, x.rotation)
    return (t,)


def same_text(a: dict, o: dict) -> bool:
    """AutoCAD text (left/baseline, ink box known) vs ours (alignment may be swapped).
    Baseline must match exactly. Horizontally, ours is either left-aligned at AutoCAD's
    insert, or right-aligned at the mirrored start, which AutoCAD encodes as
    insert + (ink_left + ink_right) (identical box when side bearings are equal)."""
    if a["neg"] or o["neg"] or abs((a["rot"] - o["rot"]) % 360) > 1e-6 or abs(a["height"] - o["height"]) > 1e-9:
        return False
    if a["h"] != 0 or a["v"] != 0:
        return False
    base_y = o["anchor"][1] - (o["height"] if o["v"] == 3 else 0.0)
    if abs(base_y - a["insert"][1]) > 1e-6:
        return False
    if o["h"] == 0:
        return abs(o["anchor"][0] - a["insert"][0]) < 1e-6
    if o["h"] == 2:
        return abs(o["anchor"][0] - (a["insert"][0] + a["ink"][0] + a["ink"][1])) < 1e-4
    return False


def run_ours(rt, ws, name):
    case = CASES[name]
    ok(rt.create_drawing(f"{name}.dxf"))
    if case["setup"]:
        ok(rt.apply_operations(f"{name}.dxf", ours_setup_ops(case["setup"])))
    ok(rt.apply_operations(f"{name}.dxf", case["ours"]))
    return [canon_ours(e) for e in reread(ws, f"{name}.dxf").modelspace()]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_matches_autocad(rt, ws, name):
    acad_all = [parse_acad(l) for l in GOLDEN[name]["acad_entities"]]
    ours_all = run_ours(rt, ws, name)
    acad = Counter(c for c in acad_all if c[0] != "TEXT")
    ours = Counter(c for c in ours_all if c[0] != "TEXT")
    missing = acad - ours
    extra = ours - acad
    assert not missing and not extra, f"\nAutoCAD only: {sorted(missing.elements())}\nAgentCAD only: {sorted(extra.elements())}"
    at = [c for c in acad_all if c[0] == "TEXT"]
    ot = [c for c in ours_all if c[0] == "TEXT"]
    assert len(at) == len(ot)
    unmatched = list(ot)
    for a in at:
        hit = next((o for o in unmatched if o[1] == a[1] and same_text(a[2], o[2])), None)
        assert hit is not None, f"no AgentCAD text matches AutoCAD {a} among {unmatched}"
        unmatched.remove(hit)
