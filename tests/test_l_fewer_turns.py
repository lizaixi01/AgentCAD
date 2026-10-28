"""Test L: fewer agent turns. apply_operations creates a missing drawing and returns the same independent
validation as validate_drawing; apply_batch draws a set of drawings in one call. In the Claude Code trials every
tool call was its own turn, and every turn re-reads the whole context."""
from __future__ import annotations

import json

from conftest import by_tag, ok, reread


def flange(od: float, holes: int) -> list[dict]:
    return [{"op": "add_circle", "center": [0, 0], "diameter": od, "layer": "OUTLINE", "tag": "od"},
            {"op": "add_circle", "center": [od / 2 - 10, 0], "diameter": 8, "layer": "HOLES", "tag": "h0"},
            {"op": "array_polar", "target": "tag:h0", "center": [0, 0], "count": holes}]


def test_apply_creates_a_missing_drawing(rt, ws):
    r = ok(rt.apply_operations("new.dxf", flange(100, 4), create={"units": "mm", "template": "blank"}))
    assert r["created_drawing"]["units"] == "mm"
    doc = reread(ws, "new.dxf")
    assert doc.header["$INSUNITS"] == 4 and by_tag(doc, "od").dxf.radius == 50
    assert [x["tool"] for x in ok(rt.history("new.dxf"))["records"]] == ["create_drawing", "apply_operations"]
    # an existing drawing is used as it is: create only fills in a missing one
    r = ok(rt.apply_operations("new.dxf", [{"op": "add_point", "location": [0, 0]}], create={"units": "in"}))
    assert "created_drawing" not in r and reread(ws, "new.dxf").header["$INSUNITS"] == 4


def test_apply_create_errors(rt):
    e = rt.apply_operations("x.dxf", flange(100, 4), create={"unit": "mm"})["error"]
    assert e["code"] == "UNKNOWN_PARAM" and "units" in e["hint"]
    e = rt.apply_operations("x.dxf", flange(100, 4), dry_run=True, create={"units": "mm"})["error"]
    assert e["code"] == "DRY_RUN_NEEDS_DRAWING"


def test_apply_validation_matches_validate_drawing(rt, plate):
    reqs = [{"type": "hole_count", "count": 4, "layer": "HOLES"}, {"type": "hole", "center": [50, 30], "diameter": 9}]
    r = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}], requirements=reqs,
                               bounds=[[0, 0], [10, 10]]))
    v = ok(rt.validate_drawing(plate, requirements=reqs, bounds=[[0, 0], [10, 10]]))["validation"]
    a = r["validation"]
    assert a["passed"] is False and a["summary"] == v["summary"]
    assert a["requirements"] == v["requirements"] and a["requirements_passed"] == v["requirements_passed"]
    assert a["recognized"] == v["recognized"] and a["coverage"] == v["coverage"]
    assert {i["code"] for i in a["issues"]} == {i["code"] for i in v["issues"]} >= {"OUT_OF_BOUNDS"}


def test_apply_validates_a_sheet(rt, ws, plate):
    ok(rt.apply_operations(plate, [{"op": "create_layout", "name": "A4", "paper": "A4"},
                                   {"op": "add_viewport", "layout": "A4", "center": [148, 105], "scale": 1}]))
    r = ok(rt.apply_operations(plate, [{"op": "add_text", "text": "NOTE", "insert": [20, 20], "height": 3.5,
                                        "layout": "A4"}], layout="A4",
                               requirements=[{"type": "text", "contains": "NOTE"}]))
    assert r["validation"]["coverage"]["checked_layout"] == "A4"
    assert r["validation"]["requirements_passed"]


