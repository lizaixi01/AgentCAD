"""Commits when another process holds one of the store's files open past the retry timeout (Windows: os.replace
onto an open file fails). The drawing is either untouched (FILE_BUSY, retryable) or the change is saved and recorded
or reported as applied, never a plain failure that a retry would apply twice."""
from __future__ import annotations

import json
import os

import ezdxf
import pytest

from agentcad import store as store_mod
from agentcad.store import DrawingStore, sha256_file
from conftest import ok

pytestmark = pytest.mark.skipif(os.name != "nt", reason="POSIX rename never fails on an open target")

LINE = [{"op": "add_line", "start": [0, 0], "end": [50, 0], "tag": "l"}]


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch):
    monkeypatch.setattr(store_mod, "REPLACE_TIMEOUT", 0.1)


def st(rt, path) -> DrawingStore:
    return rt._drawing(path)[1]


def lines(ws, path) -> int:
    return len(ezdxf.readfile(ws / path).modelspace().query("LINE"))


def journal(s: DrawingStore) -> list[dict]:
    return s.read_journal()


def err(r) -> dict:
    assert not r["ok"], r
    return r["error"]


def test_busy_committed_copy_still_commits_and_records(rt, ws, blank):
    s = st(rt, blank)
    with open(s.committed_path, "rb"):
        r = ok(rt.apply_operations(blank, LINE))
    assert r["warnings"] and "committed" in r["warnings"][0]
    assert lines(ws, blank) == 1
    head = s.head()
    assert head["pending"] is None and head["sha256"] == sha256_file(ws / blank)
    assert journal(s)[-1]["tool"] == "apply_operations" and journal(s)[-1]["ok"]
    # the stale copy is never used: recover finds nothing to do
    assert ok(rt.recover(blank))["recovered"] is False


def test_busy_drawing_changes_nothing_and_is_retryable(rt, ws, blank):
    s = st(rt, blank)
    before = sha256_file(ws / blank)
    cps = s.list_checkpoints()
    with open(ws / blank, "rb"):
        e = err(rt.apply_operations(blank, LINE))
    assert e["code"] == "FILE_BUSY" and e["retryable"] and not e["partial_changes"]
    assert sha256_file(ws / blank) == before and s.list_checkpoints() == cps  # no checkpoint left behind
    assert s.head()["pending"] is None
    assert not (ws / (blank + ".agentcad-tmp")).exists()
    ok(rt.apply_operations(blank, LINE))  # the retry applies it once
    assert lines(ws, blank) == 1


def test_busy_head_before_the_replace_changes_nothing(rt, ws, blank):
    s = st(rt, blank)
    before = sha256_file(ws / blank)
    with open(s.head_path, "rb"):
        e = err(rt.apply_operations(blank, LINE))
    assert e["code"] == "FILE_BUSY" and e["retryable"] and not e["partial_changes"]
    assert sha256_file(ws / blank) == before and s.head()["pending"] is None
    ok(rt.apply_operations(blank, LINE))
    assert lines(ws, blank) == 1


def test_busy_head_after_the_replace_reports_applied_and_recover_records_it(rt, ws, blank, monkeypatch):
    """The reviewer's case: the drawing is replaced, then head.json stays busy. The call must say the change is in
    the file, and recover must record it instead of letting the next commit absorb it."""
    s = st(rt, blank)
    real = store_mod.replace_file
    held = []

    def replace(src, dst, timeout=None):
        real(src, dst, timeout)
        if dst == s.path and not held:  # the drawing is in place: now another process opens head.json
            held.append(open(s.head_path, "rb"))

    monkeypatch.setattr(store_mod, "replace_file", replace)
    try:
        e = err(rt.apply_operations(blank, LINE))
    finally:
        for f in held:
            f.close()
    assert e["code"] == "FILE_BUSY" and e["partial_changes"] and not e["retryable"]
    assert e["details"]["state"] == "applied_not_recorded" and "recover" in e["hint"]
    assert lines(ws, blank) == 1  # the change is in the file
    status = ok(rt.recover(blank))
    assert status["recovered"] and status["pending_commit"] == "completed"
    assert lines(ws, blank) == 1  # recorded, not rolled back
    head = s.head()
    assert head["pending"] is None and head["sha256"] == sha256_file(ws / blank) == e["details"]["sha256"]
    assert sha256_file(s.committed_path) == head["sha256"]
    rec = journal(s)[-1]
    assert rec["tool"] == "recover" and rec["completed_commit"] == "apply_operations"
    # the timeline sees it as a commit: the viewer maps it to its version
    assert rec["sha256"] == head["sha256"] and rec["checkpoint_before"] == e["details"]["checkpoint_before"]
    ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    assert lines(ws, blank) == 1


