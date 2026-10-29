"""Test L: working alongside a running AutoCAD (autocad_live), against a stand-in for AutoCAD's COM objects.

The stand-in mirrors the parts of the AutoCAD ActiveX API the backend uses (Documents, Open, Close, Saved,
SaveAs, GetVariable, ZoomCenter/ZoomWindow, SendCommand). A real session is exercised by hand: AutoCAD's GUI
needs a signed-in licence, which a test cannot provide."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import ezdxf
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime
from conftest import ok

pytest.importorskip("pythoncom")


class FakeDoc:
    def __init__(self, app: "FakeApp", path: str, read_only: bool = False) -> None:
        self.app, self.FullName, self.Name, self.Saved = app, str(Path(path)), Path(path).name, True
        self.ReadOnly = read_only
        self.user_edit = None  # simulated GUI edit, applied to what SaveAs writes
        self.content = Path(path).read_bytes()  # like AutoCAD: what was read at open time, not the file later

    @property
    def Saved(self):
        return self._saved

    @Saved.setter
    def Saved(self, value):
        self._saved = value
        self.dbmod = 0 if value else 1  # tests marking a user edit default to an object modification

    def Activate(self):
        self.app.ActiveDocument = self

    def Close(self, save):
        self.app.log.append(("close", self.Name))
        self.app.docs.remove(self)

    def SaveAs(self, path, kind):
        assert kind == 65  # ac2018_dxf
        import io
        doc = ezdxf.read(io.StringIO(self.content.decode("utf-8", "replace")))
        if self.user_edit:
            self.user_edit(doc)
        doc.saveas(path)
        self.FullName, self.Name, self.Saved, self.ReadOnly = str(path), Path(path).name, True, False

    def GetVariable(self, name):
        return {"VIEWCTR": (1.0, 2.0, 0.0), "VIEWSIZE": 50.0, "DBMOD": self.dbmod,
                "VIEWDIR": (0.0, 0.0, 1.0), "VIEWTWIST": 0.0, "PERSPECTIVE": 0,
                "WORLDUCS": 1, "TILEMODE": 1, "CVPORT": 2}[name]

    def SendCommand(self, text):
        self.app.log.append(("command", text))
        self.Saved = False


class FakeDocuments:
    def __init__(self, app):
        self.app = app

    @property
    def Count(self):
        return len(self.app.docs)

    def Item(self, i):
        return self.app.docs[i]

    def Open(self, path, read_only):
        d = FakeDoc(self.app, path, read_only)
        self.app.docs.append(d)
        self.app.log.append(("open", d.Name))
        return d


class FakeApp:
    Version = "26.0s"

    def __init__(self):
        self.docs: list[FakeDoc] = []
        self.log: list[tuple] = []
        self.Documents = FakeDocuments(self)
        self.ActiveDocument = None

    def GetAcadState(self):
        return type("State", (), {"IsQuiescent": True})()

    def ZoomCenter(self, center, size):
        self.log.append(("zoom_center", tuple(center.value), size))
        previous = self.ActiveDocument.dbmod
        self.ActiveDocument.Saved = False
        self.ActiveDocument.dbmod = previous | 24

    def ZoomWindow(self, lo, hi):
        self.log.append(("zoom_window", tuple(lo.value), tuple(hi.value)))

    def ZoomExtents(self):
        self.log.append(("zoom_extents",))


def live_rt(ws: Path, app: FakeApp | None, **kw) -> Runtime:
    rt = Runtime(Policy(root=ws, **kw))
    rt.live_connect = lambda start=False: app
    return rt


def add_user_line(doc):
    doc.modelspace().add_line((0, 0), (100, 60), dxfattribs={"layer": "0"})


def test_not_running(ws, plate):
    rt = live_rt(ws, None)
    assert ok(rt.autocad_live("status")) ["running"] is False
    assert rt.autocad_live("open", plate)["error"]["code"] == "AUTOCAD_NOT_RUNNING"
    assert rt.autocad_live("dance")["error"]["code"] == "INVALID_ENUM"


def test_open_and_status(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app)
    r = ok(rt.autocad_live("open", plate))
    assert r["open_in_autocad"] and r["unsaved_changes"] is False and r["read_only"] is True
    assert "pull" in r["hint"]
    ok(rt.autocad_live("open", plate))  # already open: activated, not opened twice
    assert [x for x in app.log if x[0] == "open"] == [("open", "plate.dxf")]
    st = ok(rt.autocad_live("status"))
    assert st["running"] and st["documents"][0]["drawing"] == "plate.dxf"
    assert rt.autocad_live("open", "../x.dxf")["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_live_open_allows_atomic_commits_and_preserves_unsaved_gui_edits(ws, plate, monkeypatch):
    """Write-open holds a Windows lock; the read-only DXF open observed in AutoCAD permits replacement."""
    import win32con
    import win32file

    app = FakeApp()

    class LockedDoc(FakeDoc):
        def __init__(self, app, path, read_only):
            super().__init__(app, path, read_only)
            self.handle = None if read_only else win32file.CreateFile(
                str(path), win32con.GENERIC_READ, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)

        def Close(self, save):
            if self.handle is not None:
                self.handle.Close()
                self.handle = None
            super().Close(save)

        def SaveAs(self, path, kind):
            super().SaveAs(path, kind)
            if self.handle is not None:
                self.handle.Close()  # AutoCAD changed the open document's path, releasing the original file
                self.handle = None

    def open_locked(path, read_only):
        d = LockedDoc(app, path, read_only)
        app.docs.append(d)
        app.log.append(("open", d.Name))
        return d

    monkeypatch.setattr(app.Documents, "Open", open_locked)
    rt = live_rt(ws, app, live_sync=True)
    opened = ok(rt.autocad_live("open", plate))
    assert opened["read_only"] is True and app.docs[0].ReadOnly is True
    r = ok(rt.apply_operations(plate, [{"op": "add_circle", "center": [50, 30], "diameter": 20}]))
    assert r["live"]["reloaded"] and app.docs[0].ReadOnly is True
    assert ezdxf.readfile(ws / plate).modelspace().query("CIRCLE[radius==10]")

    # The GUI may be edited while read-only; an agent commit must not discard those unsaved edits.
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    r = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}]))
    assert r["live"]["error"]["code"] == "AUTOCAD_UNSAVED_CHANGES" and app.docs[0].Saved is False
    assert rt.autocad_live("pull", plate)["error"]["code"] == "LIVE_CONFLICT"
    assert app.docs[0].Saved is False
    ok(rt.autocad_live("pull", plate, force=True))
    assert app.docs[0].ReadOnly is True
    assert any(e.dxftype() == "LINE" and e.dxf.end.x == 100 for e in ezdxf.readfile(ws / plate).modelspace())
    app.docs[0].Close(False)


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_user_write_open_drawing_is_not_silently_closed(ws, plate, monkeypatch):
    import win32con
    import win32file

    app = FakeApp()
    doc = app.Documents.Open(str(ws / plate), False)
    handle = win32file.CreateFile(str(ws / plate), win32con.GENERIC_READ,
                                  win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None,
                                  win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
    monkeypatch.setattr("agentcad.store.REPLACE_TIMEOUT", 0.05)
    rt = live_rt(ws, app, live_sync=True)
    try:
        before = (ws / plate).read_bytes()
        r = ok(rt.autocad_live("open", plate))
        assert r["read_only"] is False and "reload" in r["hint"]
        failed = rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}])
        assert failed["error"]["code"] == "FILE_BUSY" and (ws / plate).read_bytes() == before
        assert app.docs == [doc] and not doc.ReadOnly
    finally:
        handle.Close()
    assert ok(rt.autocad_live("reload", plate))["reloaded"]
    assert app.docs[0].ReadOnly is True
    assert ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}]))["live"]["reloaded"]


def test_live_sync_reopens_after_each_change_and_keeps_the_view(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app, live_sync=True)
    ok(rt.autocad_live("open", plate))
    r = ok(rt.apply_operations(plate, [{"op": "add_circle", "center": [50, 30], "diameter": 20}]))
    assert r["live"] == {"reloaded": True, "open_in_autocad": True, "view_kept": True}
    assert app.log[-3:] == [("close", "plate.dxf"), ("open", "plate.dxf"), ("zoom_center", (1.0, 2.0, 0.0), 50.0)]
    # the user has unsaved edits in AutoCAD: the agent's change is committed, AutoCAD is left alone
    app.docs[0].Saved = False
    r = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}]))
    assert r["live"]["reloaded"] is False and r["live"]["error"]["code"] == "AUTOCAD_UNSAVED_CHANGES"
    assert rt.autocad_live("reload", plate)["error"]["code"] == "AUTOCAD_UNSAVED_CHANGES"
    assert ok(rt.autocad_live("reload", plate, discard=True))["reloaded"] is True
    # no sync when the drawing is not open in AutoCAD, and nothing without live_sync
    assert ok(rt.apply_operations("plate.dxf", [{"op": "add_point", "location": [2, 2]}]))["live"]["reloaded"]
    assert "live" not in ok(live_rt(ws, app).apply_operations(plate, [{"op": "add_point", "location": [3, 3]}]))


def test_repeated_sync_after_zoom_does_not_mistake_view_changes_for_drawing_edits(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app, live_sync=True)
    ok(rt.autocad_live("open", plate))
    for index in range(3):
        result = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [index, index]}]))
        assert result["live"]["reloaded"] and result["live"]["view_kept"]
        assert app.docs[0].Saved is False and app.docs[0].dbmod == 24
    assert len(ezdxf.readfile(ws / plate).modelspace().query("POINT")) == 3


@pytest.mark.parametrize("dbmod", [0, 1, 2, 4, 17, 25, 32, 64])
def test_reload_protects_every_non_view_only_unsaved_change(ws, plate, dbmod):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    doc = app.docs[0]
    doc.Saved, doc.dbmod = False, dbmod
    assert rt.autocad_live("reload", plate)["error"]["code"] == "AUTOCAD_UNSAVED_CHANGES"
    assert app.docs == [doc]


@pytest.mark.parametrize("variable,value", [("VIEWDIR", (1.0, 0.0, 0.0)), ("VIEWTWIST", 0.5),
                                           ("PERSPECTIVE", 1), ("WORLDUCS", 0), ("TILEMODE", 0)])
def test_reload_keeps_unsaved_views_that_center_and_size_cannot_restore(ws, plate, variable, value):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    doc = app.docs[0]
    doc.Saved, doc.dbmod = False, 16
    original = doc.GetVariable
    doc.GetVariable = lambda name: value if name == variable else original(name)
    assert rt.autocad_live("reload", plate)["error"]["code"] == "AUTOCAD_UNSAVED_CHANGES"
    assert app.docs == [doc]


@pytest.mark.parametrize("dbmod", [8, 16, 24])
def test_reload_restores_an_ordinary_paper_space_view(ws, plate, dbmod):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    doc = app.docs[0]
    doc.Saved, doc.dbmod = False, dbmod
    original = doc.GetVariable
    doc.GetVariable = lambda name: {"TILEMODE": 0, "CVPORT": 1}.get(name, original(name))
    assert ok(rt.autocad_live("reload", plate))["view_kept"]


def test_pull_commits_the_users_edits(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    none = ok(rt.autocad_live("pull", plate))
    assert none["changed"] is False and "journal_seq" not in none
    n_cp = len(ok(rt.list_checkpoints(plate))["checkpoints"])
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    r = ok(rt.autocad_live("pull", plate, label="user added a line"))
    assert r["changed"] and len(r["changes"]["added"]) == 1 and r["changes"]["deleted"] == []
    assert r["validation"]["passed"] and r["checkpoint_before"]
    assert len(ok(rt.list_checkpoints(plate))["checkpoints"]) == n_cp + 1
    assert any(e.dxftype() == "LINE" and e.dxf.end.x == 100 for e in ezdxf.readfile(ws / plate).modelspace())
    # AutoCAD shows the committed file again, at the same view; the temporary DXF is gone
    assert [d.FullName for d in app.docs] == [str(ws / plate)] and app.log[-1][0] == "zoom_center"
    assert not any((ws / ".agentcad" / "live").glob("*.dxf"))
    last = ok(rt.history(plate))["records"][-1]
    assert last["tool"] == "autocad_live" and last["changes"]["added"] == 1
    ok(rt.rollback(plate))  # undo works as for any change
    assert not any(e.dxftype() == "LINE" and e.dxf.end.x == 100 for e in ezdxf.readfile(ws / plate).modelspace())


def test_pull_needs_write_access_and_an_open_drawing(ws, plate):
    app = FakeApp()
    assert live_rt(ws, app).autocad_live("pull", plate)["error"]["code"] == "NOT_OPEN_IN_AUTOCAD"
    ro = live_rt(ws, app, read_only=True)
    ok(ro.autocad_live("open", plate))
    assert ro.autocad_live("pull", plate)["error"]["code"] == "READ_ONLY"


def test_zoom_and_gated_commands(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app)
    r = ok(rt.autocad_live("zoom", plate, ids=["tag:hole.bl"]))
    (x0, y0), (x1, y1) = r["window"]
    assert x0 < 6 < 14 < x1 and app.log[-1][0] == "zoom_window"
    assert ok(rt.autocad_live("zoom", plate))["window"] == "extents"
    assert rt.autocad_live("command", plate, command="_.ERASE _ALL ")["error"]["code"] == "LIVE_COMMANDS_DISABLED"
    rt2 = live_rt(ws, app, allow_live_commands=True)
    r = ok(rt2.autocad_live("command", plate, command="_.LINE _non 0,0 _non 10,10 "))
    assert app.log[-1] == ("command", "_.LINE _non 0,0 _non 10,10 ") and "pull" in r["hint"] and r["finished"]
    assert rt2.autocad_live("command", plate, command="  ")["error"]["code"] == "INVALID_STRING"


def test_pull_refuses_to_revert_newer_agent_changes(ws, plate):
    """AutoCAD keeps what it read at open time. Pulling it after the agent changed the file would silently undo
    the agent's change, so pull refuses unless forced (and the forced pull keeps a checkpoint)."""
    app = FakeApp()
    rt = live_rt(ws, app)  # no live sync: AutoCAD is not reloaded after the agent's change
    ok(rt.autocad_live("open", plate))
    ok(rt.apply_operations(plate, [{"op": "add_circle", "center": [50, 30], "radius": 3, "tag": "agent"}]))
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    e = rt.autocad_live("pull", plate)["error"]
    assert e["code"] == "LIVE_CONFLICT" and "force" in e["hint"]
    assert app.docs[0].Saved is False and app.docs[0].FullName == str(ws / plate)  # AutoCAD untouched
    r = ok(rt.autocad_live("pull", plate, force=True))
    assert r["forced"] and r["changed"]
    assert not ezdxf.readfile(ws / plate).query("CIRCLE[radius==3]")  # AutoCAD's version won, as asked
    sm = ok(rt.get_diff(plate))["summary"]  # the agent's circle is in the checkpoint (its handle may be reused)
    assert sm["deleted"] + sm["modified"] >= 1
    # after the pull AutoCAD shows the committed file: the next pull is not stale
    assert ok(rt.autocad_live("pull", plate))["changed"] is False


