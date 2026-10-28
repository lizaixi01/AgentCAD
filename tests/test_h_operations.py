"""Test H: one test per implemented operation — parameters, success, resulting
geometry re-read from disk, and a diagnosable failure."""
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


# --- draw -----------------------------------------------------------------------------------------

def test_add_line(rt, ws, blank):
    r = ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": ["30mm", 40], "layer": "OUTLINE", "tag": "l"}]))
    assert len(r["changes"]["added"]) == 1
    e = by_tag(reread(ws, blank), "l")
    assert (e.dxf.end - e.dxf.start).magnitude == A(50)
    assert e.dxf.layer == "OUTLINE"
    assert err(apply(rt, blank, [{"op": "add_line", "start": [1, 1], "end": [1, 1]}]))["code"] == "DEGENERATE_GEOMETRY"
    assert err(apply(rt, blank, [{"op": "add_line", "start": [0, 0]}]))["code"] == "MISSING_PARAM"


def test_add_polyline_with_bulge(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_polyline", "points": [[0, 0], [10, 0, 1], [10, 10]], "closed": True, "tag": "p"}]))
    e = by_tag(reread(ws, blank), "p")
    pts = list(e.get_points("xyb"))
    assert e.closed and len(pts) == 3 and pts[1][2] == A(1)
    assert err(apply(rt, blank, [{"op": "add_polyline", "points": [[0, 0]]}]))["code"] == "TOO_FEW_POINTS"
    assert err(apply(rt, blank, [{"op": "add_polyline", "points": [[0, "x"], [1, 1]]}]))["code"] == "INVALID_LENGTH"


def test_add_rectangle_plain_rounded_rotated(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "tag": "r"},
        {"op": "add_rectangle", "center": [0, 0], "width": 40, "height": 20, "corner_radius": 5, "tag": "rr"},
        {"op": "add_rectangle", "corner": [0, 0], "width": 10, "height": 10, "rotation": 45, "tag": "rot"}]))
    doc = reread(ws, blank)
    r = by_tag(doc, "r")
    assert [tuple(p) for p in r.get_points("xy")] == [(0, 0), (100, 0), (100, 60), (0, 60)]
    rr = by_tag(doc, "rr")
    assert len(rr) == 8 and rr.closed
    rot = [tuple(p) for p in by_tag(doc, "rot").get_points("xy")]
    assert rot[1][0] == A(10 / math.sqrt(2)) and rot[1][1] == A(10 / math.sqrt(2))
    e = err(apply(rt, blank, [{"op": "add_rectangle", "corner": [0, 0], "width": 10, "height": 10, "corner_radius": 6}]))
    assert e["code"] == "RADIUS_TOO_LARGE" and e["category"] == "geometry"
    assert err(apply(rt, blank, [{"op": "add_rectangle", "width": 1, "height": 1}]))["code"] == "AMBIGUOUS_PARAMS"
    assert err(apply(rt, blank, [{"op": "add_rectangle", "corner": [0, 0], "width": -1, "height": 1}]))["code"] == "OUT_OF_RANGE"


def test_add_circle(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_circle", "center": [5, 5], "diameter": 8, "tag": "c"}]))
    c = by_tag(reread(ws, blank), "c")
    assert c.dxf.radius == A(4) and tuple(c.dxf.center)[:2] == (5, 5)
    assert err(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "diameter": 2}]))["code"] == "AMBIGUOUS_PARAMS"
    assert err(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 0}]))["code"] == "OUT_OF_RANGE"


def test_add_arc_center_and_3p(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_arc", "center": [0, 0], "radius": 10, "start_angle": -90, "end_angle": 450, "tag": "a"},
        {"op": "add_arc", "start": [10, 0], "mid": [0, 10], "end": [-10, 0], "tag": "a3"}]))
    doc = reread(ws, blank)
    a = by_tag(doc, "a")
    assert a.dxf.start_angle == A(270) and a.dxf.end_angle == A(90)  # normalised
    a3 = by_tag(doc, "a3")
    assert a3.dxf.radius == A(10) and a3.dxf.start_angle == A(0) and a3.dxf.end_angle == A(180)
    assert err(apply(rt, blank, [{"op": "add_arc", "center": [0, 0], "radius": 1, "start_angle": 0, "end_angle": 360}]))["code"] == "DEGENERATE_GEOMETRY"
    assert err(apply(rt, blank, [{"op": "add_arc", "start": [0, 0], "mid": [1, 0], "end": [2, 0]}]))["code"] == "DEGENERATE_GEOMETRY"


