"""Runtime behaviour derived from AutoCAD 2027 observations (research/autocad,
docs/research/autocad-observations.md). These tests do not need AutoCAD."""
from __future__ import annotations

import ezdxf
import pytest

from conftest import ok, reread

A = pytest.approx


def foreign(ws, name, build):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    build(doc)
    doc.saveas(ws / name)
    return name


def codes(rt, name):
    return {i["code"] for i in ok(rt.validate_drawing(name))["validation"]["issues"]}


def test_negative_z_extrusion_is_read_in_wcs(rt, ws):
    """AutoCAD keeps extrusion (0,0,-1) entities as they are; OCS x is mirrored."""
    def build(doc):
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "OUTLINE"})
        m.add_circle((-90, 10), 4, dxfattribs={"extrusion": (0, 0, -1)})          # WCS center (90, 10)
        m.add_arc((-50, 30), 5, 0, 90, dxfattribs={"extrusion": (0, 0, -1)})      # WCS: center (50,30), 90..180
    name = foreign(ws, "negz.dxf", build)
    ents = ok(rt.inspect_entities(name))["entities"]
    circle = next(e for e in ents if e["type"] == "CIRCLE")
    arc = next(e for e in ents if e["type"] == "ARC")
    assert circle["center"] == [90.0, 10.0]
    assert (arc["center"], arc["start_angle"], arc["end_angle"]) == ([50.0, 30.0], 90.0, 180.0)
    v = ok(rt.validate_drawing(name, requirements=[{"type": "hole", "center": [90, 10], "diameter": 8}]))["validation"]
    assert v["requirements"][0]["status"] == "pass"
    # editing works in WCS terms: offset the -Z circle outward, trim the -Z arc
    ok(rt.apply_operations(name, [{"op": "offset", "target": circle["id"], "distance": 1, "side_point": [200, 10]},
                                  {"op": "add_line", "start": [47, 0], "end": [47, 60], "tag": "cut"}]))
    out = ok(rt.inspect_entities(name, filter={"type": "CIRCLE"}))["entities"]
    assert sorted((c["center"][0], c["radius"]) for c in out) == [(90.0, 4.0), (90.0, 5.0)]
    # x=47 crosses the arc at 126.87 deg; remove the part towards 180 deg
    ok(rt.apply_operations(name, [{"op": "trim", "target": arc["id"], "edges": "tag:cut", "pick": [45.1, 31]}]))
    arc2 = ok(rt.inspect_entities(name, ids=[arc["id"]]))["entities"][0]
    assert arc2["center"] == [50.0, 30.0] and arc2["start_angle"] == A(90.0) and arc2["end_angle"] == A(126.869898, abs=1e-5)


def test_xdata_that_autocad_rejects_is_flagged(rt, ws):
    def unregistered(doc):
        doc.modelspace().add_line((0, 0), (10, 0)).set_xdata("NOTREG", [(1000, "x")])
    def big(doc):
        doc.appids.add("BIG")
        doc.modelspace().add_line((0, 0), (10, 0)).set_xdata("BIG", [(1000, "x" * 250)] * 80)
    assert "XDATA_APPID_UNREGISTERED" in codes(rt, foreign(ws, "unreg.dxf", unregistered))
    assert "XDATA_TOO_LARGE" in codes(rt, foreign(ws, "big.dxf", big))
    # our own tags are always registered and small
    ok(rt.create_drawing("own.dxf"))
    ok(rt.apply_operations("own.dxf", [{"op": "add_point", "location": [0, 0], "tag": "p" * 200}]))
    assert not {"XDATA_APPID_UNREGISTERED", "XDATA_TOO_LARGE"} & codes(rt, "own.dxf")


def test_arc_angles_and_negative_radius(rt, ws):
    def bad(doc):
        doc.modelspace().add_arc((0, 0), 10, -90, 450)
        doc.modelspace().add_circle((50, 0), 5).dxf.radius = -5  # AutoCAD silently turns this into 1.0
    c = codes(rt, foreign(ws, "bad.dxf", bad))
    assert "ARC_ANGLE_NOT_NORMALIZED" in c and "DEGENERATE_GEOMETRY" in c


def test_angular_dimension_stores_radians(rt, ws, blank):
    """AutoCAD stores the measurement (group 42) of angular dimensions in radians."""
    import math
    ok(rt.apply_operations(blank, [{"op": "add_angular_dim", "center": [0, 0], "p1": [10, 0], "p2": [0, 10], "tag": "a"}]))
    from conftest import by_tag
    d = by_tag(reread(ws, blank), "a")
    assert d.dxf.actual_measurement == A(math.pi / 2)
    v = ok(rt.validate_drawing(blank, requirements=[{"type": "dimension", "kind": "angular", "value": 90}]))["validation"]
    assert v["requirements"][0]["status"] == "pass" and "DIMENSION_STALE" not in {i["code"] for i in v["issues"]}


def test_three_point_arc_clockwise_pick_order(rt, ws, blank):
    ok(rt.apply_operations(blank, [{"op": "add_arc", "start": [-10, 0], "mid": [0, 10], "end": [10, 0], "tag": "a"}]))
    from conftest import by_tag
    a = by_tag(reread(ws, blank), "a")
    assert (a.dxf.start_angle, a.dxf.end_angle) == (A(0), A(180))  # passes through the mid point (0, 10)


def test_mirrored_block_is_really_mirrored(rt, ws, blank):
    ok(rt.apply_operations(blank, [
        {"op": "define_block", "name": "B", "entities": [{"op": "add_circle", "center": [5, 0], "radius": 1}],
         "attributes": [{"tag": "N", "insert": [0, 2], "height": 2, "default": "X"}]},
        {"op": "insert_block", "name": "B", "insert": [10, 10], "tag": "b"},
        {"op": "mirror", "target": "tag:b", "p1": [0, 0], "p2": [0, 1], "keep_original": False}]))
    from conftest import by_tag
    b = by_tag(reread(ws, blank), "b")
    world = [v for v in b.virtual_entities() if v.dxftype() == "CIRCLE"][0]
    from agentcad.model import circle_wcs
    assert circle_wcs(world)[0] == (A(-15), A(10))  # block content mirrored (virtual entity is -Z: read in WCS)
    att = b.attribs[0]
    assert att.dxf.halign == 2 and att.dxf.align_point.x == A(-10)  # attribute text stays readable