def test_pull_of_a_drawing_this_runtime_did_not_open(ws, plate):
    app = FakeApp()
    app.Documents.Open(str(ws / plate), False)  # the user opened it themselves
    e = live_rt(ws, app).autocad_live("pull", plate)["error"]
    assert e["code"] == "LIVE_CONFLICT"
    assert ok(live_rt(ws, app).autocad_live("pull", plate, force=True))["forced"]


def test_pull_keeps_edits_that_are_not_entities(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    app.docs[0].user_edit = lambda d: d.layers.add("USER_LAYER", color=2)
    app.docs[0].Saved = False
    r = ok(rt.autocad_live("pull", plate))
    assert r["changed"] and r["layers"]["added"] == ["USER_LAYER"]
    assert "USER_LAYER" in ezdxf.readfile(ws / plate).layers


def test_failed_pull_keeps_autocads_copy(ws, plate, monkeypatch):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    before = (ws / plate).read_bytes()

    def boom(*a, **k):
        from agentcad.errors import file_error
        raise file_error("FILE_TOO_LARGE", "simulated")
    monkeypatch.setattr("agentcad.store.DrawingStore.commit", boom)
    e = rt.autocad_live("pull", plate)["error"]
    copy = ws / e["details"]["autocad_copy"]
    assert copy.is_file() and any(x.dxftype() == "LINE" and x.dxf.end.x == 100
                                  for x in ezdxf.readfile(copy).modelspace())
    assert (ws / plate).read_bytes() == before and app.docs[0].FullName == str(copy)  # nothing closed or lost


def test_dry_runs_do_not_touch_autocad(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app, live_sync=True)
    ok(rt.autocad_live("open", plate))
    n = len(app.log)
    r = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}], dry_run=True))
    assert "live" not in r and len(app.log) == n


