"""Live viewer, friendly edition: progress events (progress.py), the viewer started by the MCP server, the HTML
snapshot export, before/after framing and thumbnails."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from agentcad import progress
from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.service import Runtime
from agentcad.viewer import ChangeFeed, Viewer, Workspace
from conftest import ok

needs_freecad = pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed (set AGENTCAD_FREECAD)")

OPS = [{"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "layer": "OUTLINE"},
       {"op": "add_circle", "center": [20, 20], "diameter": 8, "layer": "HOLES"},
       {"op": "add_circle", "center": [80, 20], "diameter": 8, "layer": "HOLES"}]


def events(ws: Path) -> list[dict]:
    f = ws / ".agentcad" / "activity.jsonl"
    return [json.loads(x) for x in f.read_text("utf-8").splitlines()] if f.exists() else []


@pytest.fixture
def cache(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("viewer-cache")


@pytest.fixture
def viewer(ws, cache):
    v = Viewer(Policy(root=ws), port=0, interval=0.05, cache_dir=cache).start()
    yield v
    v.stop()


def get(srv: Viewer, route: str, **q):
    url = srv.url.rstrip("/") + route + ("?" + urllib.parse.urlencode(q) if q else "")
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.status, r.headers, r.read()


# --- progress events ----------------------------------------------------------------------------------------

def test_a_batch_reports_start_steps_checking_and_done(rt, ws, blank):
    before = len(events(ws))
    ok(rt.apply_operations(blank, OPS, label="plate"))
    evs = events(ws)[before:]
    assert {e["run"] for e in evs} == {evs[0]["run"]} and [e["n"] for e in evs] == list(range(1, len(evs) + 1))
    states = [e["state"] for e in evs]
    assert states[0] == "working" and evs[0]["step"] == 0 and evs[0]["total"] == 3
    assert states[-2:] == ["checking", "done"]
    steps = [e for e in evs if e["state"] == "working" and e["step"]]
    assert steps[0]["step"] == 1 and steps[-1]["step"] == 3  # first and last always, the rest throttled
    assert steps[0]["op"] == {"op": "add_rectangle", "width": 100, "height": 60}
    done = evs[-1]
    assert done["drawing"] == blank and done["tool"] == "apply_operations"
    assert done["changes"] == {"added": 3, "modified": 0, "deleted": 0} and done["total"] == 3
    assert done["ops"] == [{"op": "add_rectangle", "width": 100, "height": 60, "n": 1},
                           {"op": "add_circle", "diameter": 8, "n": 2}]
    assert done["passed"] is True and isinstance(done["issues"], int)


def test_a_failed_batch_reports_the_error_without_absolute_paths(rt, ws, blank):
    r = rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "diameter": -1}])
    assert not r["ok"]
    last = events(ws)[-1]
    assert last["state"] == "error" and last["error"]["code"] == r["error"]["code"]
    assert str(ws) not in json.dumps(last)


def test_scrub_removes_absolute_paths():
    root = Path(r"D:\work\ws")
    s = progress.scrub(r"D:\work\ws\parts\a.dxf and C:\Users\bob\secret.dxf, /home/bob/x.dxf, \\srv\share\y", root)
    assert s == "parts\\a.dxf and <path>, <path>, <path>"
    assert progress.scrub("width 10/20 mm, ratio a/b") == "width 10/20 mm, ratio a/b"


def test_nested_create_is_one_run_and_dry_runs_report_nothing(rt, ws):
    ok(rt.apply_operations("new.dxf", OPS[:1], create={"units": "mm"}))
    assert len({e["run"] for e in events(ws)}) == 1
    n = len(events(ws))
    ok(rt.apply_operations("new.dxf", OPS[1:], dry_run=True))
    assert len(events(ws)) == n


def test_checks_report_a_verdict(rt, ws, plate):
    ok(rt.validate_drawing(plate))
    evs = [e for e in events(ws) if e["tool"] == "validate_drawing"]
    assert [e["state"] for e in evs] == ["checking", "done"] and evs[-1]["passed"] is True


def test_progress_never_fails_a_commit(rt, ws, blank):
    log = ws / ".agentcad" / "activity.jsonl"
    log.unlink(missing_ok=True)
    log.mkdir(parents=True)  # appending is now impossible
    r = ok(rt.apply_operations(blank, OPS))
    assert r["changes"]["added"]


def test_read_only_runtime_writes_no_progress(ws, blank):
    ro = Runtime(Policy(root=ws, read_only=True))
    n = len(events(ws))
    assert not ro.apply_operations(blank, OPS)["ok"]
    ro.validate_drawing(blank)
    assert len(events(ws)) == n


def test_group_ops_counts_identical_steps():
    g = progress.group_ops([{"op": "add_sketch", "shapes": [{}]}, {"op": "pocket", "through_all": True}] * 3
                           + [{"op": "fillet", "radius": 2, "edges": "all"}])
    assert g == [{"op": "add_sketch", "shapes": 1, "n": 3}, {"op": "pocket", "through_all": True, "n": 3},
                 {"op": "fillet", "radius": 2, "n": 1}]
    many = progress.group_ops([{"op": "add_circle", "diameter": d} for d in range(progress.MAX_GROUPS + 5)])
    assert len(many) == progress.MAX_GROUPS + 1 and many[-1] == {"op": "...", "n": 5}


def test_feed_and_http_serve_progress(rt, ws, blank, viewer):
    feed = viewer.feed
    last = feed.last_id
    ok(rt.apply_operations(blank, OPS))
    deadline = time.time() + 10
    while time.time() < deadline and not any(e["kind"] == "activity" and e["activity"]["state"] == "done"
                                             for e in feed.since(last, progress=True)):
        feed.wait(feed.last_id, 0.5, progress=True)
    kinds = {e["kind"] for e in feed.since(last, progress=True)}
    assert {"activity", "changed"} <= kinds
    assert all(e["kind"] != "activity" for e in feed.since(last))  # plain /api/events stays file events only
    code, _, body = get(viewer, "/api/activity")
    acts = json.loads(body)["events"]
    assert code == 200 and acts[-1]["state"] == "done" and acts[-1]["drawing"] == blank
    for route in ("/friendly.js", "/logo.svg"):
        assert get(viewer, route)[0] == 200


def test_feed_starts_from_the_existing_log_and_follows_rotation(rt, ws, blank, cache):
    ok(rt.apply_operations(blank, OPS))
    feed = ChangeFeed(Workspace(Policy(root=ws, read_only=True), cache))
    assert feed.activity and feed.activity[-1]["state"] == "done" and not feed.progress_events
    log = ws / ".agentcad" / "activity.jsonl"
    log.replace(log.with_name("activity.jsonl.1"))  # rotated: the next run starts a new, smaller file
    ok(rt.apply_operations(blank, OPS[:1]))
    feed.poll()
    assert [e["activity"]["state"] for e in feed.progress_events][-1] == "done"


@needs_freecad
def test_a_3d_batch_reports_each_operation(rt, ws):
    ops = [{"op": "set_parameters", "params": {"w": 40}},
           {"op": "add_sketch", "plane": "XY", "shapes": [{"type": "rectangle", "corner": [0, 0], "width": "=Params.w",
                                                           "height": 30}]},
           {"op": "pad", "sketch": "$1", "length": 5},
           {"op": "fillet", "edges": {"type": "line", "direction": "z"}, "radius": 2}]
    ok(rt.apply_operations("p.FCStd", ops, create={"units": "mm"}))
    evs = events(ws)
    assert [e["state"] for e in evs][-2:] == ["checking", "done"]
    steps = [e["step"] for e in evs if e["state"] == "working" and e["step"]]
    assert steps and steps == sorted(steps) and steps[-1] == 4 and len(steps) >= 2  # relayed while FreeCAD runs
    assert evs[-1]["ops"][0] == {"op": "set_parameters", "params": {"w": 40}, "n": 1}


# --- the viewer the MCP server starts --------------------------------------------------------------------------

def test_mcp_runtime_starts_a_viewer_on_the_first_change(ws, monkeypatch):
    monkeypatch.setenv("AGENTCAD_VIEWER", "1")
    monkeypatch.setenv("AGENTCAD_VIEWER_PORT", "0")
    monkeypatch.delenv("AGENTCAD_VIEWER_OPEN", raising=False)
    rt = Runtime(Policy(root=ws), auto_viewer=True)
    assert "viewer_url" not in ok(rt.read_drawing(ok(rt.create_drawing("a.dxf"))["drawing"]))
    try:
        r = ok(rt.apply_operations("a.dxf", OPS))
        url = r["viewer_url"]
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+/#a\.dxf", url)
        with urllib.request.urlopen(url.split("#")[0] + "api/ping", timeout=10) as resp:
            assert Path(json.loads(resp.read())["root"]) == ws.resolve()
        b = ok(rt.apply_batch([{"path": "b.dxf", "operations": OPS[:1], "create": {"units": "mm"}}]))
        assert b["viewer_url"] == url.split("#")[0] + "#b.dxf"
        assert "viewer_url" not in ok(rt.apply_operations("a.dxf", OPS[:1], dry_run=True))
        # another runtime on the same root (a second agent) finds this viewer instead of starting one
        other = Runtime(Policy(root=ws), auto_viewer=True)
        assert ok(other.apply_operations("a.dxf", OPS[:1]))["viewer_url"] == url
        assert other._viewer is None
    finally:
        rt._viewer.stop()


def test_viewer_autostart_opt_out(ws, monkeypatch):
    monkeypatch.setenv("AGENTCAD_VIEWER", "0")
    rt = Runtime(Policy(root=ws), auto_viewer=True)
    assert "viewer_url" not in ok(rt.apply_operations("a.dxf", OPS, create={"units": "mm"}))
    assert rt._viewer is None and not (ws / ".agentcad" / "viewer.json").exists()


def test_mcp_server_tells_agents_to_share_the_link():
    from agentcad.mcp_server import INSTRUCTIONS
    assert "viewer_url" in INSTRUCTIONS


# --- export, before/after, thumbnails ---------------------------------------------------------------------------

def test_html_export_is_self_contained_and_leaks_no_paths(rt, ws, blank, viewer):
    ok(rt.apply_operations(blank, OPS[:1], label=f"outline from {ws / 'notes' / 'spec.pdf'}"))
    ok(rt.apply_operations(blank, OPS[1:], label=r"holes as in C:\Users\someone\Desktop\old.dxf"))
    rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "diameter": -1}], label="bad")
    code, headers, body = get(viewer, "/api/export", path=blank)
    page = body.decode("utf-8")
    assert code == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Content-Disposition"].startswith('attachment; filename="blank-')
    # nothing is loaded from anywhere: no external scripts, styles, images or links
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:|//)""", page) and "<link" not in page
    assert "import(" not in page and "fetch(" not in page
    for leak in (str(ws), str(ws).replace("\\", "/"), "someone", str(Path.home())):
        assert leak not in page
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert data["name"] == blank and data["kind"] == "drawing"
    assert data["image"].startswith("data:image/svg+xml;base64,") and data["image_before"] and data["image_after"]
    assert [h["ok"] for h in data["history"]] == [True, True, True, False]
    assert data["history"][-2]["shown"] is True and data["history"][-2]["steps"] == [
        {"op": "add_circle", "diameter": 8, "n": 2}]
    assert data["history"][1]["label"] == str(Path("outline from notes") / "spec.pdf")  # relative to the workspace
    assert "<path>" in data["history"][2]["label"]
    assert "AgentCADFriendly" in page  # the wording script is inlined
    # an older version exports too
    first = json.loads(get(viewer, "/api/timeline", path=blank)[2])["records"][1]["version"]
    assert get(viewer, "/api/export", path=blank, v=first)[0] == 200


