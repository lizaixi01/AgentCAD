"""Live viewer (viewer.py): change feed, versions, render endpoints, SSE, and that it never writes the workspace."""
from __future__ import annotations

import json
import math
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.store import sha256_file
from agentcad.viewer import COLORS, ChangeFeed, Viewer, Workspace
from conftest import ok

needs_freecad = pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed (set AGENTCAD_FREECAD)")


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
    assert code == 200 and "text/html" in ctype and b"EventSource" in body
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


# --- 3D parts ---------------------------------------------------------------------------------------------------

PLATE = [
    {"op": "set_parameters", "params": {"width": 80, "depth": 50, "thickness": 6}},
    {"op": "add_sketch", "plane": "XY",
     "shapes": [{"type": "rectangle", "corner": [0, 0], "width": "=Params.width", "height": "=Params.depth"}]},
    {"op": "pad", "sketch": "$1", "length": "=Params.thickness", "tag": "base"},
]


@needs_freecad
def test_part_mesh_png_and_diff(rt, ws, viewer):
    ok(rt.apply_operations("plate.FCStd", PLATE, create={"units": "mm"}))
    ok(rt.apply_operations("plate.FCStd", [{"op": "set_parameters", "params": {"width": 120}}]))
    before = files_state(ws)
    code, r = get_json(viewer, "/api/drawings")
    assert {"path": "plate.FCStd", "kind": "part"} in r["drawings"]
    code, m = get_json(viewer, "/api/mesh", path="plate.FCStd")
    assert code == 200 and len(m["indices"]) % 3 == 0 and m["indices"] and len(m["edges"]) == 12
    xs = m["positions"][0::3]
    assert max(xs) - min(xs) == pytest.approx(120, abs=1e-3)
    tl = get_json(viewer, "/api/timeline", path="plate.FCStd")[1]
    assert tl["kind"] == "part"
    first = [x for x in tl["records"] if x.get("version")][0]["version"]
    old = get_json(viewer, "/api/mesh", path="plate.FCStd", v=first)[1]
    xs = old["positions"][0::3]
    assert max(xs) - min(xs) == pytest.approx(80, abs=1e-3)
    code, d = get_json(viewer, "/api/diff", path="plate.FCStd")
    assert code == 200 and d["parameters"]["width"] == {"old": 80, "new": 120}
    code, ctype, png = get(viewer, "/api/png", path="plate.FCStd")
    assert code == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert files_state(ws) == before


@needs_freecad
def test_part_mesh_covers_every_face(rt, viewer):
    """The viewer once lost one filleted corner of a phone body (Shape.tessellate dropped a face it failed to mesh):
    the triangles must add up to the whole surface of a part with rounded corners."""
    w, h, r, t = 78.0, 160.0, 12.0, 8.0
    b = math.tan(math.radians(22.5))  # bulge of a 90-degree arc
    x0, x1, y0, y1 = -w / 2, w / 2, -h / 2, h / 2
    outline = [[x0 + r, y0], [x1 - r, y0, b], [x1, y0 + r], [x1, y1 - r, b],
               [x1 - r, y1], [x0 + r, y1, b], [x0, y1 - r], [x0, y0 + r, b]]
    ok(rt.apply_operations("phone.FCStd", [{"op": "add_sketch", "plane": "XY",
                                            "shapes": [{"type": "polygon", "points": outline}]},
                                           {"op": "pad", "sketch": "$0", "length": t}], create={"units": "mm"}))
    code, m = get_json(viewer, "/api/mesh", path="phone.FCStd")
    assert code == 200
    p, ix = m["positions"], m["indices"]
    area = 0.0
    for i in range(0, len(ix), 3):
        a, c, d = (p[3 * ix[i + k]:3 * ix[i + k] + 3] for k in range(3))
        u, v = [c[j] - a[j] for j in range(3)], [d[j] - a[j] for j in range(3)]
        area += math.hypot(u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]) / 2
    face = w * h - (4 - math.pi) * r * r
    side = 2 * (w + h) - 8 * r + 2 * math.pi * r
    assert area == pytest.approx(2 * face + side * t, rel=2e-3)


