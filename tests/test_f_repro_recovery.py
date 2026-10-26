"""Test F: deterministic replays, traceable journal, checkpoint recovery, no duplicate growth."""
from __future__ import annotations

import json

from agentcad.model import entity_to_dict
from conftest import PLATE_SPEC, ok, reread

PLAN = [
    {"op": "create_layer", "name": "PART", "if_exists": "skip"},
    {"op": "add_rectangle", "corner": [0, 0], "width": 80, "height": 50, "corner_radius": 4, "layer": "PART",
     "tag": "body", "if_tag_exists": "skip"},
    {"op": "add_circle", "center": [40, 25], "diameter": 20, "layer": "PART", "tag": "bore", "if_tag_exists": "skip"},
    {"op": "add_linear_dim", "p1": [0, 0], "p2": [80, 0], "offset": -10, "tag": "d80", "if_tag_exists": "skip"},
]


def geometry(ws, name):
    return sorted(json.dumps({k: v for k, v in entity_to_dict(e).items() if k != "id"}, sort_keys=True)
                  for e in reread(ws, name).modelspace())


def test_same_plan_twice_gives_equivalent_geometry(rt, ws):
    for name in ("run1.dxf", "run2.dxf"):
        ok(rt.create_drawing(name))
        ok(rt.apply_operations(name, PLAN))
    assert geometry(ws, "run1.dxf") == geometry(ws, "run2.dxf")
    ok(rt.draw_from_spec(PLATE_SPEC, "s1.dxf"))
    ok(rt.draw_from_spec(PLATE_SPEC, "s2.dxf"))
    assert geometry(ws, "s1.dxf") == geometry(ws, "s2.dxf")
    # even the handles are identical: entity ids are deterministic
    assert [e.dxf.handle for e in reread(ws, "s1.dxf").modelspace()] == [e.dxf.handle for e in reread(ws, "s2.dxf").modelspace()]


def test_replaying_plan_does_not_duplicate(rt, ws):
    ok(rt.create_drawing("r.dxf"))
    ok(rt.apply_operations("r.dxf", PLAN))
    g = geometry(ws, "r.dxf")
    r = ok(rt.apply_operations("r.dxf", PLAN))
    assert r["changes"]["added"] == []
    assert geometry(ws, "r.dxf") == g
    # without the idempotency flag the duplicate tag is refused, not silently duplicated
    plain = [{k: v for k, v in o.items() if k != "if_tag_exists"} for o in PLAN]
    e = rt.apply_operations("r.dxf", plain)["error"]
    assert e["code"] == "TAG_EXISTS" and e["entities"]
    # drawing a spec onto an existing file is refused instead of stacking a second copy
    ok(rt.draw_from_spec(PLATE_SPEC, "p.dxf"))
    assert rt.draw_from_spec(PLATE_SPEC, "p.dxf")["error"]["code"] == "FILE_EXISTS"


def test_journal_traceability(rt, ws):
    ok(rt.create_drawing("j.dxf"))
    ok(rt.apply_operations("j.dxf", PLAN, label="base"))
    ok(rt.apply_operations("j.dxf", [{"op": "move", "target": "tag:bore", "delta": [5, 0]}], label="shift"))
    recs = ok(rt.history("j.dxf"))["records"]
    assert [r["tool"] for r in recs] == ["create_drawing", "apply_operations", "apply_operations"]
    assert recs[1]["operations"] == PLAN and recs[2]["label"] == "shift"
    for r in recs:
        assert {"seq", "ts", "versions", "sha256"} <= set(r)
        assert r["versions"]["ezdxf"]
    assert recs[2]["checkpoint_before"] == "cp-0002"
    d = ok(rt.get_diff("j.dxf", "cp-0002"))
    assert d["summary"]["modified"] == 1 and d["modified"][0]["tag"] == "bore"
    assert d["modified"][0]["changes"]["center"] == {"old": [40.0, 25.0], "new": [45.0, 25.0]}


def test_mid_batch_failure_then_rollback(rt, ws):
    ok(rt.create_drawing("f.dxf"))
    ok(rt.apply_operations("f.dxf", PLAN))
    good = (ws / "f.dxf").read_bytes()
    r = rt.apply_operations("f.dxf", [{"op": "move", "target": "tag:bore", "delta": [1, 0]},
                                      {"op": "delete", "target": "tag:does-not-exist"}])
    assert not r["ok"] and r["error"]["partial_changes"] is False
    assert (ws / "f.dxf").read_bytes() == good
    g_before = geometry(ws, "f.dxf")
    ok(rt.apply_operations("f.dxf", [{"op": "delete", "target": "tag:bore"}]))
    assert geometry(ws, "f.dxf") != g_before
    ok(rt.rollback("f.dxf"))  # back to the last checkpoint (before the delete)
    assert geometry(ws, "f.dxf") == g_before


def test_crash_recovery_restores_last_valid_checkpoint(rt, ws):
    ok(rt.create_drawing("c.dxf"))
    ok(rt.apply_operations("c.dxf", PLAN))
    ok(rt.apply_operations("c.dxf", [{"op": "add_point", "location": [1, 1], "tag": "last"}]))
    expected = geometry(ws, "c.dxf")
    # simulate a crash in the middle of a write: truncated file + pending marker
    from agentcad.store import DrawingStore
    store = DrawingStore(rt.policy, (ws / "c.dxf").resolve())
    head = store.head()
    head["pending"] = {"label": "simulated crash"}
    store._write_head(head)
    data = (ws / "c.dxf").read_bytes()
    (ws / "c.dxf").write_bytes(data[: len(data) // 2])
    assert not rt.read_drawing("c.dxf")["ok"]
    r = ok(rt.recover("c.dxf"))
    assert r["recovered"] and r["previous_status"]["readable"] is False
    assert r["restored_checkpoint"] == "committed"
    assert geometry(ws, "c.dxf") == expected  # nothing from the last committed batch is lost
    assert ok(rt.validate_drawing("c.dxf"))["validation"]["readable"]
    assert not ok(rt.recover("c.dxf"))["recovered"]  # nothing left to recover
    # the corrupt file was preserved for forensics
    assert list((store.dir / "failed").glob("*-corrupt.dxf"))