def test_add_ellipse(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_ellipse", "center": [0, 0], "rx": 5, "ry": 10, "tag": "e"}]))
    e = by_tag(reread(ws, blank), "e")
    assert e.dxf.ratio == A(0.5) and e.dxf.major_axis.magnitude == A(10)
    pts = [p for p in e.vertices([0, math.pi / 2])]
    assert max(abs(p.y) for p in pts) == A(10)
    assert err(apply(rt, blank, [{"op": "add_ellipse", "center": [0, 0], "rx": 0, "ry": 1}]))["code"] == "OUT_OF_RANGE"


def test_add_spline_point_text_mtext(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_spline", "fit_points": [[0, 0], [10, 5], [20, 0]], "tag": "s"},
        {"op": "add_point", "location": [3, 4], "tag": "pt"},
        {"op": "add_text", "text": "HELLO", "insert": [0, 0], "height": 5, "align": "middle_center", "tag": "t"},
        {"op": "add_mtext", "text": "LINE1\nLINE2", "insert": [0, 20], "char_height": 3, "tag": "mt"}]))
    doc = reread(ws, blank)
    assert len(by_tag(doc, "s").fit_points) == 3
    assert tuple(by_tag(doc, "pt").dxf.location)[:2] == (3, 4)
    t = by_tag(doc, "t")
    assert t.dxf.text == "HELLO" and t.dxf.height == A(5)
    assert by_tag(doc, "mt").plain_text().splitlines() == ["LINE1", "LINE2"]
    assert err(apply(rt, blank, [{"op": "add_spline", "fit_points": [[0, 0]]}]))["code"] == "TOO_FEW_POINTS"
    assert err(apply(rt, blank, [{"op": "add_text", "text": "", "insert": [0, 0]}]))["code"] == "INVALID_STRING"
    assert err(apply(rt, blank, [{"op": "add_text", "text": "x", "insert": [0, 0], "align": "diagonal"}]))["code"] == "INVALID_ENUM"


# --- annotation -------------------------------------------------------------------------------------

def test_dimensions_measure_actual_geometry(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_circle", "center": [50, 50], "radius": 10, "tag": "c"},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [100, 0], "tag": "dh"},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [30, 40], "orientation": "vertical", "offset": -5, "tag": "dv"},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [30, 40], "orientation": "aligned", "offset": 5, "tag": "da"},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [30, 40], "orientation": "rotated", "angle": 30, "tag": "dr"},
        {"op": "add_radius_dim", "target": "tag:c", "tag": "drad"},
        {"op": "add_diameter_dim", "target": "$0", "text": "%%c<>", "tag": "ddia"},
        {"op": "add_angular_dim", "center": [0, 0], "p1": [10, 0], "p2": [0, 10], "tag": "dang"}]))
    v = ok(rt.validate_drawing(blank, requirements=[
        {"type": "dimension", "kind": "linear", "value": 100},
        {"type": "dimension", "kind": "linear", "value": 40},
        {"type": "dimension", "kind": "aligned", "value": 50},
        {"type": "dimension", "kind": "linear", "value": 30 * math.cos(math.radians(30)) + 40 * math.sin(math.radians(30))},
        {"type": "dimension", "kind": "radius", "value": 10},
        {"type": "dimension", "kind": "diameter", "value": 20},
        {"type": "dimension", "kind": "angular", "value": 90}]))["validation"]
    assert all(r["status"] == "pass" for r in v["requirements"]), v["requirements"]
    doc = reread(ws, blank)
    for t in ("dh", "dv", "da", "drad", "ddia", "dang"):
        d = by_tag(doc, t)
        assert d.dxf.geometry in doc.blocks  # rendered block exists
        assert d.dxf.hasattr("actual_measurement")  # group 42 written
    assert err(apply(rt, blank, [{"op": "add_radius_dim", "target": "tag:dh"}]))["code"] == "UNSUPPORTED_ENTITY"
    assert err(apply(rt, blank, [{"op": "add_linear_dim", "p1": [0, 0], "p2": [0, 0]}]))["code"] == "DEGENERATE_GEOMETRY"


