"""Test I: the common AutoCAD operations added after the first catalog (HATCH, POLYGON, DONUT, XLINE/RAY, PLINE
width, BREAK, JOIN, DRAWORDER, PURGE, ordinate dimensions, center marks, text styles). Results are re-read from
disk; each op also has a diagnosable failure."""
from __future__ import annotations

import math

import pytest

from agentcad.model import get_tag
from conftest import by_tag, ok, reread

A = pytest.approx


def apply(rt, path, ops, **kw):
    return rt.apply_operations(path, ops, **kw)


def err(r):
    assert not r["ok"], r
    return r["error"]


def xy(pts):
    return [(round(p[0], 6), round(p[1], 6)) for p in pts]


# --- draw -----------------------------------------------------------------------------------------

def test_hatch_from_entities_with_island(rt, ws, blank):
    r = ok(apply(rt, blank, [
        {"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "tag": "box"},
        {"op": "add_circle", "center": [30, 30], "radius": 10, "tag": "hole"},
        {"op": "add_hatch", "boundary": ["tag:box", "tag:hole"], "pattern": "ANSI31", "pattern_scale": 2,
         "pattern_angle": 15, "layer": "HATCH", "tag": "h"}]))
    assert r["validation"]["passed"] and not r["validation"]["issues"]
    doc = reread(ws, blank)
    h = by_tag(doc, "h")
    assert (h.dxf.pattern_name, h.dxf.solid_fill, h.dxf.layer) == ("ANSI31", 0, "HATCH")
    assert h.dxf.pattern_scale == A(2) and h.dxf.pattern_angle == A(15)
    outer, island = h.paths
    assert xy(outer.vertices) == [(0, 0), (100, 0), (100, 60), (0, 60)]
    arc = island.edges[0]
    assert (arc.center[0], arc.center[1], arc.radius) == (A(30), A(30), A(10))
    # 'behind' (default): the hatch is drawn first
    order = sorted(doc.modelspace(), key=lambda e: int(dict(doc.modelspace().get_redraw_order()).get(e.dxf.handle, e.dxf.handle), 16))
    assert order[0].dxf.handle == h.dxf.handle


def test_hatch_from_points_solid_color_and_errors(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_hatch", "points": [[0, 0], [40, 0], [40, 40], [0, 40]],
                          "holes": [[[10, 10], [30, 10], [20, 30]]], "color": 30, "tag": "s"}]))
    h = by_tag(reread(ws, blank), "s")
    assert h.dxf.solid_fill == 1 and h.dxf.color == 30 and len(h.paths) == 2
    assert xy(h.paths[1].vertices) == [(10, 10), (30, 10), (20, 30)]
    ok(apply(rt, blank, [{"op": "add_polyline", "points": [[0, 100], [10, 100], [10, 110]], "tag": "open"},
                         {"op": "add_line", "start": [0, 200], "end": [1, 200], "tag": "ln"}]))
    assert err(apply(rt, blank, [{"op": "add_hatch", "boundary": "tag:open"}]))["code"] == "BOUNDARY_NOT_CLOSED"
    assert err(apply(rt, blank, [{"op": "add_hatch", "boundary": "tag:ln"}]))["code"] == "UNSUPPORTED_BOUNDARY"
    assert err(apply(rt, blank, [{"op": "add_hatch", "points": [[0, 0], [1, 0], [1, 1]], "pattern": "NOPE"}]))["code"] == "UNKNOWN_PATTERN"
    assert err(apply(rt, blank, [{"op": "add_hatch", "points": [[0, 0], [1, 0], [2, 0]]}]))["code"] == "DEGENERATE_GEOMETRY"
    assert err(apply(rt, blank, [{"op": "add_hatch"}]))["code"] == "AMBIGUOUS_PARAMS"


def test_polygon_inscribed_circumscribed_side(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_polygon", "center": [0, 0], "sides": 6, "radius": 10, "mode": "circumscribed", "tag": "hex"},
        {"op": "add_polygon", "center": [0, 0], "sides": 4, "radius": 10, "rotation": 0, "tag": "sq"},
        {"op": "add_polygon", "center": [0, 0], "sides": 3, "side_length": 12, "tag": "tri"}]))
    doc = reread(ws, blank)
    hexp = [tuple(p) for p in by_tag(doc, "hex").get_points("xy")]
    assert by_tag(doc, "hex").closed and len(hexp) == 6
    assert min(p[1] for p in hexp) == A(-10) and max(p[1] for p in hexp) == A(10)  # across flats = 2 x radius
    assert hexp[0][1] == A(hexp[-1][1])  # bottom edge horizontal
    assert xy(by_tag(doc, "sq").get_points("xy")) == [(10, 0), (0, 10), (-10, 0), (0, -10)]
    tri = [tuple(p) for p in by_tag(doc, "tri").get_points("xy")]
    assert all(math.dist(tri[i], tri[(i + 1) % 3]) == A(12) for i in range(3))
    assert err(apply(rt, blank, [{"op": "add_polygon", "center": [0, 0], "sides": 2, "radius": 1}]))["code"] == "OUT_OF_RANGE"
    assert err(apply(rt, blank, [{"op": "add_polygon", "center": [0, 0], "sides": 5}]))["code"] == "AMBIGUOUS_PARAMS"


