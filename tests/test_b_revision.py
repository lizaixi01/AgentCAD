"""Test B: widen the plate to 120 mm, keep hole centers 10 mm from adjacent edges."""
from __future__ import annotations

import pytest

from agentcad.model import entity_to_dict, get_tag
from conftest import ok, reread

A = pytest.approx


def snapshot(ws, name):
    return {e.dxf.handle: entity_to_dict(e) for e in reread(ws, name).modelspace()}


def test_revise_width_keeps_edge_distance(rt, ws, plate):
    # a user-added, untagged note must survive the revision untouched
    note = ok(rt.apply_operations(plate, [{"op": "add_text", "text": "DEBURR ALL EDGES", "insert": [0, -50]}]))
    note_id = note["changes"]["added"][0]
    before = snapshot(ws, plate)

    r = ok(rt.revise_drawing(plate, {"width": 120}))
    after = snapshot(ws, plate)

    # 1. the existing drawing was modified (same handles), not regenerated
    assert set(after) == set(before)
    assert after[note_id] == before[note_id]

    # 2. only affected objects changed
    changed_tags = {after[h].get("tag") for h in after if after[h] != before[h]}
    assert changed_tags == {"outline", "hole.br", "hole.tr", "cl.hole.br.h", "cl.hole.br.v", "cl.hole.tr.h",
                            "cl.hole.tr.v", "dim.width", "dim.holes0.pitch_x", "dim.holes0.pitch_y"}
    for t in ("hole.bl", "hole.tl", "dim.height", "dim.holes0.dia", "dim.holes0.x", "dim.holes0.y", "notes"):
        h = next(k for k, v in before.items() if v.get("tag") == t)
        assert after[h] == before[h], t

    # 3. hole positions follow the constraint (10 mm from the adjacent edges)
    doc = reread(ws, plate)
    holes = sorted((round(c.dxf.center.x, 9), round(c.dxf.center.y, 9)) for c in doc.modelspace().query("CIRCLE"))
    assert holes == [(10, 10), (10, 50), (110, 10), (110, 50)]

    # 4. diff is queryable
    d = ok(rt.get_diff(plate))
    assert d["summary"] == {"added": 0, "deleted": 0, "modified": 10, "unchanged": len(before) - 10}
    width_dim = next(m for m in d["modified"] if m["tag"] == "dim.width")
    assert width_dim["changes"]["measurement"] == {"old": 100.0, "new": 120.0}

    # 5. everything passes independent validation (requirements re-derived from the new spec)
    v = ok(rt.validate_drawing(plate, detail=True))["validation"]
    assert v["passed"], v
    req = {x["id"]: x for x in v["requirements"]}
    assert req["outline"]["actual"] == {"width": 120.0, "height": 60.0}
    assert req["hole.br"]["actual"]["center"] == [110.0, 10.0]
    assert req["dim.width"]["actual"] == 120.0


def test_revision_is_idempotent_and_reversible(rt, ws, plate):
    ok(rt.revise_drawing(plate, {"width": 120}))
    snap = snapshot(ws, plate)
    r = ok(rt.revise_drawing(plate, {"width": 120}))  # same request again
    assert r["changes"] == {"added": [], "modified": [], "deleted": []}
    assert snapshot(ws, plate) == snap
    ok(rt.rollback(plate, "cp-0001"))  # back to the original 100 mm
    v = ok(rt.validate_drawing(plate, detail=True))["validation"]
    assert {x["id"]: x for x in v["requirements"]}["outline"]["actual"]["width"] == 100.0


def test_revision_rejects_contradiction_without_touching_file(rt, ws, plate):
    before = (ws / plate).read_bytes()
    r = rt.revise_drawing(plate, {"width": 15})  # holes would overlap the edge / each other
    assert not r["ok"] and r["error"]["category"] == "spec"
    assert (ws / plate).read_bytes() == before


def test_low_level_stretch_route_on_foreign_drawing(rt, ws, blank):
    """Drawings not made from a spec: the agent revises with STRETCH + validate."""
    ok(rt.apply_operations(blank, [
        {"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "layer": "OUTLINE"},
        *[{"op": "add_circle", "center": c, "diameter": 8, "layer": "HOLES"} for c in ([10, 10], [90, 10], [90, 50], [10, 50])],
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [100, 0], "offset": -15, "layer": "DIM"}]))
    assert not rt.revise_drawing(blank, {"width": 120})["ok"]
    ok(rt.apply_operations(blank, [{"op": "stretch", "window": [[60, -100], [200, 100]], "delta": [20, 0]}]))
    reqs = [{"type": "outline", "width": 120, "height": 60, "layer": "OUTLINE"},
            *[{"type": "hole", "center": c, "diameter": 8} for c in ([10, 10], [110, 10], [110, 50], [10, 50])],
            {"type": "dimension", "value": 120}]
    v = ok(rt.validate_drawing(blank, requirements=reqs))["validation"]
    assert v["passed"], v
