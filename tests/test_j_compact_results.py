"""Test J: agent-facing results are compact by default and complete on request (validate_drawing, get_diff,
history). In the Claude Code trials validate_drawing alone was a third of all tool output."""
from __future__ import annotations

import json

from conftest import ok

HOLES = [{"op": "add_circle", "center": [10 + 20 * i, 10], "diameter": 8, "layer": "HOLES", "tag": f"h{i}"}
         for i in range(10)]


def size(x) -> int:
    return len(json.dumps(x))


def test_validate_is_compact_by_default(rt, plate):
    ok(rt.apply_operations(plate, [{**h, "center": [h["center"][0], 30], "tag": "x" + h["tag"]} for h in HOLES[:4]]))
    full = ok(rt.validate_drawing(plate, detail=True))["validation"]
    brief = ok(rt.validate_drawing(plate))["validation"]
    assert brief["passed"] == full["passed"] and brief["summary"] == full["summary"]
    assert size(brief) < size(full) / 3
    # only failures are spelled out (4 extra holes break the hole counts); passed requirements are listed by id
    failed = [r["id"] for r in full["requirements"] if r["status"] != "pass"]
    assert [r["id"] for r in brief["requirements"]] == failed and "hole_count" in failed
    assert brief["requirements"][0]["status"] == "fail" and "expected" in brief["requirements"][0]
    assert brief["requirements_passed"] == [r["id"] for r in full["requirements"] if r["status"] == "pass"]
    rec = brief["recognized"]
    assert rec["circles"] == {"count": 8, "by_diameter": {"8": 8}}
    assert rec["dimensions"]["count"] == len(full["recognized"]["dimensions"])
    assert "detail_hint" in brief


def test_failed_requirements_and_warnings_stay_complete(rt, plate):
    v = ok(rt.validate_drawing(plate, requirements=[
        {"type": "hole", "center": [12, 10], "diameter": 8, "tolerance": 0.05},
        {"type": "outline", "width": 100, "height": 60, "layer": "OUTLINE", "closed": True}]))["validation"]
    bad, good = v["requirements"]
    assert bad["status"] == "fail" and bad["expected"]["center"] == [12, 10] and bad["deviation"] == 2.0
    assert good["status"] == "pass" and "closed" in good["warnings"][0] and "actual" not in good


def test_apply_and_strict_failure_use_the_compact_report(rt, plate):
    r = ok(rt.apply_operations(plate, [{"op": "add_line", "start": [0, 0], "end": [5, 5]}],
                               requirements=[{"type": "hole", "center": [10, 10], "diameter": 8}]))
    assert r["validation"]["requirements"] == [] and r["validation"]["requirements_passed"] == ["R1"]
    e = rt.apply_operations(plate, [{"op": "add_line", "start": [0, 0], "end": [5, 5]}], strict=True,
                            requirements=[{"type": "hole", "center": [50, 50], "diameter": 8}])["error"]
    v = e["details"]["validation"]
    assert e["code"] == "VALIDATION_FAILED" and v["requirements"][0]["status"] == "fail"
    assert "by_diameter" in v["recognized"]["circles"]


def test_diff_lists_added_entities_briefly(rt, blank):
    ok(rt.apply_operations(blank, HOLES[:2]))
    ok(rt.apply_operations(blank, [{"op": "add_spline", "fit_points": [[0, 0], [5, 9], [10, 0], [20, 4]], "tag": "s"},
                                   {"op": "modify", "target": "tag:h0", "set": {"radius": 6}}]))
    brief, full = ok(rt.get_diff(blank)), ok(rt.get_diff(blank, detail=True))
    assert brief["summary"] == full["summary"] == {"added": 1, "deleted": 0, "modified": 1, "unchanged": 1}
    assert brief["added"] == [{"id": full["added"][0]["id"], "type": "SPLINE", "layer": "0", "tag": "s"}]
    assert "control_points" in full["added"][0]
    assert brief["modified"][0]["changes"]["radius"] == {"old": 4.0, "new": 6.0}  # changed fields always shown


def test_history_lines_and_full_records_on_request(rt, blank):
    ok(rt.apply_operations(blank, HOLES, label="holes"))
    ok(rt.apply_operations(blank, [{"op": "modify", "target": "tag:h3", "set": {"radius": 5}}], label="bigger"))
    rt.apply_operations(blank, [{"op": "move", "target": "tag:nope", "delta": [1, 0]}])
    lines = ok(rt.history(blank))["records"]
    assert [x["tool"] for x in lines] == ["create_drawing", "apply_operations", "apply_operations", "apply_operations"]
    assert lines[1]["ops"] == ["add_circle x10"] and lines[1]["changes"] == {"added": 10, "modified": 0, "deleted": 0}
    assert lines[2]["label"] == "bigger" and lines[2]["checkpoint_before"]
    assert lines[3]["ok"] is False and lines[3]["error"]["code"] == "ENTITY_NOT_FOUND"
    assert all("operations" not in x and "versions" not in x for x in lines)
    full = ok(rt.history(blank, seq=[lines[2]["seq"]]))["records"]
    assert len(full) == 1 and full[0]["operations"][0]["set"] == {"radius": 5}
    assert size(lines) < size(ok(rt.history(blank, detail=True))["records"]) / 2