def test_donut_and_wide_polyline(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_donut", "center": [5, 5], "outer_diameter": 20, "inner_diameter": 10, "tag": "d"},
                         {"op": "add_donut", "center": [50, 5], "outer_diameter": 4, "tag": "dot"},
                         {"op": "add_polyline", "points": [[0, 50], [30, 50]], "width": 1.5, "tag": "w"}]))
    doc = reread(ws, blank)
    d = by_tag(doc, "d")
    assert d.closed and d.dxf.const_width == A(5)
    assert [tuple(map(lambda v: round(v, 6), p)) for p in d.get_points("xyb")] == [(-2.5, 5, 1), (12.5, 5, 1)]
    assert by_tag(doc, "dot").dxf.const_width == A(2)
    assert by_tag(doc, "w").dxf.const_width == A(1.5)
    assert err(apply(rt, blank, [{"op": "add_donut", "center": [0, 0], "outer_diameter": 5, "inner_diameter": 5}]))["code"] == "DEGENERATE_GEOMETRY"


def test_xline_and_ray_do_not_change_extents(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [10, 10]},
                         {"op": "add_xline", "point": [0, 0], "angle": 30, "tag": "x"},
                         {"op": "add_ray", "point": [5, 5], "through": [5, 50], "tag": "r"}]))
    doc = reread(ws, blank)
    x, ray = by_tag(doc, "x"), by_tag(doc, "r")
    assert (x.dxf.unit_vector.x, x.dxf.unit_vector.y) == (A(math.sqrt(3) / 2), A(0.5))
    assert (ray.dxf.start.x, ray.dxf.unit_vector.y) == (A(5), A(1))
    info = ok(rt.read_drawing(blank))
    assert info["extents"] == [[0, 0], [10, 10]]
    assert err(apply(rt, blank, [{"op": "add_ray", "point": [0, 0], "through": [0, 0]}]))["code"] == "DEGENERATE_GEOMETRY"
    assert err(apply(rt, blank, [{"op": "add_xline", "point": [0, 0]}]))["code"] == "AMBIGUOUS_PARAMS"


# --- edit -----------------------------------------------------------------------------------------

def test_break_line_arc_circle(rt, ws, blank):
    r = ok(apply(rt, blank, [
        {"op": "add_line", "start": [0, 0], "end": [100, 0], "layer": "L1", "tag": "ln"},
        {"op": "break", "target": "tag:ln", "p1": [30, 5], "p2": [60, -5]},
        {"op": "add_arc", "center": [0, 50], "radius": 10, "start_angle": 0, "end_angle": 180, "tag": "arc"},
        {"op": "break", "target": "tag:arc", "p1": [0, 70]},
        {"op": "add_circle", "center": [50, 50], "radius": 10, "tag": "c"},
        {"op": "break", "target": "tag:c", "p1": [60, 50], "p2": [50, 60]}]))
    doc = reread(ws, blank)
    ln = by_tag(doc, "ln")
    assert (ln.dxf.start.x, ln.dxf.end.x) == (A(0), A(30))
    rest = doc.entitydb[r["results"][1]["created"][0]]
    assert (rest.dxf.start.x, rest.dxf.end.x, rest.dxf.layer) == (A(60), A(100), "L1")
    assert get_tag(rest) is None  # the copy does not share the tag
    arc = by_tag(doc, "arc")
    other = doc.entitydb[r["results"][3]["created"][0]]
    assert (arc.dxf.start_angle, arc.dxf.end_angle, other.dxf.start_angle, other.dxf.end_angle) == (A(0), A(90), A(90), A(180))
    c = by_tag(doc, "c")  # the counter-clockwise part from p1 (0 deg) to p2 (90 deg) is removed
    assert c.dxftype() == "ARC" and (c.dxf.start_angle, c.dxf.end_angle) == (A(90), A(0))
    assert err(apply(rt, blank, [{"op": "break", "target": "tag:ln", "p1": [0, 0]}]))["code"] == "BREAK_AT_END"
    assert err(apply(rt, blank, [{"op": "break", "target": "tag:ln", "p1": [-5, 0], "p2": [50, 0]}]))["code"] == "BREAK_REMOVES_ALL"
    ok(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "tag": "c2"}]))
    assert err(apply(rt, blank, [{"op": "break", "target": "tag:c2", "p1": [1, 0]}]))["code"] == "MISSING_PARAM"


