"""Constraint checking (all types) vs. sequential direct enforcement (subset) — kept distinct."""
from __future__ import annotations

import pytest

from conftest import by_tag, ok, reread

A = pytest.approx


@pytest.fixture
def geo(rt, blank):
    ok(rt.apply_operations(blank, [
        {"op": "add_line", "start": [0, 0], "end": [10, 0], "tag": "h"},
        {"op": "add_line", "start": [10, 0], "end": [10, 10], "tag": "v"},
        {"op": "add_line", "start": [0, 5], "end": [10, 5], "tag": "h2"},
        {"op": "add_line", "start": [20, 0], "end": [25, 9], "tag": "skew"},
        {"op": "add_circle", "center": [5, 10], "radius": 5, "tag": "c1"},
        {"op": "add_circle", "center": [5, 10], "radius": 2, "tag": "c2"},
        {"op": "add_circle", "center": [30, 30], "radius": 3, "tag": "c3"},
        {"op": "add_line", "start": [-5, 0], "end": [-5, 10], "tag": "axis"},
        {"op": "add_point", "location": [-8, 3], "tag": "pl"},
        {"op": "add_point", "location": [-2, 3], "tag": "pr"}]))
    return blank


def test_check_all_types(rt, geo):
    cs = [{"type": "coincident", "a": "tag:h@end", "b": "tag:v@start"},
          {"type": "perpendicular", "a": "tag:h", "b": "tag:v"},
          {"type": "parallel", "a": "tag:h", "b": "tag:h2"},
          {"type": "horizontal", "a": "tag:h"}, {"type": "vertical", "a": "tag:v"},
          {"type": "tangent", "a": "tag:c1", "b": "tag:h2"},
          {"type": "concentric", "a": "tag:c1", "b": "tag:c2"},
          {"type": "distance", "a": "tag:h@start", "b": "tag:v@end", "value": 200 ** 0.5},
          {"type": "length", "a": "tag:h", "value": 10}, {"type": "angle", "a": "tag:h", "b": "tag:v", "value": 90},
          {"type": "symmetric", "a": "tag:pl@location", "b": "tag:pr@location", "axis": "tag:axis"},
          {"type": "equal", "a": "tag:h", "b": "tag:v"}, {"type": "radius", "a": "tag:c1", "value": 5},
          {"type": "diameter", "a": "tag:c2", "value": 4}, {"type": "fixed", "a": "tag:c3@center", "value": [30, 30]}]
    r = ok(rt.apply_constraints(geo, cs))
    bad = [x for x in r["constraints"] if not x["satisfied"]]
    assert not bad, bad
    r = ok(rt.apply_constraints(geo, [{"type": "perpendicular", "a": "tag:h", "b": "tag:skew"}]))
    c = r["constraints"][0]
    assert not c["satisfied"] and c["error"] > 25 and c["entities"]


def test_enforce_subset_and_recheck(rt, ws, geo):
    r = ok(rt.apply_constraints(geo, [{"type": "perpendicular", "a": "tag:h", "b": "tag:skew"},
                                      {"type": "length", "a": "tag:skew", "value": 20},
                                      {"type": "concentric", "a": "tag:c1", "b": "tag:c3"}], mode="enforce"))
    assert r["solver"] == "sequential-direct" and r["all_satisfied"]
    doc = reread(ws, geo)
    s = by_tag(doc, "skew")
    assert (s.dxf.end.x, s.dxf.end.y) == (A(20), A(20))
    assert (by_tag(doc, "c3").dxf.center.x, by_tag(doc, "c3").dxf.center.y) == (A(5), A(10))


def test_conflicting_constraints_not_saved(rt, ws, geo):
    before = (ws / geo).read_bytes()
    r = rt.apply_constraints(geo, [{"type": "length", "a": "tag:h", "value": 20},
                                   {"type": "length", "a": "tag:h", "value": 30}], mode="enforce")
    assert not r["ok"] and r["error"]["code"] == "CONSTRAINT_CONFLICT"
    assert (ws / geo).read_bytes() == before
    r = rt.apply_constraints(geo, [{"type": "tangent", "a": "tag:c1", "b": "tag:h"}], mode="enforce")
    assert r["error"]["code"] == "UNSUPPORTED_ENFORCEMENT"  # check-only type


def test_constraint_input_errors(rt, geo):
    r = ok(rt.apply_constraints(geo, [{"type": "coincident", "a": "tag:h", "b": "tag:v@start"},
                                      {"type": "length", "a": "tag:h"}, {"type": "radius", "a": "tag:h", "value": 1}]))
    codes = [x["error_detail"]["code"] for x in r["constraints"]]
    assert codes == ["BAD_POINT_REF", "MISSING_PARAM", "UNSUPPORTED_ENTITY"]
    r = ok(rt.apply_constraints(geo, [{"type": "colinear"}]))
    assert r["constraints"][0]["error_detail"]["code"] == "UNKNOWN_CONSTRAINT" and not r["all_satisfied"]
