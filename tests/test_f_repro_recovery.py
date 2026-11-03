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
    recs = ok(rt.history("j.dxf", detail=True))["records"]
    assert [r["tool"] for r in recs] == ["create_drawing", "apply_operations", "apply_operations"]
    assert recs[1]["operations"] == PLAN and recs[2]["label"] == "shift"
    for r in recs:
        assert {"seq", "ts", "versions", "sha256"} <= set(r)
        assert r["versions"]["ezdxf"]
    assert recs[2]["checkpoint_before"] == "cp-0002"
    d = ok(rt.get_diff("j.dxf", "cp-0002"))
    assert d["summary"]["modified"] == 1 and d["modified"][0]["tag"] == "bore"
    assert d["modified"][0]["changes"]["center"] == {"old": [40.0, 25.0], "new": [45.0, 25.0]}


def test_limited_history_reads_long_utf8_records_from_the_tail(rt, monkeypatch):
    from agentcad import store
    _, state = rt._drawing("tail.dxf", must_exist=False)
    with state.lock():
        for _ in range(8):
            state.journal({"ok": False})
        # The record is larger than a read block, and head may lag the journal.
        with monkeypatch.context() as patch:
            def busy(_):
                raise PermissionError
            patch.setattr(state, "_write_head", busy)
            assert state.journal({"ok": True, "label": "图\u2028纸" * 12000}) == 9
        assert state.journal({"ok": True}) == 10
    loads = store.json.loads
    parsed = []

    def count_loads(value):
        parsed.append(value)
        return loads(value)

    monkeypatch.setattr(store.json, "loads", count_loads)
    recent = state.read_journal(2)
    assert [r["seq"] for r in recent] == [9, 10]
    assert recent[0]["label"] == "图\u2028纸" * 12000
    assert len(parsed) == 2


def test_colliding_legacy_names_have_separate_checkpoints(rt):
    first, second = "parts/panel.dxf", "parts__panel.dxf"
    ok(rt.create_drawing(first, units="cm"))
    checkpoint = ok(rt.apply_operations(first, PLAN))["checkpoint_before"]
    ok(rt.create_drawing(second, units="mm"))
    assert rt.rollback(second, checkpoint)["error"]["code"] == "NO_CHECKPOINT"
    assert ok(rt.read_drawing(second))["units"] == "mm"
    assert ok(rt.read_drawing(first))["units"] == "cm"


def test_rollback_rejects_a_checkpoint_with_other_bytes(rt, ws):
    name = "checked.dxf"
    ok(rt.create_drawing(name))
    checkpoint = ok(rt.apply_operations(name, PLAN))["checkpoint_before"]
    _, state = rt._drawing(name)
    current = (ws / name).read_bytes()
    state.checkpoint_path(checkpoint).write_bytes(current)
    assert rt.rollback(name, checkpoint)["error"]["code"] == "CHECKPOINT_CHANGED"
    assert (ws / name).read_bytes() == current


def test_recover_skips_checkpoint_whose_hash_cannot_be_read(rt, ws, monkeypatch):
    from agentcad import service
    name = "busy.dxf"
    ok(rt.create_drawing(name))
    older = ok(rt.apply_operations(name, PLAN))["checkpoint_before"]
    newer = ok(rt.apply_operations(name, [{"op": "add_point", "location": [1, 1]}]))["checkpoint_before"]
    _, state = rt._drawing(name)
    state.committed_path.unlink()
    (ws / name).write_bytes(b"")
    sha256_file = service.sha256_file

    def hash_if_readable(path):
        if path.name == f"{newer}.dxf":
            raise PermissionError("another process has the checkpoint open")
        return sha256_file(path)

    monkeypatch.setattr(service, "sha256_file", hash_if_readable)
    assert ok(rt.recover(name))["restored_checkpoint"] == older
    assert geometry(ws, name) == []