def test_leader_table_title_block(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "add_leader", "points": [[0, 0], [10, 10], [20, 10]], "text": "4X THRU", "tag": "ld"},
        {"op": "add_table", "insert": [0, 100], "rows": [["ITEM", "QTY"], ["Bolt M6", "4"]], "col_widths": [40, 20], "tag": "bom"},
        {"op": "add_title_block", "insert": [287, 10], "fields": {"TITLE": "PLATE", "DWG_NO": "AC-001"}, "tag": "tb"}]))
    doc = reread(ws, blank)
    assert by_tag(doc, "ld").dxftype() == "LEADER"
    assert by_tag(doc, "bom.r1c0").dxf.text == "Bolt M6"
    tb = by_tag(doc, "tb")
    assert tb.get_attrib_text("TITLE") == "PLATE" and tb.get_attrib_text("UNITS") == "mm"
    assert err(apply(rt, blank, [{"op": "add_title_block", "insert": [0, 0], "fields": {"COLOR": "x"}}]))["code"] == "UNKNOWN_FIELD"
    assert err(apply(rt, blank, [{"op": "add_table", "insert": [0, 0], "rows": [["a", "b", "c"]], "col_widths": [1]}]))["code"] == "INVALID_TABLE"


# --- edit ---------------------------------------------------------------------------------------------

def test_move_copy_rotate_scale(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0], "tag": "l"},
                         {"op": "add_circle", "center": [0, 0], "radius": 1, "tag": "c"}]))
    r = ok(apply(rt, blank, [
        {"op": "move", "target": "tag:l", "delta": [5, 5]},
        {"op": "copy", "target": "tag:c", "delta": [10, 0], "count": 3},
        {"op": "rotate", "target": "tag:l", "angle": 90, "center": [5, 5]},
        {"op": "scale", "target": "tag:c", "factor": 2, "center": [0, 0]}]))
    assert len(r["results"][1]["created"]) == 3
    doc = reread(ws, blank)
    l = by_tag(doc, "l")
    assert (l.dxf.start.x, l.dxf.start.y) == (A(5), A(5)) and (l.dxf.end.x, l.dxf.end.y) == (A(5), A(15))
    circles = sorted((e.dxf.center.x, e.dxf.radius) for e in doc.modelspace().query("CIRCLE"))
    assert circles == [(A(0), A(2)), (A(10), A(1)), (A(20), A(1)), (A(30), A(1))]
    assert sum(1 for e in doc.modelspace() if get_tag(e) == "c") == 1  # copies do not inherit the tag
    assert err(apply(rt, blank, [{"op": "move", "target": "tag:nope", "delta": [1, 1]}]))["code"] == "ENTITY_NOT_FOUND"
    assert err(apply(rt, blank, [{"op": "move", "target": "tag:l"}]))["code"] == "MISSING_PARAM"
    assert err(apply(rt, blank, [{"op": "scale", "target": "tag:l", "factor": 0, "center": [0, 0]}]))["code"] == "OUT_OF_RANGE"


