"""Live viewer (viewer.py): change feed, versions, render endpoints, SSE, and that it never writes the workspace."""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from agentcad.policy import Policy
from agentcad.store import sha256_file
from agentcad.viewer import COLORS, ChangeFeed, Viewer, Workspace
from conftest import ok


def line(rt, path, start, end, layer="OUTLINE", tag=None):
    op = {"op": "add_line", "start": start, "end": end, "layer": layer, **({"tag": tag} if tag else {})}
    return ok(rt.apply_operations(path, [op]))


@pytest.fixture
def cache(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("viewer-cache")


@pytest.fixture
def workspace(ws, cache) -> Workspace:
    return Workspace(Policy(root=ws, read_only=True), cache)


@pytest.fixture
def viewer(ws, cache):
    v = Viewer(Policy(root=ws), port=0, interval=0.05, cache_dir=cache).start()
    yield v
    v.stop()


def get(srv: Viewer, route: str, **q):
    url = srv.url.rstrip("/") + route + ("?" + urllib.parse.urlencode(q) if q else "")
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def get_json(srv: Viewer, route: str, **q):
    code, _, body = get(srv, route, **q)
    return code, json.loads(body)


def files_state(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*")
            if p.is_file() and p.name != "viewer.json"}


# --- versions and timeline ---------------------------------------------------------------------------------

def test_timeline_maps_each_commit_to_a_stored_version(rt, ws, blank, workspace):
    line(rt, blank, [0, 0], [100, 0], tag="a")
    line(rt, blank, [0, 0], [0, 50], tag="b")
    bad = rt.apply_operations(blank, [{"op": "add_line", "start": [1, 1], "end": [1, 1]}])
    assert not bad["ok"]
    tl = workspace.timeline(blank)
    recs = tl["records"]
    assert [r["tool"] for r in recs] == ["create_drawing", "apply_operations", "apply_operations", "apply_operations"]
    commits = [r for r in recs if r.get("version")]
    assert len(commits) == 3 and all(r["available"] for r in commits)
    assert recs[-1]["ok"] is False and "version" not in recs[-1] and recs[-1]["error"]["code"]
    assert commits[1]["ops"] == ["add_line"]
    assert commits[-1]["version"] == tl["current"] == sha256_file(ws / blank)
    # each commit records the version it started from, so its diff is the edit it made
    assert commits[2]["before"] == commits[1]["version"]
    assert not tl["modified_outside_runtime"]


def test_timeline_pages_preserve_order_even_with_legacy_duplicate_sequences(rt, blank, viewer):
    line(rt, blank, [0, 0], [100, 0])
    line(rt, blank, [0, 0], [0, 50])
    _, store = rt._drawing(blank)
    with store.journal_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"seq": 3, "tool": "export_drawing", "ok": True, "label": "legacy duplicate"}) + "\n")
    code, recent = get_json(viewer, "/api/timeline", path=blank, limit=1)
    assert code == 200 and recent["records"][0]["label"] == "legacy duplicate"
    code, earlier = get_json(viewer, "/api/timeline", path=blank, limit=3, cursor=recent["next_cursor"])
    assert code == 200 and [r["seq"] for r in earlier["records"]] == [1, 2, 3]
    assert earlier["next_cursor"] is None and earlier["current"] == recent["current"]
    assert get_json(viewer, "/api/timeline", path=blank, limit=0)[0] == 400
    assert get_json(viewer, "/api/timeline", path=blank, limit=1, cursor=1)[0] == 400


def test_old_versions_render_and_diff(rt, blank, workspace):
    line(rt, blank, [0, 0], [100, 0], tag="a")
    v1 = workspace.timeline(blank)["current"]
    line(rt, blank, [0, 0], [0, 50], layer="HIDDEN_L", tag="b")
    cur = workspace.svg(blank, None)
    old = workspace.svg(blank, v1)
    assert cur.startswith("<svg") and old.startswith("<svg") and cur != old
    d = workspace.diff(blank, None)
    assert d["before"] == v1 and d["summary"]["added"] == 1 and d["added"][0]["tag"] == "b"
    assert workspace.diff(blank, v1)["summary"]["added"] == 1  # v1 itself added line a
    # highlight: the added line green, the rest grey
    hl = workspace.svg(blank, None, diff=True)
    assert COLORS["added"] in hl and COLORS["other"] in hl
    # hiding a layer drops its geometry but keeps the frame
    hidden = workspace.svg(blank, None, hide=("HIDDEN_L",))
    assert hidden.count("<path") < cur.count("<path")
    assert hidden.split(">")[0] == cur.split(">")[0]  # same viewBox
    layers = {l["name"]: l["entities"] for l in workspace.layers(blank, None)["layers"]}
    assert layers["OUTLINE"] == 1 and layers["HIDDEN_L"] == 1


def test_unknown_version_and_outside_paths_are_refused(blank, workspace):
    from agentcad.errors import AgentCADError
    with pytest.raises(AgentCADError) as e:
        workspace.svg(blank, "0" * 64)
    assert e.value.code == "VERSION_NOT_FOUND"
    with pytest.raises(AgentCADError) as e:
        workspace.svg("../outside.dxf", None)
    assert e.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_edit_outside_the_runtime_is_flagged_and_still_shown(rt, ws, blank, workspace):
    line(rt, blank, [0, 0], [10, 0])
    import ezdxf
    doc = ezdxf.readfile(ws / blank)
    doc.modelspace().add_circle((0, 0), 5)
    doc.saveas(ws / blank)
    tl = workspace.timeline(blank)
    assert tl["modified_outside_runtime"]
    assert workspace.svg(blank, None).startswith("<svg")
    assert "before" not in workspace.diff(blank, None) or workspace.diff(blank, None)["before"] is None


# --- change feed ---------------------------------------------------------------------------------------------