TESSELLATE_STUBS = r'''
import importlib.util, json
spec = importlib.util.spec_from_file_location("fc_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class Face:
    """first: triangles of the first meshing; again: of a copy meshed from scratch"""
    def __init__(self, first, again):
        self.first, self.again, self.calls = first, again, []
    def tessellate(self, d):
        self.calls.append(d)
        return [f"p{i}" for i in range(3 * len(self.first))], self.first
    def copy(self):
        return Face(self.again, self.again)

class Shape:
    def __init__(self, faces):
        self.Faces = faces
    def tessellate(self, d):
        return [], []

ok, dropped, lost = Face([(0, 1, 2)], []), Face([], [(0, 1, 2), (2, 1, 0)]), Face([], [])
pts, tris, missing = runner.tessellate(Shape([ok, dropped, lost]), 0.4)
json.dump({"points": len(pts), "tris": tris, "missing": missing}, open(OUT, "w"))
'''


@needs_freecad
def test_tessellate_meshes_a_dropped_face_again(tmp_path):
    """A face Shape.tessellate left without triangles is meshed again on its own; one that still has none is named."""
    import subprocess
    cmd, env = freecad.find_freecad()
    out = tmp_path / "out.json"
    script = tmp_path / "stubs.py"
    script.write_text(f"RUNNER = {str(freecad.RUNNER)!r}\nOUT = {str(out)!r}\n" + TESSELLATE_STUBS, "utf-8")
    env = {**os.environ, **env}
    env.pop("AGENTCAD_FC_JOB", None)
    p = subprocess.run(cmd + [str(script)], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert out.is_file(), f"the FreeCAD script failed (exit {p.returncode}):\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}"
    r = json.loads(out.read_text("utf-8"))
    assert r["missing"] == ["Face3"]
    assert r["points"] == 3 + 6  # Face1's points, then the re-meshed Face2's
    assert r["tris"] == [[0, 1, 2], [3, 4, 5], [5, 4, 3]]  # Face2's indices shifted past Face1's points


@needs_freecad
def test_part_mesh_reports_no_missing_faces(rt, viewer):
    ok(rt.apply_operations("plate.FCStd", PLATE, create={"units": "mm"}))
    code, m = get_json(viewer, "/api/mesh", path="plate.FCStd")
    assert code == 200 and m["missing_faces"] == []


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


@needs_freecad
@pytest.mark.parametrize("extra", [
    {"op": "primitive", "kind": "sphere", "dims": {"radius": 10}, "position": [0, 0, 40]},
    {"op": "primitive", "kind": "cone", "dims": {"radius1": 6, "radius2": 0, "height": 12}, "position": [0, 0, 40]},
])
def test_mesh_skips_degenerate_edges(rt, workspace, extra):
    """A sphere's or cone's pole is an edge without a curve: the viewer's mesh leaves it out instead of failing."""
    ok(rt.create_drawing("knob.FCStd"))
    ok(rt.apply_operations("knob.FCStd", [
        {"op": "primitive", "kind": "cylinder", "dims": {"radius": 3, "height": 40}}, extra]))
    m = json.loads(workspace.mesh("knob.FCStd", None).read_text("utf-8"))
    assert m["indices"] and all(len(e) >= 6 for e in m["edges"])


def test_page_shows_only_the_layer_for_the_file_kind():
    """The transparent 3D layer used to stay on top of a 2D drawing and took every wheel, drag and double-click."""
    from agentcad.viewer import STATIC
    page = (STATIC / "index.html").read_text("utf-8")
    assert '$("stage").hidden = isPart(S.path); $("three").hidden = !isPart(S.path);' in page
    assert '$("three").hidden = false' not in page


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
                       ("con.dxf", "_con.dxf"), ("a<b>c|d?.STEP", "a_b_c_d_.step")):
        code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": quote(name)})
        assert code == 200 and r["path"] == want and (tmp_path / want).is_file(), (name, r)
        assert r["shown"] == want.endswith(".dxf")  # a drawing opens; the rest wait for the assistant
    assert not (tmp_path.parent / "evil.dxf").exists()
    code, r = _post(page_viewer.url, "/api/import", b"x", {"X-AgentCAD-Filename": "virus.exe"})
    assert code == 400 and r["error"]["code"] == "UNSUPPORTED_FILE"
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