def test_export_file_name_keeps_unicode(rt, viewer):
    ok(rt.apply_operations("底板.dxf", OPS[:1], create={"units": "mm"}))
    _, headers, _ = get(viewer, "/api/export", path="底板.dxf")
    cd = headers["Content-Disposition"]
    assert "filename*=UTF-8''%E5%BA%95%E6%9D%BF-" in cd and cd.isascii()


def test_before_and_after_are_framed_alike(rt, blank):
    ws_ = Workspace(Policy(root=rt.policy.root, read_only=True))
    ok(rt.apply_operations(blank, OPS[:1]))
    ok(rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [300, 200], "layer": "OUTLINE"}]))
    tl = ws_.timeline(blank)
    a, b = tl["records"][-2]["version"], tl["records"][-1]["version"]
    vb = lambda s: re.search(r'viewBox="([^"]+)"', s).group(1)  # noqa: E731
    assert vb(ws_.svg(blank, a)) != vb(ws_.svg(blank, b))
    assert vb(ws_.svg(blank, a, frame=b)) == vb(ws_.svg(blank, b, frame=a))


def test_thumbnail_of_a_drawing(rt, blank, viewer):
    ok(rt.apply_operations(blank, OPS))
    code, headers, body = get(viewer, "/api/thumb", path=blank)
    assert code == 200 and headers["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg")


@needs_freecad
def test_part_export_and_thumbnail(rt, ws, viewer):
    ops = [{"op": "add_sketch", "plane": "XY", "shapes": [{"type": "rectangle", "corner": [0, 0], "width": 40, "height": 30}]},
           {"op": "pad", "sketch": "$0", "length": 5}]
    ok(rt.apply_operations("p.FCStd", ops, create={"units": "mm"}))
    code, headers, png = get(viewer, "/api/thumb", path="p.FCStd")
    assert code == 200 and headers["Content-Type"] == "image/png" and png[:8] == b"\x89PNG\r\n\x1a\n"
    page = get(viewer, "/api/export", path="p.FCStd")[2].decode("utf-8")
    assert '"image": "data:image/png;base64,' in page and str(ws) not in page