def test_change_feed_reports_added_changed_removed(rt, ws, blank, workspace):
    feed = ChangeFeed(workspace, rescan=0)
    assert feed.events == []  # what exists at start is not news
    line(rt, blank, [0, 0], [10, 0])
    feed.poll()
    assert [(e["drawing"], e["kind"]) for e in feed.events] == [(blank, "changed")]
    ok(rt.create_drawing("sub/new.dxf"))
    feed.poll()
    assert (("sub/new.dxf", "added")) in [(e["drawing"], e["kind"]) for e in feed.events]
    n = feed.last_id
    feed.poll()
    assert feed.last_id == n  # nothing changed, nothing reported
    os.remove(ws / "sub" / "new.dxf")
    feed.poll()
    assert feed.events[-1]["drawing"] == "sub/new.dxf" and feed.events[-1]["kind"] == "removed"
    assert [e["id"] for e in feed.since(n)] == [n + 1]


def test_listing_skips_state_and_tool_folders(rt, ws, blank, workspace):
    line(rt, blank, [0, 0], [10, 0])  # creates checkpoints under .agentcad/
    (ws / ".venv").mkdir()
    (ws / ".venv" / "x.dxf").write_text("0\nEOF\n")
    assert workspace.list_drawings() == [blank]


# --- HTTP server ------------------------------------------------------------------------------------------------

def test_http_endpoints(rt, ws, blank, viewer):
    line(rt, blank, [0, 0], [100, 0], tag="a")
    code, ctype, body = get(viewer, "/")
    assert code == 200 and "text/html" in ctype and b'id="root"' in body and b"/friendly.js" in body
    # the page is the build of web/viewer: its script (with the live feed) and styles are served from /app/assets/
    assets = re.findall(rb'(?:src|href)="(/app/assets/[^"]+)"', body)
    assert any(a.endswith(b".js") for a in assets) and any(a.endswith(b".css") for a in assets)
    for a in assets:
        code, ctype, data = get(viewer, a.decode())
        assert code == 200 and data and ctype.startswith("text/javascript" if a.endswith(b".js") else "text/css")
        if a.endswith(b".js"):
            assert b"EventSource" in data and b"/api/events" in data
    code, r = get_json(viewer, "/api/drawings")
    assert code == 200 and r["drawings"] == [{"path": blank, "kind": "drawing"}]
    code, tl = get_json(viewer, "/api/timeline", path=blank)
    assert code == 200 and tl["records"][-1]["ops"] == ["add_line"]
    first = tl["records"][0]["version"]
    code, ctype, body = get(viewer, "/api/svg", path=blank, v="current", diff="1")
    assert code == 200 and ctype == "image/svg+xml" and body.startswith(b"<svg")
    code, ctype, _ = get(viewer, "/api/svg", path=blank, v=first)
    assert code == 200
    code, d = get_json(viewer, "/api/diff", path=blank)
    assert code == 200 and d["summary"]["added"] == 1
    code, l = get_json(viewer, "/api/layers", path=blank)
    assert code == 200 and any(x["name"] == "OUTLINE" for x in l["layers"])
    assert get_json(viewer, "/api/svg", path=blank, v="f" * 64)[0] == 404
    assert get_json(viewer, "/api/svg", path="../x.dxf")[0] == 403
    assert get_json(viewer, "/api/svg", path="missing.dxf")[0] == 404
    assert get_json(viewer, "/api/timeline")[0] == 400
    assert get_json(viewer, "/nope")[0] == 404


def test_sse_pushes_a_commit(rt, blank, viewer):
    url = viewer.url + "api/events"
    got: list[dict] = []

    def listen():
        with urllib.request.urlopen(url, timeout=20) as r:
            for raw in r:
                s = raw.decode().strip()
                if s.startswith("data:"):
                    got.append(json.loads(s[5:]))
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    import time
    time.sleep(0.3)  # let the stream open before the commit
    line(rt, blank, [0, 0], [10, 0])
    t.join(15)
    assert got and got[0]["drawing"] == blank and got[0]["kind"] == "changed"


def test_viewer_never_writes_the_workspace(rt, ws, blank, viewer):
    line(rt, blank, [0, 0], [100, 0])
    before = files_state(ws)
    tl = get_json(viewer, "/api/timeline", path=blank)[1]
    for rec in tl["records"]:
        if rec.get("version"):
            assert get(viewer, "/api/svg", path=blank, v=rec["version"], diff="1")[0] == 200
            assert get(viewer, "/api/diff", path=blank, v=rec["version"])[0] == 200
    assert files_state(ws) == before


def test_viewer_url_in_create_drawing_only_while_a_viewer_runs(rt, ws, viewer):
    r = ok(rt.create_drawing("shown.dxf"))
    assert r["viewer_url"] == viewer.url + "#shown.dxf"
    viewer.stop()
    assert not (ws / ".agentcad" / "viewer.json").exists()
    assert "viewer_url" not in ok(rt.create_drawing("hidden.dxf"))


def test_open_reuses_the_running_viewer_without_loading_ezdxf(ws, viewer):
    """The desktop icon while AgentCAD already runs: only the browser opens, and ezdxf (a second to import) is not
    loaded, so the icon's window closes sooner."""
    import subprocess
    import sys
    code = ("import json, sys, webbrowser\n"
            "opened = []\n"
            "webbrowser.open = lambda url, *a, **k: opened.append(url) or True\n"
            "from agentcad.cli import run\n"
            "r, code = run(['--root', sys.argv[1], 'viewer', '--open'])\n"
            "print(json.dumps({'code': code, 'opened': opened, 'ezdxf': 'ezdxf' in sys.modules}))\n")
    p = subprocess.run([sys.executable, "-c", code, str(ws)], capture_output=True, text=True, timeout=60, check=True)
    lines = p.stdout.strip().splitlines()
    printed, result = json.loads(lines[0]), json.loads(lines[-1])
    assert printed == {"ok": True, "viewer": viewer.url, "root": str(ws), "reused": True}
    assert result == {"code": 0, "opened": [viewer.url], "ezdxf": False}


def test_cli_reports_a_busy_port(ws):
    from agentcad.cli import run
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        r, code = run(["--root", str(ws), "viewer", "--port", str(s.getsockname()[1])])
    finally:
        s.close()
    assert code == 2 and r["error"]["code"] == "PORT_IN_USE"