def test_mirror_keeps_wcs_and_readable_text(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_arc", "center": [10, 0], "radius": 5, "start_angle": 0, "end_angle": 90, "tag": "a"},
                         {"op": "add_polyline", "points": [[10, 0], [20, 0, 0.5], [20, 10]], "tag": "p"},
                         {"op": "add_text", "text": "T", "insert": [10, 5], "tag": "t"}]))
    r = ok(apply(rt, blank, [{"op": "mirror", "target": ["tag:a", "tag:p", "tag:t"], "p1": [0, 0], "p2": [0, 1]}]))
    doc = reread(ws, blank)
    arc_m = doc.entitydb[r["results"][0]["created"][0]]
    assert tuple(arc_m.dxf.extrusion) == (0, 0, 1)
    assert arc_m.dxf.center.x == A(-10)
    s = arc_m.start_point
    e = arc_m.end_point
    got = sorted([(round(s.x, 6), round(s.y, 6)), (round(e.x, 6), round(e.y, 6))])
    assert got == [(-15.0, 0.0), (-10.0, 5.0)]  # mirror of (15,0) and (10,5)
    pl = doc.entitydb[r["results"][0]["created"][1]]
    pts = list(pl.get_points("xyb"))
    assert pts[1][0] == A(-20) and pts[1][2] == A(-0.5)  # bulge sign flips
    tm = doc.entitydb[r["results"][0]["created"][2]]
    assert tm.dxf.insert.x == A(-10) and tuple(tm.dxf.extrusion) == (0, 0, 1)
    assert err(apply(rt, blank, [{"op": "mirror", "target": "tag:a", "p1": [0, 0], "p2": [0, 0]}]))["code"] == "DEGENERATE_GEOMETRY"


def test_arrays(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "tag": "c"}]))
    r = ok(apply(rt, blank, [{"op": "array_rect", "target": "tag:c", "rows": 2, "cols": 3, "row_spacing": 10, "col_spacing": 20}]))
    assert len(r["results"][0]["created"]) == 5
    r = ok(apply(rt, blank, [{"op": "add_circle", "center": [100, 0], "radius": 1},
                             {"op": "array_polar", "target": "$0", "center": [0, 0], "count": 4}]))
    doc = reread(ws, blank)
    centers = {(round(e.dxf.center.x, 6), round(e.dxf.center.y, 6)) for e in doc.modelspace().query("CIRCLE")}
    assert {(100, 0), (0, 100), (-100, 0), (0, -100)} <= centers
    assert {(0, 0), (20, 0), (40, 0), (0, 10), (20, 10), (40, 10)} <= centers
    e = err(apply(rt, blank, [{"op": "array_rect", "target": "tag:c", "rows": 1000, "cols": 1000}]))
    assert e["code"] == "OUT_OF_RANGE" or e["code"] == "BUDGET_EXCEEDED"


def test_delete_and_large_delete_guard(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_point", "location": [i, 0], "layer": "PTS"} for i in range(60)]))
    e = err(apply(rt, blank, [{"op": "delete", "target": {"layer": "PTS"}}]))
    assert e["code"] == "CONFIRMATION_REQUIRED" and e["category"] == "policy"
    assert len(reread(ws, blank).modelspace()) == 60  # nothing deleted
    r = ok(apply(rt, blank, [{"op": "delete", "target": {"layer": "PTS"}, "confirm_large": True}]))
    assert len(r["changes"]["deleted"]) == 60 and len(reread(ws, blank).modelspace()) == 0
    assert err(apply(rt, blank, [{"op": "delete", "target": {}}]))["code"] == "EMPTY_SELECTOR"


def test_set_properties_and_modify(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "tag": "c"},
                         {"op": "add_line", "start": [0, 0], "end": [1, 0], "tag": "l"}]))
    ok(apply(rt, blank, [{"op": "set_properties", "target": "tag:c", "layer": "HOLES", "color": 1, "linetype": "DASHED"},
                         {"op": "modify", "target": "tag:c", "set": {"radius": "5mm", "center": [2, 2]}},
                         {"op": "modify", "target": "tag:l", "set": {"end": [0, 7]}}]))
    doc = reread(ws, blank)
    c = by_tag(doc, "c")
    assert (c.dxf.layer, c.dxf.color, c.dxf.linetype, c.dxf.radius) == ("HOLES", 1, "DASHED", A(5))
    assert by_tag(doc, "l").dxf.end.y == A(7)
    assert err(apply(rt, blank, [{"op": "modify", "target": "tag:c", "set": {"start": [0, 0]}}]))["code"] == "UNKNOWN_FIELD"
    assert err(apply(rt, blank, [{"op": "set_properties", "target": "tag:c", "linetype": "WAVY"}]))["code"] == "UNKNOWN_LINETYPE"