def test_apply_batch_draws_a_family_in_one_call(rt, ws):
    table = [("FL-1", 100, 4), ("FL-2", 120, 6), ("FL-3", 140, 8)]
    jobs = [{"path": f"{n}.dxf", "create": {"units": "mm"}, "operations": flange(od, k),
             "requirements": [{"type": "hole_count", "count": k, "diameter": 8}]} for n, od, k in table]
    r = ok(rt.apply_batch(jobs))
    assert (r["succeeded"], r["failed"], r["all_passed"]) == (3, 0, True)
    for (n, od, k), job in zip(table, r["jobs"]):
        assert job["created"] and job["passed"] and job["changes"]["added"] == k + 1
        assert by_tag(reread(ws, f"{n}.dxf"), "od").dxf.radius == od / 2
    assert len(json.dumps(r)) < 6000  # three validations, still compact


def test_apply_batch_isolates_a_failing_job(rt, ws):
    jobs = [{"path": "a.dxf", "create": {"units": "mm"}, "operations": flange(100, 4)},
            {"path": "b.dxf", "create": {"units": "mm"}, "operations": [{"op": "add_circle", "center": [0, 0]}]},
            {"path": "c.dxf", "create": {"units": "mm"}, "operations": flange(80, 3)}]
    r = ok(rt.apply_batch(jobs))
    assert [j["ok"] for j in r["jobs"]] == [True, False, True] and r["failed"] == 1 and not r["all_passed"]
    assert r["jobs"][1]["error"]["code"] == "AMBIGUOUS_PARAMS"
    # the failed job created its drawing but left it empty (the batch of operations is atomic per drawing)
    assert len(reread(ws, "b.dxf").modelspace()) == 0
    r = ok(rt.apply_batch([{**j, "path": "s_" + j["path"]} for j in jobs], stop_on_error=True))
    assert [j.get("skipped", False) for j in r["jobs"]] == [False, False, True] and r["skipped"] == 1


def test_apply_batch_rejects_bad_jobs_before_running_any(rt, ws):
    good = {"path": "g.dxf", "create": {"units": "mm"}, "operations": flange(100, 4)}
    for jobs, code in (([], "INVALID_LIST"), ([good, {"path": "h.dxf"}], "INVALID_JOB"),
                       ([good, {**good, "colour": 3}], "UNKNOWN_PARAM"), ([good, good], "DUPLICATE_PATH"),
                       ([good, {**good, "path": "./G.dxf"}], "DUPLICATE_PATH"),  # same file, other spelling
                       ([good, {**good, "path": "h.dxf", "create": {"unit": "mm"}}], "UNKNOWN_PARAM"),
                       ([good, {**good, "path": "../outside.dxf"}], "PATH_OUTSIDE_WORKSPACE"),
                       ([good] * 201, "BUDGET_EXCEEDED")):
        assert rt.apply_batch(jobs)["error"]["code"] == code, jobs[-1]
    assert not (ws / "g.dxf").exists()


def test_apply_batch_read_only_and_strict(ws):
    from agentcad.policy import Policy
    from agentcad.service import Runtime
    jobs = [{"path": "a.dxf", "create": {"units": "mm"}, "operations": flange(100, 4)}]
    assert Runtime(Policy(root=ws, read_only=True)).apply_batch(jobs)["error"]["code"] == "READ_ONLY"
    rt = Runtime(Policy(root=ws))
    r = ok(rt.apply_batch([{**jobs[0], "strict": True, "requirements": [{"type": "hole_count", "count": 9}]}]))
    assert r["jobs"][0]["error"]["code"] == "VALIDATION_FAILED"
    assert len(reread(ws, "a.dxf").modelspace()) == 0  # strict: nothing saved


def test_mcp_registers_apply_batch_and_says_validation_is_included(ws):
    import anyio
    from agentcad.mcp_server import INSTRUCTIONS, build_server
    from agentcad.policy import Policy
    assert "apply_batch" in INSTRUCTIONS and "validate_drawing only for detail=true" in INSTRUCTIONS
    tools = {t.name: t for t in anyio.run(build_server(Policy(root=ws)).list_tools)}
    assert "jobs" in tools["apply_batch"].inputSchema["required"]
    assert {"create", "bounds", "layout"} <= set(tools["apply_operations"].inputSchema["properties"])