# --- commits are never blocked by the viewer -------------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="POSIX rename never fails on an open target")
def test_store_waits_out_a_reader(tmp_path):
    """The hazard: on Windows, os.replace onto a file another handle has open fails. replace_file retries."""
    from agentcad.store import replace_file
    target, new = tmp_path / "a.dxf", tmp_path / "b.tmp"
    target.write_bytes(b"old")
    new.write_bytes(b"new")
    f = open(target, "rb")
    with pytest.raises(PermissionError):
        os.replace(new, target)
    threading.Timer(0.2, f.close).start()  # a reader that finishes after 0.2 s
    replace_file(new, target)
    assert target.read_bytes() == b"new"
    f2 = open(target, "rb")  # a reader that never lets go: the commit fails after the timeout, as before
    try:
        new.write_bytes(b"newer")
        with pytest.raises(PermissionError):
            replace_file(new, target, timeout=0.1)
    finally:
        f2.close()


def test_commits_succeed_while_the_viewer_reads(rt, ws, blank, workspace):
    """Agents work next to the viewer: hammer the viewer's read paths while the runtime commits 60 times."""
    stop = threading.Event()
    reads, errors = [0], []

    def hammer():
        while not stop.is_set():
            try:
                tl = workspace.timeline(blank)
                workspace.snapshot(blank, None)
                workspace.diff(blank, None)  # every read the page makes, not just the snapshot (review N3)
                workspace.layers(blank, None)
                for r in tl["records"][-3:]:
                    if r.get("version") and r["available"]:
                        workspace.snapshot(blank, r["version"])
                reads[0] += 1
            except Exception as exc:  # noqa: BLE001  the viewer may lose a race; the agent must not
                if "VERSION" not in str(getattr(exc, "code", "")):
                    errors.append(repr(exc))

    threads = [threading.Thread(target=hammer, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        for i in range(60):
            line(rt, blank, [0, i], [100, i])  # ok() fails the test on any commit error
    finally:
        stop.set()
        for t in threads:
            t.join(10)
    assert reads[0] > 20, reads
    assert not errors, errors[:3]


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_a_cached_version_is_not_read_while_its_rename_is_in_flight(rt, ws, blank, workspace, monkeypatch):
    """os.replace (MoveFileEx) still holds a DELETE handle on the file it just renamed; opening the new name then
    fails with a sharing violation. A second reader must not be handed the cached copy before os.replace returns
    (the 1-in-16 failure of the test above)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    line(rt, blank, [0, 0], [100, 0])
    version = sha256_file(ws / blank)
    real_replace, errors, raced = os.replace, [], []

    def read():
        try:
            workspace.layers(blank, version)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def replace(src, dst):
        real_replace(src, dst)
        if Path(dst).parent != workspace.cache or raced:
            return
        h = k32.CreateFileW(str(dst), 0x00010000, 7, None, 3, 0, None)  # DELETE, share all, OPEN_EXISTING
        assert h != wintypes.HANDLE(-1).value, ctypes.get_last_error()
        try:
            t = threading.Thread(target=read)
            raced.append(t)
            t.start()
            t.join(0.5)  # a reader that waits for the copy to be finished is still waiting here
        finally:
            k32.CloseHandle(h)

    monkeypatch.setattr(os, "replace", replace)
    workspace.layers(blank, version)
    raced[0].join(10)
    assert raced and not errors, errors


# --- reachable only from this machine -----------------------------------------------------------------------------

def raw_get(srv: Viewer, route: str, host: str) -> int:
    import http.client
    port = int(srv.url.rstrip("/").rsplit(":", 1)[1])
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("GET", route, skip_host=True)
    c.putheader("Host", host)
    c.endheaders()
    code = c.getresponse().status
    c.close()
    return code


def test_foreign_host_header_is_refused(blank, viewer):
    """DNS rebinding: a page on evil.example resolves its name to 127.0.0.1; its requests say Host: evil.example."""
    port = viewer.url.rstrip("/").rsplit(":", 1)[1]
    assert raw_get(viewer, "/api/drawings", f"evil.example:{port}") == 403
    assert raw_get(viewer, "/", "evil.example") == 403
    assert raw_get(viewer, "/api/drawings", "") == 403
    for h in (f"127.0.0.1:{port}", f"localhost:{port}", "localhost"):
        assert raw_get(viewer, "/api/drawings", h) == 200, h


def test_non_loopback_host_needs_allow_remote(ws):
    from agentcad.cli import run
    from agentcad.errors import AgentCADError
    with pytest.raises(AgentCADError) as e:
        Viewer(Policy(root=ws), host="0.0.0.0", port=0)
    assert e.value.code == "REMOTE_NOT_ALLOWED"
    r, code = run(["--root", str(ws), "viewer", "--host", "0.0.0.0", "--port", "0"])
    assert code == 4 and r["error"]["code"] == "REMOTE_NOT_ALLOWED"


def test_viewer_url_trusts_only_a_loopback_viewer_of_this_root(rt, ws, tmp_path_factory, cache):
    from agentcad.viewer import viewer_url
    info = ws / ".agentcad" / "viewer.json"
    info.parent.mkdir(parents=True, exist_ok=True)
    other = Viewer(Policy(root=tmp_path_factory.mktemp("other-root")), port=0, cache_dir=cache).start()
    mute = socket.socket()  # listens, never answers like a viewer
    mute.bind(("127.0.0.1", 0))
    mute.listen()
    port = mute.getsockname()[1]
    try:
        for url in (f"http://example.com:{port}/", f"http://10.0.0.1:{port}/", f"file://127.0.0.1:{port}/",
                    "http://127.0.0.1/", f"http://127.0.0.1:{port}/",  # not a viewer
                    other.url):  # a viewer, of another root
            info.write_text(json.dumps({"url": url}), "utf-8")
            assert viewer_url(rt.policy, "a.dxf") is None, url
    finally:
        mute.close()
        other.stop()
    mine = Viewer(Policy(root=ws), port=0, cache_dir=cache).start()
    try:
        assert viewer_url(rt.policy, "a.dxf") == mine.url + "#a.dxf"
    finally:
        mine.stop()


def test_viewer_url_probe_leaves_no_traceback(rt, viewer, capfd):
    """The probe is a real request (GET /api/ping): the viewer has nothing to complain about."""
    capfd.readouterr()
    for i in range(3):
        assert ok(rt.create_drawing(f"t{i}.dxf"))["viewer_url"]
    import time
    time.sleep(0.2)
    assert "Traceback" not in capfd.readouterr().err


def test_ipv6_loopback(ws, cache):
    try:
        v = Viewer(Policy(root=ws), host="::1", port=0, cache_dir=cache).start()
    except OSError as exc:  # no IPv6 on this machine
        pytest.skip(f"IPv6 loopback unavailable: {exc}")
    try:
        assert v.url.startswith("http://[::1]:")
        code, r = get_json(v, "/api/ping")
        assert code == 200 and Path(r["root"]) == ws.resolve()
    finally:
        v.stop()


def test_create_drawing_does_not_load_the_http_server(ws):
    import subprocess
    import sys
    code = ("import sys; from agentcad.policy import Policy; from agentcad.service import Runtime; "
            f"assert Runtime(Policy(root={str(ws)!r})).create_drawing('a.dxf')['ok']; "
            "print('http.server' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "False", out.stderr


def test_viewer_serves_the_ui_kit_and_nothing_else(tmp_path):
    import urllib.error
    import urllib.request
    from agentcad.policy import Policy
    from agentcad.viewer import Viewer
    v = Viewer(Policy(root=tmp_path), port=0).start()
    try:
        for name, ctype in (("fluid.css", "text/css"), ("fluid.js", "text/javascript"), ("gallery.html", "text/html"),
                            ("inter-latin-wght-normal.woff2", "font/woff2")):
            with urllib.request.urlopen(v.url + "ui/" + name) as r:
                assert r.status == 200 and r.headers["Content-Type"].startswith(ctype) and r.read()
        for bad in ("../index.html", "..%2Fviewer.py", "%2e%2e/index.html", "nope.css", "NOTICE.exe"):
            try:
                urllib.request.urlopen(v.url + "ui/" + bad)
                raise AssertionError(bad + " was served")
            except urllib.error.HTTPError as e:
                assert e.code == 404, bad
        for bad in ("../index.html", "..%2F..%2Fviewer.py", "%2e%2e/app/index.html", "nope.js", "index.html"):
            try:
                urllib.request.urlopen(v.url + "app/assets/" + bad)
                raise AssertionError(bad + " was served")
            except urllib.error.HTTPError as e:
                assert e.code == 404, bad
    finally:
        v.stop()


# --- adding files from the page, and showing the folder -----------------------------------------------------------

def _post(url, path, body=b"", headers=None):
    import urllib.error
    import urllib.request
    h = {"X-AgentCAD-Viewer": "1", **(headers or {})}
    req = urllib.request.Request(url + path.lstrip("/"), data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def page_viewer(tmp_path, monkeypatch):
    from agentcad import desktop
    from agentcad.policy import Policy
    from agentcad.viewer import Viewer
    opened = []
    monkeypatch.setattr(desktop, "open_folder", lambda p: opened.append(("folder", p)))
    monkeypatch.setattr(desktop, "reveal", lambda p: opened.append(("reveal", p)))
    v = Viewer(Policy(root=tmp_path, read_only=False), port=0).start()
    v.opened = opened
    yield v
    v.stop()


def test_page_adds_files_without_overwriting(page_viewer, tmp_path):
    from urllib.parse import quote
    dxf = (tmp_path / "src.dxf")
    import ezdxf
    ezdxf.new().saveas(dxf)
    data = dxf.read_bytes()
    dxf.unlink()
    code, r = _post(page_viewer.url, "/api/import", data, {"X-AgentCAD-Filename": quote("板 plate.dxf")})
    assert code == 200 and r["path"] == "板 plate.dxf" and r["shown"] and not r["renamed"]
    code, r = _post(page_viewer.url, "/api/import", b"other", {"X-AgentCAD-Filename": quote("板 plate.dxf")})
    assert r["path"] == "板 plate (2).dxf" and r["renamed"]
    assert (tmp_path / "板 plate.dxf").read_bytes() == data  # the first one is untouched
    # a name is only its last part: nothing lands outside the workspace
    for name, want in (("../../evil.dxf", "evil.dxf"), (r"..\..\x\evil2.png", "evil2.png"), ("C:/Windows/w.pdf", "w.pdf"),
                       ("con.dxf", "_con.dxf"), ("a<b>c|d?.PDF", "a_b_c_d_.pdf")):
        code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": quote(name)})
        assert code == 200 and r["path"] == want and (tmp_path / want).is_file(), (name, r)
        assert r["shown"] == want.endswith(".dxf")  # a drawing opens; the rest wait for the assistant
    code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": "part.step"})
    assert code == 200 and r["path"] == "part.step" and r["shown"] and r["kind"] == "part"  # 3D parts open too
    assert not (tmp_path.parent / "evil.dxf").exists()
    for name in ("virus.exe", "notes.docx"):
        code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": name})
        assert code == 400 and r["error"]["code"] == "UNSUPPORTED_FILE", name
    # the page learns where the drawings are and that it may add files; the new drawing is listed
    with __import__("urllib.request").request.urlopen(page_viewer.url + "api/drawings") as resp:
        d = json.loads(resp.read())
    assert d["root"] == str(tmp_path) and d["can_add"] is True and "板 plate.dxf" in [x["path"] for x in d["drawings"]]


def test_only_the_page_itself_may_add_or_open(page_viewer, tmp_path):
    from urllib.parse import quote
    name = {"X-AgentCAD-Filename": quote("a.dxf")}
    # another site: no special header (it cannot send one without a CORS preflight), or a foreign Origin
    code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Viewer": "0", **name})
    assert code == 403 and r["error"]["code"] == "NOT_FROM_THE_PAGE"
    code, _ = _post(page_viewer.url, "/api/import", b"x", {"Origin": "https://evil.example", **name})
    assert code == 403
    code, _ = _post(page_viewer.url, "/api/reveal", b"{}", {"Host": "evil.example"})
    assert code == 403
    assert not (tmp_path / "a.dxf").exists() and not page_viewer.opened
    # the page: the folder, a file in it; nothing outside
    (tmp_path / "in.dxf").write_text("x")
    assert _post(page_viewer.url, "/api/reveal", b"{}")[0] == 200
    assert _post(page_viewer.url, "/api/reveal", json.dumps({"path": "in.dxf"}).encode())[0] == 200
    code, r = _post(page_viewer.url, "/api/reveal", json.dumps({"path": "../../Windows"}).encode())
    assert code == 403 and r["error"]["code"] == "OUTSIDE_WORKSPACE"
    assert page_viewer.opened == [("folder", tmp_path), ("reveal", (tmp_path / "in.dxf").resolve())]


def test_read_only_and_remote_viewers_take_no_files(tmp_path, monkeypatch):
    from agentcad import desktop
    from agentcad.policy import Policy
    from agentcad.viewer import Viewer
    monkeypatch.setattr(desktop, "open_folder", lambda p: None)
    v = Viewer(Policy(root=tmp_path, read_only=True), port=0).start()
    try:
        code, r = _post(v.url, "/api/import", b"x", {"X-AgentCAD-Filename": "a.dxf"})
        assert code == 403 and r["error"]["code"] == "READ_ONLY" and not (tmp_path / "a.dxf").exists()
    finally:
        v.stop()
    v = Viewer(Policy(root=tmp_path, read_only=False), port=0, allow_remote=True).start()
    try:
        assert _post(v.url, "/api/import", b"x", {"X-AgentCAD-Filename": "a.dxf"})[0] == 403
        assert _post(v.url, "/api/reveal", b"{}")[0] == 403
    finally:
        v.stop()


def test_a_refused_request_still_gets_its_answer(tmp_path):
    """A refusal used to close with the body unread: Windows then reset the connection and the client could lose the
    403 (WinError 10053). Here the body arrives after the answer, which made that happen every time."""
    import select
    import socket
    import time
    from urllib.parse import urlparse
    from agentcad.policy import Policy
    from agentcad.viewer import Viewer
    v = Viewer(Policy(root=tmp_path, read_only=True), port=0).start()
    u = urlparse(v.url)
    head = b"POST /api/import HTTP/1.1\r\nHost: localhost\r\nX-AgentCAD-Viewer: 1\r\nX-AgentCAD-Filename: a.dxf\r\n"

    def ask(length, body=None):
        with socket.create_connection((u.hostname, u.port), timeout=10) as s:
            s.sendall(head + b"Content-Length: %d\r\n\r\n" % length)
            assert select.select([s], [], [], 10)[0]  # answered before the body came
            if body is not None:
                time.sleep(0.3)
                s.sendall(body)
            data = b""
            while chunk := s.recv(65536):
                data += chunk
            return data
    try:
        data = ask(1, b"x")
        assert data.startswith(b"HTTP/1.1 403") and b'"READ_ONLY"' in data
        # a large body is never read: the answer comes and the connection closes without waiting for it
        t = time.monotonic()
        assert ask(10 ** 9).startswith(b"HTTP/1.1 403") and time.monotonic() - t < 1.5
    finally:
        v.stop()


def test_a_large_file_is_refused_before_it_is_read(page_viewer, tmp_path, monkeypatch):
    from agentcad import viewer
    monkeypatch.setattr(viewer, "MAX_IMPORT", 10)
    code, r = _post(page_viewer.url, "/api/import", b"x" * 11, {"X-AgentCAD-Filename": "big.dxf"})
    assert code == 413 and r["error"]["code"] == "FILE_TOO_LARGE" and not (tmp_path / "big.dxf").exists()


def test_import_needs_a_sane_length_and_the_page_is_not_framed(page_viewer, tmp_path):
    import http.client
    from urllib.parse import quote, urlparse
    u = urlparse(page_viewer.url)

    def raw(headers, body=b""):
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
        c.putrequest("POST", "/api/import")
        for k, v in {"X-AgentCAD-Viewer": "1", "X-AgentCAD-Filename": "len.dxf", **headers}.items():
            c.putheader(k, v)
        c.endheaders()
        if body:
            c.send(body)
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    code, r = raw({"Transfer-Encoding": "chunked"}, b"1\r\nx\r\n0\r\n\r\n")
    assert code == 411 and r["error"]["code"] == "LENGTH_REQUIRED"
    code, r = raw({"Content-Length": "-1"}, b"xyz")
    assert code == 400
    assert not (tmp_path / "len.dxf").exists()
    # device names count before the first dot
    for name in ("nul.x.dxf", "CONIN$.dxf", "com¹.png"):
        code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": quote(name)})
        assert code == 200 and r["path"].startswith("_"), (name, r)
    with urllib.request.urlopen(page_viewer.url) as resp:
        assert resp.headers["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_a_refused_body_of_unknown_size_does_not_reset_the_answer(page_viewer):
    """Closing with the body unread made Windows reset the connection, and 1 in ~40 refusals reached the client as
    WinError 10053 instead of the answer (this file's length test failed now and then)."""
    import http.client
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlparse
    u = urlparse(page_viewer.url)

    def refused(headers, body):
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
        c.putrequest("POST", "/api/import")
        for k, v in {"X-AgentCAD-Viewer": "1", "X-AgentCAD-Filename": "len.dxf", **headers}.items():
            c.putheader(k, v)
        c.endheaders()
        c.send(body)
        try:
            return c.getresponse().status
        finally:
            c.close()

    reqs = [({"Transfer-Encoding": "chunked"}, b"1\r\nx\r\n0\r\n\r\n", 411), ({"Content-Length": "-1"}, b"xyz", 400)]
    with ThreadPoolExecutor(16) as ex:
        got = list(ex.map(lambda i: refused(*reqs[i % 2][:2]), range(300)))
    assert got == [reqs[i % 2][2] for i in range(300)]


# --- 3D parts the agent's own code saves ----------------------------------------------------------------------

def _settle(path: Path) -> None:
    """Make a just-written file look as if its writer finished a while ago (SETTLE)."""
    t = path.stat().st_mtime - 5
    os.utime(path, (t, t))


def test_saved_3d_files_become_versions(ws, cache):
    """An agent saves its own CadQuery/FreeCAD result over the same file; each settled save is one version, listed
    in the timeline with the version before it, and reported as a 'save' activity."""
    from agentcad import progress
    v = Viewer(Policy(root=ws, read_only=False), port=0, interval=0.05, cache_dir=cache)
    v.feed.rescan = 0  # look for new files on every poll
    part = ws / "arm.step"
    part.write_bytes(b"ISO-10303-21; first")
    _settle(part)
    v.feed.poll()
    assert [r["tool"] for r in v.ws.timeline("arm.step")["records"]] == ["save"]
    v.feed.poll()  # unchanged: nothing new
    assert len(v.ws.timeline("arm.step")["records"]) == 1
    part.write_bytes(b"ISO-10303-21; second")  # still being written: not yet a version
    v.feed.poll()
    assert len(v.ws.timeline("arm.step")["records"]) == 1
    _settle(part)
    v.feed.poll()
    recs = v.ws.timeline("arm.step")["records"]
    assert [r["seq"] for r in recs] == [1, 2] and recs[1]["before"] == recs[0]["version"]
    assert all(r["available"] for r in recs) and recs[1]["version"] == sha256_file(part)
    assert v.ws.snapshot("arm.step", recs[0]["version"])[1].read_bytes() == b"ISO-10303-21; first"
    log = [json.loads(x) for x in progress.log_path(v.ws.policy).read_text("utf-8").splitlines()]
    assert [(e["tool"], e["drawing"], e["state"]) for e in log] == [("save", "arm.step", "done")] * 2
    # the files listed include the part, as a part; the part itself was never written by the viewer
    assert {"arm.step"} <= set(v.ws.list_drawings()) and part.read_bytes() == b"ISO-10303-21; second"
    # back to the first content: a third version, pointing at the copy already stored (no new checkpoint)
    part.write_bytes(b"ISO-10303-21; first")
    _settle(part)
    v.feed.poll()
    recs = v.ws.timeline("arm.step")["records"]
    assert len(recs) == 3 and recs[2]["version"] == recs[0]["version"] and recs[2]["before"] == recs[1]["version"]
    assert len(v.ws.store("arm.step").list_checkpoints()) == 2
    v.httpd.server_close()


def test_parts_already_there_are_recorded_after_start(ws, cache):
    """What exists when the viewer starts is recorded by the feed's later polls, not while it starts."""
    part = ws / "old.stl"
    part.write_bytes(b"solid old")
    _settle(part)
    v = Viewer(Policy(root=ws, read_only=False), port=0, interval=0.05, cache_dir=cache)
    assert v.ws.timeline("old.stl")["records"] == []
    v.feed.poll()
    assert [r["tool"] for r in v.ws.timeline("old.stl")["records"]] == ["save"]
    v.feed.poll()  # the page hears that only the history moved, so it does not jump there
    assert [(e["drawing"], e["kind"], e.get("history")) for e in v.feed.since(0)] == [("old.stl", "changed", True)]
    # not announced: a page following the assistant would otherwise jump to every old part
    from agentcad import progress
    log = progress.log_path(v.ws.policy)
    assert not log.is_file() or not [x for x in log.read_text("utf-8").splitlines() if '"save"' in x]
    part.write_bytes(b"solid newer")  # a real save after the start is announced
    _settle(part)
    v.feed.poll()
    assert sum('"save"' in x for x in log.read_text("utf-8").splitlines()) == 1
    v.httpd.server_close()


def test_read_only_viewer_records_no_versions(ws, cache):
    v = Viewer(Policy(root=ws, read_only=True), port=0, interval=0.05, cache_dir=cache)
    v.feed.rescan = 0
    part = ws / "arm.stl"
    part.write_bytes(b"solid x")
    _settle(part)
    v.feed.poll()
    assert v.ws.timeline("arm.stl")["records"] == [] and not (ws / ".agentcad" / "drawings").exists()
    v.httpd.server_close()


needs_freecad = pytest.mark.skipif(not __import__("agentcad.backends.freecad", fromlist=["x"]).available(),
                                   reason="FreeCAD not installed (set AGENTCAD_FREECAD)")


@needs_freecad
def test_3d_part_mesh_thumbnail_and_change(ws, cache):
    """A STEP the agent saved, then a changed one: the page gets triangles, a thumbnail, and what changed."""
    import subprocess
    from agentcad.backends import freecad
    cmd, extra = freecad.require()
    script = ws / "make.py"
    script.write_text(  # a stand-in for the agent's own code; by environment: freecadcmd passes no arguments
        "import os, sys\n"
        "[sys.path.insert(0, p) for p in os.environ.get('AGENTCAD_FREECAD_LIB', '').split(os.pathsep) if p]\n"
        "import FreeCAD, Part\n"
        "box = Part.makeBox(40, 20, 10)\n"
        "cyl = Part.makeCylinder(5, 30, FreeCAD.Vector(20, 10, 0))\n"
        "(box.fuse(cyl) if os.environ['KIND'] == 'boss' else box.cut(cyl)).exportStep(os.environ['OUT'])\n",
        "utf-8")
    part = ws / "arm.step"
    v = Viewer(Policy(root=ws, read_only=False), port=0, interval=0.05, cache_dir=cache)
    v.feed.rescan = 0
    v.start()
    try:
        for kind in ("boss", "hole"):
            subprocess.run(cmd + [str(script)], env={**os.environ, **extra, "OUT": str(part), "KIND": kind},
                           check=True, capture_output=True, timeout=120)
            _settle(part)
            v.feed.poll()
        code, tl = get_json(v, "/api/timeline", path="arm.step")
        assert code == 200 and tl["kind"] == "part" and len(tl["records"]) == 2
        code, mesh = get_json(v, "/api/mesh", path="arm.step")
        assert code == 200 and mesh["indices"] and mesh["edges"] and not mesh["missing_faces"]
        code, ctype, png = get(v, "/api/thumb", path="arm.step")
        assert code == 200 and ctype == "image/png" and png.startswith(b"\x89PNG")
        code, d = get_json(v, "/api/diff", path="arm.step", v=tl["current"])
        assert code == 200 and d["shape"]["size"] == {"old": [40.0, 20.0, 30.0], "new": [40.0, 20.0, 10.0]}
    finally:
        v.stop()


@needs_freecad
def test_seams_match_the_per_edge_check_without_asking_it_about_shared_edges(tmp_path):
    """_is_seam searches every face for each edge (a 9 MB STEP with 2181 faces took 50 s of a 55 s mesh); _seams
    gives the same answers and asks it only about edges fewer than two faces share."""
    import subprocess
    from agentcad.backends import freecad
    cmd, extra = freecad.require()
    script = tmp_path / "seams.py"
    script.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['VIEW_DIR'])\n"
        "import _fc_view as v\n"
        "import FreeCAD, Part\n"
        "plate = Part.makeBox(100, 100, 4)\n"
        "for i in range(8):\n"
        "    for j in range(8):\n"
        "        plate = plate.cut(Part.makeCylinder(2, 4, FreeCAD.Vector(8 + 12 * i, 8 + 12 * j, 0)))\n"
        "shapes = {'cylinder': Part.makeCylinder(5, 10), 'cone': Part.makeCone(5, 2, 8), 'sphere': Part.makeSphere(4),\n"
        "          'open_face': Part.makeCylinder(5, 10).Faces[0], 'plate': plate}\n"
        "asked, check = [], v._is_seam\n"
        "v._is_seam = lambda s, e: asked.append(1) or check(s, e)\n"
        "out = {}\n"
        "for name, sh in shapes.items():\n"
        "    asked.clear()\n"
        "    new = v._seams(sh)\n"
        "    out[name] = {'same': new == [not e.Degenerated and check(sh, e) for e in sh.Edges],\n"
        "                 'seams': sum(new), 'edges': len(sh.Edges), 'asked': len(asked)}\n"
        "open(os.environ['OUT'], 'w').write(json.dumps(out))\n", "utf-8")
    out = tmp_path / "seams.json"
    view_dir = Path(freecad.__file__).parent
    subprocess.run(cmd + [str(script)], env={**os.environ, **extra, "VIEW_DIR": str(view_dir), "OUT": str(out)},
                   check=True, capture_output=True, timeout=120)
    r = json.loads(out.read_text("utf-8"))
    assert all(c["same"] for c in r.values()), r
    assert [r[k]["seams"] for k in ("cylinder", "cone", "sphere", "open_face")] == [1, 1, 0, 1]
    assert r["plate"]["seams"] == 64 and r["plate"]["asked"] == 64 and r["plate"]["edges"] > 3 * 64, r["plate"]


def test_freecad_does_not_expose_an_incomplete_cache_output(tmp_path, monkeypatch):
    from agentcad.backends import freecad
    monkeypatch.setattr(freecad, "require", lambda: (["freecad"], {}))
    monkeypatch.setattr(freecad.tempfile, "gettempdir", lambda: str(tmp_path))
    final = tmp_path / "view.mesh.json"

    class Process:
        def __init__(self, args, cwd, **kwargs):
            job = json.loads((cwd / "job.json").read_text("utf-8"))
            Path(job["output"]).write_bytes(b'{"points":[]}')
            (cwd / "result.json").write_text('{"ok": true}', "utf-8")

        def wait(self, timeout):
            return 0

    def copy_in_parts(source, destination):
        with Path(destination).open("wb") as stream:
            stream.write(b'{"points":')
            stream.flush()
            assert not final.exists()
            stream.write(Path(source).read_bytes()[10:])

    monkeypatch.setattr(freecad.subprocess, "Popen", Process)
    monkeypatch.setattr(freecad.shutil, "copyfile", copy_in_parts)
    assert freecad.run({"action": "mesh"}, outputs={"output": final})["ok"]
    assert json.loads(final.read_bytes()) == {"points": []}


def test_freecad_location_is_remembered_for_the_desktop_viewer(tmp_path, monkeypatch):
    """The agent apps start AgentCAD with AGENTCAD_FREECAD; the viewer the desktop icon opens has no such setting,
    so the location is kept per user (never in a workspace) and used from there, only if it is a FreeCAD folder."""
    from agentcad.backends import freecad
    fc = tmp_path / "FreeCAD"
    (fc / "bin").mkdir(parents=True)
    (fc / "bin" / ("freecadcmd.exe" if os.name == "nt" else "freecadcmd")).write_text("", "utf-8")
    memo = tmp_path / "user" / "AgentCAD" / "freecad.txt"
    monkeypatch.setattr(freecad, "memo_path", lambda: memo)
    monkeypatch.delenv("FREECAD_LIB", raising=False)
    monkeypatch.setenv("AGENTCAD_FREECAD", str(fc))
    freecad.remember()
    assert memo.read_text("utf-8") == str(fc)
    monkeypatch.delenv("AGENTCAD_FREECAD")
    monkeypatch.setattr(freecad, "find_freecad", lambda: None)  # as on a computer where it is not installed normally
    freecad.recall()
    assert os.environ["AGENTCAD_FREECAD"] == str(fc)
    # a remembered program file, a folder without FreeCAD, a relative or network path is not used
    evil = tmp_path / "evil.bat"
    evil.write_text("echo hi", "utf-8")
    for bad in (str(evil), str(tmp_path), "FreeCAD", "//server/share/FreeCAD"):
        monkeypatch.delenv("AGENTCAD_FREECAD", raising=False)
        memo.write_text(bad, "utf-8")
        freecad.recall()
        assert "AGENTCAD_FREECAD" not in os.environ, bad


def test_a_workspace_cannot_choose_the_program_the_viewer_runs(ws, cache, monkeypatch):
    """A freecad.txt inside a workspace (a shared folder, a cloned repository) is ignored."""
    from agentcad.backends import freecad
    monkeypatch.setattr(freecad, "memo_path", lambda: ws.parent / "no-memo" / "freecad.txt")
    monkeypatch.delenv("AGENTCAD_FREECAD", raising=False)
    monkeypatch.delenv("FREECAD_LIB", raising=False)
    evil = ws / "evil.bat"
    evil.write_text("echo hi > pwned.txt", "utf-8")
    (ws / ".agentcad").mkdir(exist_ok=True)
    (ws / ".agentcad" / "freecad.txt").write_text(str(evil), "utf-8")
    Workspace(Policy(root=ws, read_only=True), cache)._find_freecad()
    assert os.environ.get("AGENTCAD_FREECAD") != str(evil)


def test_a_freecadcmd_in_the_current_folder_is_not_run(tmp_path, monkeypatch):
    """shutil.which looks in the current folder first on Windows (Python <= 3.11): a project folder that ships a
    'freecadcmd' must not be taken for FreeCAD."""
    from agentcad.backends import freecad
    fake = tmp_path / ("freecadcmd.exe" if os.name == "nt" else "freecadcmd")
    fake.write_text("", "utf-8")
    fake.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTCAD_FREECAD", raising=False)
    monkeypatch.delenv("FREECAD_LIB", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", str(tmp_path)]))  # empty, relative and the current folder
    assert freecad._on_path("freecadcmd") is None
    hit = freecad.find_freecad()
    assert hit is None or Path(hit[0][0]).parent != tmp_path


def test_install_folder_search_is_never_relative(tmp_path, monkeypatch):
    """Without LOCALAPPDATA the per-user install pattern would stay '%LOCALAPPDATA%\\Programs\\FreeCAD *' and
    match folders under the current one."""
    from agentcad.backends import freecad
    planted = tmp_path / "%LOCALAPPDATA%" / "Programs" / "FreeCAD 9" / "bin"
    planted.mkdir(parents=True)
    (planted / ("freecadcmd.exe" if os.name == "nt" else "freecadcmd")).write_text("", "utf-8")
    monkeypatch.chdir(tmp_path)
    for var in ("LOCALAPPDATA", "AGENTCAD_FREECAD", "FREECAD_LIB"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", "")
    hit = freecad.find_freecad()
    assert hit is None or Path(hit[0][0]).is_absolute() and tmp_path not in Path(hit[0][0]).resolve().parents


def test_viewer_cache_lives_with_the_workspace(tmp_path):
    """Renders and version copies go to <root>/.agentcad/viewer-cache (the workspace is where the user keeps their
    files; the temp folder is on the system drive), except for a --read-only viewer."""
    from agentcad.viewer import CACHE_DIR, _temp_cache
    root = tmp_path / "ws"
    root.mkdir()
    v = Viewer(Policy(root=root, read_only=False), port=0)
    assert v.ws.cache == root / ".agentcad" / CACHE_DIR and v.ws.cache.is_dir()
    v.httpd.server_close()
    ro = Viewer(Policy(root=root, read_only=True), port=0)
    assert ro.ws.cache == _temp_cache(root)
    ro.httpd.server_close()


def test_thumbnails_have_their_own_freecad_lane(ws, cache, monkeypatch):
    """The part on screen never waits behind the file list's thumbnails."""
    from agentcad import viewer as viewer_mod
    from agentcad.backends import freecad
    held: list[str] = []
    lanes = []

    class Lane:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            held.append(self.name)

        def __exit__(self, *exc):
            held.remove(self.name)

    monkeypatch.setattr(viewer_mod, "FREECAD_JOBS", {"view": Lane("view"), "thumb": Lane("thumb")})
    monkeypatch.setattr(freecad, "run", lambda job, inputs=None, outputs=None: (
        lanes.append(list(held)), [Path(o).write_bytes(b"x") for o in (outputs or {}).values()],
        {"ok": True, "summary": {}})[-1])
    part = ws / "p.stl"
    part.write_bytes(b"solid p")
    w = Workspace(Policy(root=ws, read_only=True), cache)
    monkeypatch.setattr(w, "_find_freecad", lambda: None)
    w.thumb("p.stl", None)
    w.mesh("p.stl", None)
    assert lanes == [["thumb"], ["view"]]


def test_writable_viewer_migrates_nested_part_history(ws, cache):
    name = "parts/arm.step"
    part = ws / name
    part.parent.mkdir()
    part.write_bytes(b"first version")
    _settle(part)
    viewer = Viewer(Policy(root=ws), port=0, cache_dir=cache)
    try:
        w = viewer.ws
        assert w.policy.read_only and w.record
        assert w.record_save(name)
        state = w.store(name)
        legacy = ws / ".agentcad" / "drawings" / "parts__arm.step"
        legacy.parent.mkdir(parents=True)
        state.dir.rename(legacy)
        part.write_bytes(b"second version")
        _settle(part)
        assert w.record_save(name)
        assert state.dir.is_dir() and len(w.timeline(name)["records"]) == 2
        assert len((legacy / "journal.jsonl").read_text("utf-8").splitlines()) == 1
    finally:
        viewer.httpd.server_close()


def test_a_part_changed_after_start_is_announced(ws, cache):
    """A part the viewer found at start, then saved again by the agent before its first version was recorded, is a
    real save: announced, and its event is not marked as history only."""
    from agentcad import progress
    part = ws / "found.step"
    part.write_bytes(b"ISO-10303-21; at start")
    _settle(part)
    v = Viewer(Policy(root=ws, read_only=False), port=0, interval=0.05, cache_dir=cache)
    v.feed.rescan = 0
    part.write_bytes(b"ISO-10303-21; saved again")
    _settle(part)
    v.feed.poll()
    assert [(e["kind"], e.get("history")) for e in v.feed.since(0)] == [("changed", None)]
    log = progress.log_path(v.ws.policy).read_text("utf-8").splitlines()
    assert sum('"save"' in x for x in log) == 1
    v.httpd.server_close()


def test_unwritable_workspace_cache_falls_back_to_temp(tmp_path, monkeypatch):
    from agentcad import viewer as viewer_mod
    root = tmp_path / "ws"
    root.mkdir()
    real = Path.write_bytes
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: (_ for _ in ()).throw(PermissionError("read-only"))
                        if ".probe-" in self.name else real(self, data))
    assert viewer_mod._workspace_cache(root) is None
    v = Viewer(Policy(root=root, read_only=False), port=0)
    assert v.ws.cache == viewer_mod._temp_cache(root)
    v.httpd.server_close()
