"""Test D: deliberately broken inputs and drawings are detected with typed, located errors."""
from __future__ import annotations

from conftest import PLATE_SPEC, ok


def codes(report):
    return {i["code"] for i in report["issues"]}


def test_contradictory_dimension_requirements(rt, ws):
    spec = dict(PLATE_SPEC, holes=[{"pattern": "corners", "diameter": 30, "edge_offset": 10}])
    r = rt.draw_from_spec(spec, "x.dxf")
    assert not r["ok"]
    e = r["error"]
    assert e["category"] == "spec" and e["code"] == "SPEC_CONFLICT"
    paths = {i["path"] for i in e["details"]["issues"]}
    assert "hole.bl" in paths  # located: which feature conflicts
    assert not (ws / "x.dxf").exists()


def test_geometry_outside_drawing_bounds(rt, blank):
    ok(rt.apply_operations(blank, [{"op": "add_rectangle", "corner": [10, 10], "width": 100, "height": 60, "tag": "in"},
                                   {"op": "add_circle", "center": [300, 50], "radius": 5, "tag": "out"}]))
    v = ok(rt.validate_drawing(blank, bounds=[[0, 0], [297, 210]]))["validation"]
    oob = [i for i in v["issues"] if i["code"] == "OUT_OF_BOUNDS"]
    assert len(oob) == 1 and oob[0]["details"]["tag"] == "out" and oob[0]["category"] == "geometry"
    assert oob[0]["details"]["extents"] == [[295.0, 45.0], [305.0, 55.0]]
    assert not v["passed"]


def test_duplicate_entities(rt, blank):
    r = ok(rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0]},
                                       {"op": "add_line", "start": [10, 0], "end": [0, 0]},
                                       {"op": "add_circle", "center": [5, 5], "radius": 2},
                                       {"op": "add_circle", "center": [5, 5], "radius": 2}]))
    issues = [i for i in r["validation"]["issues"] if i["code"] == "DUPLICATE_ENTITY"]
    assert len(issues) == 2 and all(len(i["entities"]) == 2 for i in issues)
    # strict mode refuses to save a batch that introduces duplicates
    before = ok(rt.read_drawing(blank))["entity_count"]
    s = rt.apply_operations(blank, [{"op": "add_point", "location": [1, 1]}, {"op": "add_point", "location": [1, 1]}],
                            strict=True)
    assert not s["ok"] and s["error"]["code"] == "VALIDATION_FAILED" and s["error"]["category"] == "validation"
    assert ok(rt.read_drawing(blank))["entity_count"] == before


def test_hole_position_violation(rt, ws, plate):
    reqs = [{"type": "hole", "center": [12, 10], "diameter": 8, "tolerance": 0.05}]
    v = ok(rt.validate_drawing(plate, requirements=reqs))["validation"]
    r = v["requirements"][0]
    assert r["status"] == "fail" and r["deviation"] == 2.0 and r["entities"]
    assert r["expected"]["center"] == [12, 10] and r["actual"]["center"] == [10.0, 10.0]


def test_requirement_fields_are_not_silently_ignored(rt, plate):
    """Found with a real agent (Codex) sending fields the validator did not know."""
    v = ok(rt.validate_drawing(plate, detail=True, requirements=[
        {"type": "outline", "width": 100, "height": 60, "layer": "OUTLINE", "corner": [0, 0], "closed": True},
        {"type": "dimension", "kind": "linear", "value": 60, "tag": "dim.width"},
        {"type": "dimension", "kind": "linear", "value": 60, "tag": "dim.height"}]))["validation"]
    r = v["requirements"]
    assert "closed" in r[0]["warnings"][0] and "corner" in r[0]["warnings"][0]
    assert r[1]["status"] == "fail" and r[1]["actual"] == 100.0  # tag pins the dimension: width is 100, not 60
    assert r[2]["status"] == "pass" and "warnings" not in r[2]


def test_invalid_and_unparsable_dxf(rt, ws):
    (ws / "garbage.dxf").write_text("this is not a dxf file\n", "utf-8")
    (ws / "empty.dxf").write_bytes(b"")
    (ws / "trunc.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n10\n", "utf-8")
    for name in ("garbage.dxf", "empty.dxf", "trunc.dxf"):
        r = rt.read_drawing(name)
        assert not r["ok"] and r["error"]["category"] == "file" and r["error"]["code"] == "DXF_PARSE_ERROR", r
        v = ok(rt.validate_drawing(name))["validation"]
        assert not v["readable"] and not v["passed"]
        assert v["issues"][0]["category"] == "file"
    r = rt.read_drawing("nope.dxf")
    assert r["error"]["code"] == "FILE_NOT_FOUND"


def test_missing_parameters(rt, blank):
    r = rt.draw_from_spec({"kind": "plate", "units": "mm", "width": 100, "holes": [{"pattern": "corners"}]}, "m.dxf")
    assert not r["ok"] and r["error"]["category"] == "spec"
    missing = {i["path"] for i in r["error"]["details"]["issues"] if i["code"] == "SPEC_MISSING_PARAM"}
    assert {"height", "holes[0].diameter", "holes[0].edge_offset"} <= missing
    e = rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0]}])["error"]
    assert (e["code"], e["category"], e["op_index"], e["partial_changes"]) == ("AMBIGUOUS_PARAMS", "input", 0, False)


def test_error_categories_are_distinguishable(rt, blank):
    """input vs geometry vs file vs policy vs spec errors carry different categories."""
    cats = {
        rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": "abc"}])["error"]["category"],
        rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [0, 0]}])["error"]["category"],
        rt.read_drawing("missing.dxf")["error"]["category"],
        rt.read_drawing("../outside.dxf")["error"]["category"],
        rt.draw_from_spec({"kind": "plate"}, "s.dxf")["error"]["category"],
    }
    assert cats == {"input", "geometry", "file", "policy", "spec"}


def test_failed_batch_leaves_file_unchanged_and_is_journaled(rt, ws, blank):
    ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 1, "tag": "c"}]))
    before = (ws / blank).read_bytes()
    r = rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [5, 0]},
                                    {"op": "move", "target": "tag:c", "delta": [1, 1]},
                                    {"op": "trim", "target": "tag:c", "edges": "$0", "pick": [1, 0]}])
    assert not r["ok"]
    assert r["error"]["op_index"] == 2 and r["error"]["partial_changes"] is False
    assert (ws / blank).read_bytes() == before
    hist = ok(rt.history(blank, detail=True))["records"]
    assert hist[-1]["ok"] is False and hist[-1]["error"]["op_index"] == 2 and hist[-1]["file_unchanged"]