def test_sync_survives_unexpected_com_errors(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app, live_sync=True)
    ok(rt.autocad_live("open", plate))
    app.Documents = None  # anything at all going wrong inside AutoCAD
    r = ok(rt.apply_operations(plate, [{"op": "add_point", "location": [1, 1]}]))
    assert r["live"]["reloaded"] is False and "error" in r["live"]


def test_drawing_the_user_opened_before_an_agent_change(ws, plate):
    """Review of PR #5: AutoCAD had the drawing open already; the agent then changed the file. 'open' only
    activates it, so AutoCAD still shows the old version and a pull must not revert the agent's change."""
    app = FakeApp()
    rt = live_rt(ws, app)
    app.Documents.Open(str(ws / plate), False)  # the user opened it
    ok(rt.apply_operations(plate, [{"op": "add_circle", "center": [50, 30], "radius": 3}]))
    r = ok(rt.autocad_live("open", plate))
    assert "reload" in r["hint"]
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    assert rt.autocad_live("pull", plate)["error"]["code"] == "LIVE_CONFLICT"
    assert ezdxf.readfile(ws / plate).query("CIRCLE[radius==3]")  # the agent's circle is still there


def test_unexpected_failure_in_pull_still_reports_autocads_copy(ws, plate, monkeypatch):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False
    monkeypatch.setattr("agentcad.service.diff_docs", lambda *a: {}["boom"])
    e = rt.autocad_live("pull", plate)["error"]
    assert e["code"] == "INTERNAL_ERROR" and (ws / e["details"]["autocad_copy"]).is_file()


def test_failing_reopen_does_not_fail_a_committed_pull(ws, plate):
    app = FakeApp()
    rt = live_rt(ws, app)
    ok(rt.autocad_live("open", plate))
    app.docs[0].user_edit = add_user_line
    app.docs[0].Saved = False

    def broken_open(path, read_only):
        raise RuntimeError("AutoCAD went away")
    app.Documents.Open = broken_open
    r = ok(rt.autocad_live("pull", plate))
    assert r["changed"] and r["live"]["reopened"] is False and r["journal_seq"]