def test_stretch(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "tag": "r"},
                         {"op": "add_circle", "center": [90, 10], "radius": 4, "tag": "h"},
                         {"op": "add_circle", "center": [10, 10], "radius": 4, "tag": "h0"},
                         {"op": "add_linear_dim", "p1": [0, 0], "p2": [100, 0], "offset": -10, "tag": "d"}]))
    ok(apply(rt, blank, [{"op": "stretch", "window": [[50, -50], [200, 100]], "delta": [20, 0]}]))
    doc = reread(ws, blank)
    xs = sorted(p[0] for p in by_tag(doc, "r").get_points("xy"))
    assert xs == [0, 0, 120, 120]
    assert by_tag(doc, "h").dxf.center.x == A(110) and by_tag(doc, "h0").dxf.center.x == A(10)
    v = ok(rt.validate_drawing(blank, detail=True, requirements=[{"type": "dimension", "value": 120}]))["validation"]
    assert v["requirements"][0]["status"] == "pass"
    assert err(apply(rt, blank, [{"op": "stretch", "window": [[0, 0]], "delta": [1, 0]}]))["code"] == "INVALID_WINDOW"


def test_offset(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0], "tag": "l"},
                         {"op": "add_circle", "center": [0, 0], "radius": 5, "tag": "c"},
                         {"op": "add_rectangle", "corner": [0, 0], "width": 10, "height": 10, "tag": "r"}]))
    r = ok(apply(rt, blank, [{"op": "offset", "target": "tag:l", "distance": 2, "side_point": [5, -1]},
                             {"op": "offset", "target": "tag:c", "distance": 1, "side_point": [0, 0]},
                             {"op": "offset", "target": "tag:r", "distance": 1, "side_point": [50, 50]},
                             {"op": "offset", "target": "tag:r", "distance": 1, "side_point": [5, 5]}]))
    doc = reread(ws, blank)
    h = [x["created"][0] for x in r["results"]]
    l2 = doc.entitydb[h[0]]
    assert l2.dxf.start.y == A(-2) and l2.dxf.end.y == A(-2)
    assert doc.entitydb[h[1]].dxf.radius == A(4)
    assert sorted(tuple(p) for p in doc.entitydb[h[2]].get_points("xy")) == [(-1, -1), (-1, 11), (11, -1), (11, 11)]
    assert sorted(tuple(p) for p in doc.entitydb[h[3]].get_points("xy")) == [(1, 1), (1, 9), (9, 1), (9, 9)]
    assert err(apply(rt, blank, [{"op": "offset", "target": "tag:c", "distance": 10, "side_point": [0, 0]}]))["code"] == "OFFSET_COLLAPSES"


def test_trim_and_extend(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [100, 0], "tag": "h"},
                         {"op": "add_line", "start": [30, -10], "end": [30, 10], "tag": "v1"},
                         {"op": "add_line", "start": [70, -10], "end": [70, 10], "tag": "v2"},
                         {"op": "add_line", "start": [0, 50], "end": [20, 50], "tag": "e"},
                         {"op": "add_circle", "center": [50, 50], "radius": 10, "tag": "c"}]))
    r = ok(apply(rt, blank, [{"op": "trim", "target": "tag:h", "edges": ["tag:v1", "tag:v2"], "pick": [50, 0]}]))
    doc = reread(ws, blank)
    h = by_tag(doc, "h")
    assert h.dxf.end.x == A(30)
    second = doc.entitydb[r["results"][0]["created"][0]]
    assert (second.dxf.start.x, second.dxf.end.x) == (A(70), A(100))
    ok(apply(rt, blank, [{"op": "extend", "target": "tag:e", "edges": "tag:c"}]))
    assert by_tag(reread(ws, blank), "e").dxf.end.x == A(40)
    # trim a circle between two lines -> arc
    ok(apply(rt, blank, [{"op": "add_line", "start": [50, 30], "end": [50, 70], "tag": "cut"},
                         {"op": "trim", "target": "tag:c", "edges": "tag:cut", "pick": [60, 50]}]))
    arc = by_tag(reread(ws, blank), "c")
    assert arc.dxftype() == "ARC" and arc.dxf.start_angle == A(90) and arc.dxf.end_angle == A(270)
    assert err(apply(rt, blank, [{"op": "trim", "target": "tag:e", "edges": "tag:v1", "pick": [5, 50]}]))["code"] == "NO_INTERSECTION"
    assert err(apply(rt, blank, [{"op": "extend", "target": "tag:v1", "edges": "tag:v2"}]))["code"] == "NO_BOUNDARY_INTERSECTION"