def test_next_commit_records_an_unrecorded_change_first(rt, ws, blank, monkeypatch):
    """An agent that commits again without calling recover: the earlier change is journaled before the new one."""
    s = st(rt, blank)
    real = store_mod.replace_file
    held = []

    def replace(src, dst, timeout=None):
        real(src, dst, timeout)
        if dst == s.path and not held:
            held.append(open(s.head_path, "rb"))

    monkeypatch.setattr(store_mod, "replace_file", replace)
    try:
        e = err(rt.apply_operations(blank, LINE))
    finally:
        for f in held:
            f.close()
    monkeypatch.undo()
    r = ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    recs = journal(s)
    assert [x["tool"] for x in recs[-2:]] == ["recover", "apply_operations"]
    assert recs[-2]["completed_commit"] == "apply_operations" and recs[-2]["sha256"] == e["details"]["sha256"]
    assert r["checkpoint_before"] and s.head()["pending"] is None


def test_recover_clears_a_marker_whose_commit_never_happened(rt, ws, blank):
    s = st(rt, blank)
    head = s.head()
    head["pending"] = {"label": "x", "checkpoint": None, "ts": "t", "sha256": "0" * 64}
    s._write_head(head)
    before = sha256_file(ws / blank)
    r = ok(rt.recover(blank))
    assert r["pending_commit"] == "discarded" and sha256_file(ws / blank) == before
    assert s.head()["pending"] is None


def test_busy_head_while_journaling_keeps_the_commit_and_seq(rt, ws, blank, monkeypatch):
    s = st(rt, blank)
    real = DrawingStore.commit_bytes
    held = []

    def commit_bytes(self, *a, **kw):
        out = real(self, *a, **kw)
        held.append(open(self.head_path, "rb"))  # busy from the commit's end until after journaling
        return out

    monkeypatch.setattr(DrawingStore, "commit_bytes", commit_bytes)
    try:
        r = ok(rt.apply_operations(blank, LINE))
    finally:
        for f in held:
            f.close()
    monkeypatch.undo()
    assert journal(s)[-1]["seq"] == r["journal_seq"]
    r2 = ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    seqs = [x["seq"] for x in journal(s)]
    assert r2["journal_seq"] == r["journal_seq"] + 1 and len(seqs) == len(set(seqs))
    assert json.loads(s.head_path.read_text("utf-8"))["seq"] == r2["journal_seq"]


# --- rollback goes through the same transaction ----------------------------------------------------------------

def test_rollback_with_a_busy_drawing_changes_nothing_and_is_retryable(rt, ws, blank):
    ok(rt.apply_operations(blank, LINE))
    before = sha256_file(ws / blank)
    cps = st(rt, blank).list_checkpoints()
    with open(ws / blank, "rb"):
        e = err(rt.rollback(blank))
    assert e["code"] == "FILE_BUSY" and e["retryable"] and not e["partial_changes"]
    assert sha256_file(ws / blank) == before and st(rt, blank).head()["pending"] is None
    # the failed attempt took no checkpoint, so the retry restores the same one (not a copy of the current file)
    assert st(rt, blank).list_checkpoints() == cps
    ok(rt.rollback(blank))
    assert lines(ws, blank) == 0


def test_rollback_with_a_busy_committed_copy_succeeds_with_a_warning(rt, ws, blank):
    ok(rt.apply_operations(blank, LINE))
    s = st(rt, blank)
    with open(s.committed_path, "rb"):
        r = ok(rt.rollback(blank))
    assert r["warnings"] and lines(ws, blank) == 0
    assert s.head()["pending"] is None and s.head()["sha256"] == sha256_file(ws / blank)


def test_rollback_with_head_busy_after_the_replace_is_settled_by_recover(rt, ws, blank, monkeypatch):
    ok(rt.apply_operations(blank, LINE))
    s = st(rt, blank)
    real = store_mod.replace_file
    held = []

    def replace(src, dst, timeout=None):
        real(src, dst, timeout)
        if dst == s.path and not held:
            held.append(open(s.head_path, "rb"))

    monkeypatch.setattr(store_mod, "replace_file", replace)
    try:
        e = err(rt.rollback(blank))
    finally:
        for f in held:
            f.close()
    monkeypatch.undo()
    assert e["code"] == "FILE_BUSY" and e["partial_changes"] and not e["retryable"]
    assert lines(ws, blank) == 0  # the rollback is in the file
    r = ok(rt.recover(blank))
    assert r["pending_commit"] == "completed" and r["label"].startswith("rollback to cp-")
    head = s.head()
    assert head["pending"] is None and head["sha256"] == sha256_file(ws / blank) == sha256_file(s.committed_path)
    assert journal(s)[-1]["completed_commit"].startswith("rollback to")


# --- review of 80b7b61: B1, B2, N1, N2 ------------------------------------------------------------------------

def hold_head_after(monkeypatch, s: DrawingStore, method: str) -> list:
    """After ``DrawingStore.<method>`` returns, another process opens head.json (a real handle); close it later."""
    real = getattr(DrawingStore, method)
    held = []

    def wrapped(self, *a, **kw):
        out = real(self, *a, **kw)
        if self.head_path == s.head_path and not held:
            held.append(open(self.head_path, "rb"))
        return out

    monkeypatch.setattr(DrawingStore, method, wrapped)
    return held