def test_join_chain_into_closed_polyline(rt, ws, blank):
    r = ok(apply(rt, blank, [
        {"op": "add_line", "start": [0, 0], "end": [50, 0], "layer": "OUT", "tag": "a"},
        {"op": "add_arc", "center": [50, 10], "radius": 10, "start_angle": 270, "end_angle": 90},
        {"op": "add_line", "start": [0, 20], "end": [50, 20]},  # reversed relative to the chain
        {"op": "add_line", "start": [0, 20], "end": [0, 0]},
        {"op": "join", "target": ["tag:a", "$1", "$2", "$3"]}]))
    assert r["results"][4]["closed"] is True
    doc = reread(ws, blank)
    pl = by_tag(doc, "a")  # the result inherits the first target's tag and layer
    assert pl.dxftype() == "LWPOLYLINE" and pl.closed and pl.dxf.layer == "OUT"
    pts = [tuple(round(v, 6) for v in p) for p in pl.get_points("xyb")]
    assert pts == [(0, 0, 0), (50, 0, 1), (50, 20, 0), (0, 20, 0)]
    assert len(doc.modelspace()) == 1
    ok(apply(rt, blank, [{"op": "add_line", "start": [100, 0], "end": [110, 0], "tag": "p"},
                         {"op": "add_line", "start": [200, 0], "end": [210, 0], "tag": "q"}]))
    e = err(apply(rt, blank, [{"op": "join", "target": ["tag:p", "tag:q"]}]))
    assert e["code"] == "NOT_CONNECTED" and e["entities"]
    ok(apply(rt, blank, [{"op": "join", "target": ["tag:p", "tag:q"], "tolerance": 100, "tag": "pq"}]))
    assert not by_tag(reread(ws, blank), "pq").closed


def test_draw_order(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_hatch", "points": [[0, 0], [1, 0], [1, 1]], "behind": False, "tag": "h"},
                         {"op": "add_line", "start": [0, 0], "end": [1, 1], "tag": "l"},
                         {"op": "draw_order", "target": "tag:l", "order": "back"}]))
    doc = reread(ws, blank)
    msp = doc.modelspace()
    sort = dict(msp.get_redraw_order())
    first = min(msp, key=lambda e: int(sort.get(e.dxf.handle, e.dxf.handle), 16))
    assert get_tag(first) == "l"
    ok(apply(rt, blank, [{"op": "draw_order", "target": "tag:l", "order": "front"}]))
    msp = reread(ws, blank).modelspace()
    sort = dict(msp.get_redraw_order())
    assert get_tag(max(msp, key=lambda e: int(sort.get(e.dxf.handle, e.dxf.handle), 16))) == "l"


def test_purge(rt, ws):
    ok(rt.create_drawing("m.dxf", units="mm", template="mechanical"))
    ok(apply(rt, "m.dxf", [
        {"op": "add_line", "start": [0, 0], "end": [1, 0], "layer": "OUTLINE"},
        {"op": "define_block", "name": "USED", "entities": [{"op": "add_circle", "center": [0, 0], "radius": 1}]},
        {"op": "define_block", "name": "SPARE", "entities": [{"op": "add_circle", "center": [0, 0], "radius": 1}]},
        {"op": "insert_block", "name": "USED", "insert": [5, 5]},
        {"op": "create_text_style", "name": "UNUSED_ST"}]))
    r = ok(apply(rt, "m.dxf", [{"op": "purge"}]))
    purged = r["results"][0]["purged"]
    assert "SPARE" in purged["blocks"] and "USED" not in purged["blocks"]
    assert "HOLES" in purged["layers"] and "OUTLINE" not in purged["layers"] and "0" not in purged["layers"]
    assert "UNUSED_ST" in purged["text_styles"]
    doc = reread(ws, "m.dxf")
    assert "SPARE" not in doc.blocks and "USED" in doc.blocks and "Standard" in doc.styles
    assert "AGENTCAD" in doc.dimstyles and doc.dimstyles.get("AGENTCAD").dxf.dimtxsty in doc.styles
    assert ok(rt.validate_drawing("m.dxf"))["validation"]["passed"]
    assert err(apply(rt, "m.dxf", [{"op": "purge", "kinds": ["layer"]}]))["code"] == "INVALID_ENUM"


# --- annotate ---------------------------------------------------------------------------------------