def test_fillet_and_chamfer(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 0], "end": [50, 0], "tag": "a"},
                         {"op": "add_line", "start": [0, 0], "end": [0, 50], "tag": "b"},
                         {"op": "add_line", "start": [100, 0], "end": [150, 0], "tag": "c"},
                         {"op": "add_line", "start": [100, 0], "end": [100, 50], "tag": "d"}]))
    r = ok(apply(rt, blank, [{"op": "fillet", "line1": "tag:a", "line2": "tag:b", "radius": 10, "tag": "f"},
                             {"op": "chamfer", "line1": "tag:c", "line2": "tag:d", "d1": 5, "d2": 8}]))
    doc = reread(ws, blank)
    arc = by_tag(doc, "f")
    assert arc.dxf.radius == A(10) and (arc.dxf.center.x, arc.dxf.center.y) == (A(10), A(10))
    assert by_tag(doc, "a").dxf.start.x == A(10) and by_tag(doc, "b").dxf.start.y == A(10)
    ch = doc.entitydb[r["results"][1]["created"][0]]
    assert {(round(ch.dxf.start.x, 6), round(ch.dxf.start.y, 6)), (round(ch.dxf.end.x, 6), round(ch.dxf.end.y, 6))} == {(105, 0), (100, 8)}
    c = ok(rt.apply_constraints(blank, [{"type": "tangent", "a": "tag:f", "b": "tag:a"},
                                        {"type": "tangent", "a": "tag:f", "b": "tag:b"}]))
    assert c["all_satisfied"]
    assert err(apply(rt, blank, [{"op": "fillet", "line1": "tag:a", "line2": "tag:b", "radius": 500}]))["code"] == "FILLET_RADIUS_TOO_LARGE"
    ok(apply(rt, blank, [{"op": "add_line", "start": [0, 200], "end": [10, 200], "tag": "p1"},
                         {"op": "add_line", "start": [0, 210], "end": [10, 210], "tag": "p2"}]))
    assert err(apply(rt, blank, [{"op": "chamfer", "line1": "tag:p1", "line2": "tag:p2", "d1": 1}]))["code"] == "PARALLEL_LINES"


def test_explode(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "add_rectangle", "corner": [0, 0], "width": 10, "height": 5, "tag": "r"}]))
    r = ok(apply(rt, blank, [{"op": "explode", "target": "tag:r"}]))
    assert len(r["results"][0]["created"]) == 4
    assert [e.dxftype() for e in reread(ws, blank).modelspace()] == ["LINE"] * 4


# --- layers / blocks -------------------------------------------------------------------------------------

def test_layers(rt, ws, blank):
    ok(apply(rt, blank, [{"op": "create_layer", "name": "CUT", "color": 1, "linetype": "DASHED", "lineweight": 35},
                         {"op": "add_line", "start": [0, 0], "end": [1, 0], "layer": "CUT", "tag": "l"},
                         {"op": "modify_layer", "name": "CUT", "color": 5, "on": False, "locked": True, "new_name": "CUT2"}]))
    doc = reread(ws, blank)
    ly = doc.layers.get("CUT2")
    assert (ly.color, ly.dxf.linetype, ly.is_on(), ly.is_locked()) == (5, "DASHED", False, True)
    assert by_tag(doc, "l").dxf.layer == "CUT2"
    assert err(apply(rt, blank, [{"op": "create_layer", "name": "CUT2"}]))["code"] == "LAYER_EXISTS"
    ok(apply(rt, blank, [{"op": "create_layer", "name": "CUT2", "if_exists": "skip"}]))
    assert err(apply(rt, blank, [{"op": "delete_layer", "name": "CUT2"}]))["code"] == "LAYER_NOT_EMPTY"
    assert err(apply(rt, blank, [{"op": "delete_layer", "name": "0"}]))["code"] == "LAYER_PROTECTED"
    ok(apply(rt, blank, [{"op": "delete_layer", "name": "CUT2", "delete_entities": True}]))
    assert "CUT2" not in reread(ws, blank).layers