def applied_not_recorded(rt, s: DrawingStore, blank, monkeypatch) -> dict:
    """A commit whose change reached the drawing but whose head update stayed busy."""
    real = store_mod.replace_file
    held = []

    def replace(src, dst, timeout=None):
        real(src, dst, timeout)
        if dst == s.path and not held:
            held.append(open(s.head_path, "rb"))

    monkeypatch.setattr(store_mod, "replace_file", replace)
    try:
        e = err(rt.apply_operations(blank, LINE))
    finally:
        for f in held:
            f.close()
        monkeypatch.setattr(store_mod, "replace_file", real)
    assert e["details"]["state"] == "applied_not_recorded"
    return e


def checkpoints_on_disk_match_head(s: DrawingStore) -> None:
    listed = [c["id"] for c in s.list_checkpoints()]
    files = sorted(p.stem for p in s.cp_dir.glob("cp-*"))
    assert sorted(listed) == files, (listed, files)


@pytest.mark.parametrize("call", ["commit", "rollback"])
def test_b1_head_busy_after_the_checkpoint_keeps_record_and_file_together(rt, ws, blank, monkeypatch, call):
    """B1: head.json stays busy after the checkpoint was recorded. The abandoned checkpoint stays listed and on
    disk (never listed without its file), and a literal agent's retry does what it asked."""
    ok(rt.apply_operations(blank, LINE))
    s = st(rt, blank)
    before = sha256_file(ws / blank)
    held = hold_head_after(monkeypatch, s, "checkpoint")
    try:
        e = err(rt.rollback(blank) if call == "rollback" else
                rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    finally:
        for f in held:
            f.close()
    monkeypatch.undo()
    assert e["code"] == "FILE_BUSY" and e["retryable"] and not e["partial_changes"]
    assert sha256_file(ws / blank) == before
    checkpoints_on_disk_match_head(s)
    if call == "rollback":
        # the leftover checkpoint is a copy of the unchanged file: the default rollback skips it and undoes the line
        ok(rt.rollback(blank))
        assert lines(ws, blank) == 0
    else:
        ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    checkpoints_on_disk_match_head(s)


def test_b2_a_busy_settle_leaves_the_earlier_marker_for_the_retry(rt, ws, blank, monkeypatch):
    """B2: the next commit cannot settle an applied_not_recorded commit because head.json is busy; the reader
    leaves right after. The earlier marker must survive, and the retry records it before its own change."""
    s = st(rt, blank)
    e = applied_not_recorded(rt, s, blank, monkeypatch)
    marker = s.head()["pending"]
    assert marker and marker["sha256"] == e["details"]["sha256"]
    n_journal = len(journal(s))

    real = DrawingStore.settle_pending
    calls = []

    def settle(self, **kw):
        f = open(self.head_path, "rb")  # busy for the settle ...
        calls.append(1)
        try:
            return real(self, **kw)
        finally:
            f.close()  # ... and free again before anything else touches head.json

    monkeypatch.setattr(DrawingStore, "settle_pending", settle)
    e2 = err(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    monkeypatch.undo()
    assert calls and e2["code"] == "FILE_BUSY" and e2["retryable"] and not e2["partial_changes"]
    assert s.head()["pending"] == marker  # untouched: still to be settled
    assert len(journal(s)) == n_journal
    ok(rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 5}]))
    recs = journal(s)
    assert [r["tool"] for r in recs[-2:]] == ["recover", "apply_operations"]
    assert recs[-2]["completed_commit"] == "apply_operations" and recs[-2]["sha256"] == e["details"]["sha256"]
    assert lines(ws, blank) == 1


def test_n1_recover_with_head_busy_is_retryable(rt, ws, blank, monkeypatch):
    s = st(rt, blank)
    applied_not_recorded(rt, s, blank, monkeypatch)
    with open(s.head_path, "rb"):
        e = err(rt.recover(blank))
    assert e["code"] == "FILE_BUSY" and e["retryable"] and not e["partial_changes"]
    assert s.head()["pending"] is not None
    assert ok(rt.recover(blank))["pending_commit"] == "completed"


def test_n2_the_recover_record_carries_the_operations(rt, ws, blank, monkeypatch):
    s = st(rt, blank)
    e = applied_not_recorded(rt, s, blank, monkeypatch)
    attempt = journal(s)[-1]
    assert attempt["ok"] is False and attempt["error"]["code"] == "FILE_BUSY" and attempt["operations"] == LINE
    ok(rt.recover(blank))
    rec = journal(s)[-1]
    assert rec["operations"] == LINE and rec["changes"]["added"] and rec["completed_seq"] == attempt["seq"]
    assert rec["sha256"] == e["details"]["sha256"]