def test_ordinate_dims_are_measured_and_validated(rt, ws, blank):
    r = ok(apply(rt, blank, [
        {"op": "add_rectangle", "corner": [10, 10], "width": 80, "height": 40},
        {"op": "add_ordinate_dim", "feature": [90, 50], "leader_end": [90, 70], "axis": "x", "origin": [10, 10], "tag": "ox"},
        {"op": "add_ordinate_dim", "feature": [90, 50], "leader_end": [110, 50], "axis": "y", "origin": [10, 10], "tag": "oy"}]))
    assert r["validation"]["passed"] and not r["validation"]["issues"]
    doc = reread(ws, blank)
    ox, oy = by_tag(doc, "ox"), by_tag(doc, "oy")
    assert ox.dxf.dimtype & 0x0F == 6 and ox.dxf.dimtype & 64 and not oy.dxf.dimtype & 64
    assert (ox.dxf.actual_measurement, oy.dxf.actual_measurement) == (A(80), A(40))
    ok(apply(rt, blank, [{"op": "add_ordinate_dim", "feature": [50, 10], "leader_end": [50, 0], "axis": "x",
                          "origin": [10, 10], "text": "99", "tag": "bad"}]))
    issues = ok(rt.validate_drawing(blank))["validation"]["issues"]
    assert any(i["code"] == "DIMENSION_TEXT_MISMATCH" for i in issues)
    assert err(apply(rt, blank, [{"op": "add_ordinate_dim", "feature": [0, 0], "leader_end": [0, 0], "axis": "x"}]))["code"] == "DEGENERATE_GEOMETRY"


def test_center_mark(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_circle", "center": [10, 20], "radius": 8, "tag": "c"},
                         {"op": "add_circle", "center": [50, 20], "radius": 2},
                         {"op": "add_center_mark", "target": "tag:c", "tag": "cm"},
                         {"op": "add_center_mark", "target": "$1", "extension": 1}]))
    doc = reread(ws, blank)
    h, v = by_tag(doc, "cm.h"), by_tag(doc, "cm.v")
    assert (h.dxf.start.x, h.dxf.end.x, h.dxf.start.y) == (A(-2), A(22), A(20))  # 8 + max(2, 4)
    assert (v.dxf.start.y, v.dxf.end.y) == (A(8), A(32))
    assert h.dxf.layer == "CENTER" and doc.layers.get("CENTER").dxf.linetype == "CENTER"
    small = [e for e in doc.modelspace().query("LINE") if abs(e.dxf.start.x - 47) < 1e-9]
    assert len(small) == 1 and small[0].dxf.end.x == A(53)
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [1, 0], "tag": "l"}]))
    assert err(apply(rt, blank, [{"op": "add_center_mark", "target": "tag:l"}]))["code"] == "UNSUPPORTED_ENTITY"


def test_text_style(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "create_text_style", "name": "CN", "font": "simsun.ttc", "width_factor": 0.8},
                         {"op": "create_text_style", "name": "GB"},
                         {"op": "add_text", "text": "技术要求", "insert": [0, 0], "height": 5, "style": "CN", "tag": "t"},
                         {"op": "add_mtext", "text": "A\nB", "insert": [0, 20], "style": "GB", "tag": "m"}]))
    doc = reread(ws, blank)
    cn, gb = doc.styles.get("CN"), doc.styles.get("GB")
    assert (cn.dxf.font, cn.dxf.width, cn.dxf.get("bigfont", "")) == ("simsun.ttc", A(0.8), "")
    assert (gb.dxf.font, gb.dxf.bigfont) == ("gbenor.shx", "gbcbig.shx")
    assert by_tag(doc, "t").dxf.style == "CN" and by_tag(doc, "m").dxf.style == "GB"
    assert err(apply(rt, blank, [{"op": "create_text_style", "name": "CN"}]))["code"] == "STYLE_EXISTS"
    assert err(apply(rt, blank, [{"op": "add_text", "text": "x", "insert": [0, 0], "style": "NOPE"}]))["code"] == "UNKNOWN_STYLE"
    assert err(apply(rt, blank, [{"op": "create_text_style", "name": "X", "font": "arial.ttf", "big_font": "gbcbig.shx"}]))["code"] == "INVALID_PARAMS"


def test_new_draw_ops_inside_blocks(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "define_block", "name": "NUT", "entities": [
        {"op": "add_polygon", "center": [0, 0], "sides": 6, "radius": 5, "mode": "circumscribed"},
        {"op": "add_hatch", "points": [[-1, -1], [1, -1], [1, 1], [-1, 1]]},
        {"op": "add_donut", "center": [0, 0], "outer_diameter": 1}]},
        {"op": "insert_block", "name": "NUT", "insert": [10, 10]}]))
    types = sorted(e.dxftype() for e in reread(ws, blank).blocks.get("NUT"))
    assert types == ["HATCH", "LWPOLYLINE", "LWPOLYLINE"]