def test_blocks_and_attributes(rt, ws, blank):
    ok(apply(rt, blank, [
        {"op": "define_block", "name": "BOLT", "entities": [{"op": "add_circle", "center": [0, 0], "radius": 3},
                                                            {"op": "add_line", "start": [-4, 0], "end": [4, 0]}],
         "attributes": [{"tag": "SIZE", "insert": [0, 5], "height": 2, "default": "M6"}]},
        {"op": "insert_block", "name": "BOLT", "insert": [10, 10], "attributes": {"SIZE": "M8"}, "tag": "b1"},
        {"op": "insert_block", "name": "BOLT", "insert": [30, 10], "rotation": 90, "scale": 2, "tag": "b2"},
        {"op": "set_attributes", "target": "tag:b2", "values": {"SIZE": "M10"}}]))
    doc = reread(ws, blank)
    assert len(doc.blocks.get("BOLT")) >= 2
    b1, b2 = by_tag(doc, "b1"), by_tag(doc, "b2")
    assert b1.get_attrib_text("SIZE") == "M8" and b2.get_attrib_text("SIZE") == "M10"
    assert b2.dxf.xscale == A(2) and b2.dxf.rotation == A(90)
    assert err(apply(rt, blank, [{"op": "insert_block", "name": "NUT", "insert": [0, 0]}]))["code"] == "BLOCK_NOT_FOUND"
    assert err(apply(rt, blank, [{"op": "define_block", "name": "BOLT", "entities": []}]))["code"] == "BLOCK_EXISTS"
    assert err(apply(rt, blank, [{"op": "insert_block", "name": "BOLT", "insert": [0, 0], "attributes": {"X": 1}}]))["code"] == "UNKNOWN_ATTRIBUTE"
    ok(apply(rt, blank, [{"op": "define_block", "name": "BOLT", "if_exists": "redefine",
                          "entities": [{"op": "add_circle", "center": [0, 0], "radius": 5}]}]))
    assert reread(ws, blank).blocks.get("BOLT").query("CIRCLE")[0].dxf.radius == A(5)


def test_unknown_op_and_param_are_diagnosable(rt, blank):
    e = err(apply(rt, blank, [{"op": "add_cirle", "center": [0, 0], "radius": 1}]))
    assert e["code"] == "UNKNOWN_OP" and "add_circle" in e["hint"] and e["op_index"] == 0
    e = err(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "colour": 3}]))
    assert e["code"] == "UNKNOWN_PARAM" and "color" in e["hint"]


def test_batch_refs_and_tags(rt, ws, blank):
    r = ok(apply(rt, blank, [{"op": "add_circle", "center": [0, 0], "radius": 2},
                             {"op": "copy", "target": "$0", "delta": [10, 0]},
                             {"op": "move", "target": "$1", "delta": [0, 5]}]))
    c2 = reread(ws, blank).entitydb[r["results"][1]["created"][0]]
    assert (c2.dxf.center.x, c2.dxf.center.y) == (A(10), A(5))
    assert err(apply(rt, blank, [{"op": "move", "target": "$5", "delta": [0, 1]}]))["code"] == "BAD_REFERENCE"


def test_units_conversion_and_explicitness(rt, ws):
    ok(rt.create_drawing("inch.dxf", units="in"))
    ok(rt.apply_operations("inch.dxf", [{"op": "add_circle", "center": [0, 0], "diameter": "25.4mm", "tag": "c"}]))
    assert by_tag(reread(ws, "inch.dxf"), "c").dxf.radius == A(0.5)
    assert reread(ws, "inch.dxf").header["$INSUNITS"] == 1
    e = err(rt.create_drawing("x.dxf", units="furlong"))
    assert e["code"] == "UNKNOWN_UNIT"