def test_clean_legacy_history_migrates_to_its_owner(rt, ws):
    first, second = "parts/panel.dxf", "parts__panel.dxf"
    ok(rt.create_drawing(first))
    checkpoint = ok(rt.apply_operations(first, PLAN))["checkpoint_before"]
    _, state = rt._drawing(first)
    legacy = ws / ".agentcad" / "drawings" / second
    legacy.parent.mkdir(parents=True)
    state.dir.rename(legacy)
    # Simulate a colliding writer dying after copying its file but before
    # adding that checkpoint to head.json.
    foreign = legacy / "checkpoints" / "cp-0002.dxf"
    foreign.write_bytes((ws / first).read_bytes())
    assert len(ok(rt.history(first))["records"]) == 2
    ok(rt.create_drawing(second))
    assert len(ok(rt.history(second))["records"]) == 1
    assert rt.rollback(first, "cp-0002")["error"]["code"] == "CHECKPOINT_NOT_FOUND"
    assert not (state.cp_dir / foreign.name).exists() and foreign.is_file()
    ok(rt.rollback(first, checkpoint))
    assert geometry(ws, first) == []
    assert len(ok(rt.history(first))["records"]) == 3
    assert legacy.is_dir()


def test_clean_legacy_history_matches_case_insensitive_posix_alias(rt, ws, monkeypatch):
    import os
    from pathlib import Path
    from agentcad import store
    name = "Parts/Panel.dxf"
    ok(rt.create_drawing(name))
    ok(rt.apply_operations(name, PLAN))
    _, state = rt._drawing(name)
    legacy = ws / ".agentcad" / "drawings" / "Parts__Panel.dxf"
    legacy.parent.mkdir(parents=True)
    state.dir.rename(legacy)
    journal = legacy / "journal.jsonl"
    journal.write_text(journal.read_text("utf-8").replace(name, name.lower(), 1), "utf-8")
    samefile = Path.samefile
    monkeypatch.setattr(store.os.path, "normcase", lambda path: path)
    monkeypatch.setattr(Path, "samefile", lambda path, other: (
        path.exists() and str(path).casefold() == str(other).casefold()) or samefile(path, other))
    assert len(ok(rt.history(name))["records"]) == 2
    (ws / name).unlink()
    stat = Path.stat

    def separate_volume(path, *args, **kwargs):
        result = stat(path, *args, **kwargs)
        if path == (ws / name).parent:
            fields = list(result)
            fields[2] = result.st_dev + 1
            return os.stat_result(fields)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", separate_volume)
        assert ok(rt.history(name))["records"] == []
    assert ok(rt.recover(name))["restored_checkpoint"] == "committed"
    assert len(ok(rt.history(name))["records"]) == 3


def test_export_keeps_its_journal_record_during_legacy_migration(rt, ws, monkeypatch):
    from pathlib import Path
    from agentcad.service import Runtime
    name = "parts/panel.dxf"
    ok(rt.create_drawing(name))
    _, state = rt._drawing(name)
    legacy = ws / ".agentcad" / "drawings" / "parts__panel.dxf"
    legacy.parent.mkdir(parents=True)
    state.dir.rename(legacy)
    write_text = Path.write_text

    def during_export(path, *args, **kwargs):
        if path == ws / "result.json":
            concurrent = Runtime(rt.policy).apply_operations(name, PLAN)
            assert concurrent["error"]["code"] == "DRAWING_LOCKED"
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", during_export)
    ok(rt.export_drawing(name, "result.json", "json"))
    assert [r["tool"] for r in ok(rt.history(name))["records"]] == ["create_drawing", "export_drawing"]


def test_mixed_legacy_history_is_preserved_but_ineligible_for_rollback(rt, ws):
    first, second = "parts/panel.dxf", "parts__panel.dxf"
    ok(rt.create_drawing(first))
    checkpoint = ok(rt.apply_operations(first, PLAN))["checkpoint_before"]
    _, state = rt._drawing(first)
    legacy = ws / ".agentcad" / "drawings" / second
    legacy.parent.mkdir(parents=True)
    state.dir.rename(legacy)
    with (legacy / "journal.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"seq": 3, "drawing": second, "ok": False}) + "\n")
    ok(rt.create_drawing(second))
    assert rt.rollback(first, checkpoint)["error"]["code"] == "NO_CHECKPOINT"
    assert (legacy / "checkpoints" / f"{checkpoint}.dxf").is_file()


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
