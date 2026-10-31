"""Test Q (setup wizard): ``agentcad setup --gui`` serves a local page that runs ``install.setup`` and reports each
step. Configs live in a temp home folder, as in test_q_install."""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from agentcad import install
from agentcad.setup_gui import Wizard


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    for k, v in {"HOME": h, "USERPROFILE": h, "APPDATA": h / "AppData" / "Roaming",
                 "LOCALAPPDATA": h / "AppData" / "Local", "XDG_CONFIG_HOME": h / ".config"}.items():
        monkeypatch.setenv(k, str(v))
    for k in ("AGENTCAD_ROOT", "CODEX_HOME"):
        monkeypatch.delenv(k, raising=False)
    real_which = install.shutil.which
    monkeypatch.setattr(install.shutil, "which",
                        lambda name, *a, **k: None if name in ("claude", "codex", "cursor") else real_which(name, *a, **k))
    assert Path.home() == h
    return h


class FakeRunner:
    """Stands in for PowerShell (the Windows desktop shortcut), so no test touches the real desktop."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "False\nC:/fake/Desktop/AgentCAD.lnk\n", "")


@pytest.fixture
def wizard(home):
    w = Wizard(launcher="python", runner=FakeRunner()).start_background()
    yield w
    w.stop()


def _call(w: Wizard, method: str, path: str, body=None, token: str | None = None, host: str | None = None):
    u = urlparse(w.url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    headers = {"X-AgentCAD-Token": w.token if token is None else token}
    if host:
        headers["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, (json.loads(raw) if r.getheader("Content-Type", "").startswith("application/json") else raw)


def _wait(w: Wizard) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        _, st = _call(w, "GET", "/api/state")
        if st["phase"] in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("setup did not finish")


def test_page_and_info(wizard, home):
    code, page = _call(wizard, "GET", "/")
    assert code == 200 and b"AgentCAD" in page and b"/api/start" in page
    code, info = _call(wizard, "GET", "/api/info")
    assert code == 200
    assert info["workspace"] == str(home / "AgentCAD")
    assert [a["id"] for a in info["apps"]] == list(install.CLIENTS)
    assert all(a["found"] is False for a in info["apps"])  # nothing installed in the fake home


def test_api_needs_token_and_localhost(wizard):
    assert _call(wizard, "GET", "/api/info", token="")[0] == 403
    assert _call(wizard, "POST", "/api/start", {"clients": ["cursor"]}, token="wrong")[0] == 403
    code, out = _call(wizard, "GET", "/api/info", host="evil.example:80")
    assert code == 403 and out["error"]["code"] == "HOST_NOT_ALLOWED"
    assert wizard.snapshot()["phase"] == "ready"  # nothing was started


def test_setup_runs_and_reports_each_step(wizard, home):
    code, out = _call(wizard, "POST", "/api/start", {"clients": ["cursor", "codex"]})
    assert code == 200 and out["ok"], out
    st = _wait(wizard)
    assert st["phase"] == "done", st
    assert [s["id"] for s in st["steps"]] == ["workspace", "freecad", "autocad", "cursor", "codex",
                                                 "shortcut"]
    assert all(s["state"] == "done" for s in st["steps"])
    assert st["steps"][0]["info"]["path"] == str(home / "AgentCAD")
    assert {c["client"]: c["status"] for c in st["result"]["clients"]} == {"cursor": "added", "codex": "added"}
    assert "server" not in st["result"]  # the command line is not shown on the page
    cursor = json.loads((home / ".cursor" / "mcp.json").read_text("utf-8"))
    assert cursor["mcpServers"]["agentcad"]["env"]["AGENTCAD_ROOT"] == (home / "AgentCAD").as_posix()
    assert "[mcp_servers.agentcad]" in (home / ".codex" / "config.toml").read_text("utf-8")
    assert (home / "AgentCAD").is_dir()

    _call(wizard, "POST", "/api/start", {"clients": ["cursor"]})  # running it again is safe
    st = _wait(wizard)
    assert st["phase"] == "done" and st["result"]["clients"][0]["status"] == "unchanged"


def test_a_broken_config_is_reported_not_overwritten(wizard, home):
    bad = home / ".cursor" / "mcp.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json", "utf-8")
    _call(wizard, "POST", "/api/start", {"clients": ["cursor"]})
    st = _wait(wizard)
    assert st["phase"] == "error"
    step = st["steps"][-1]
    step = next(s for s in st["steps"] if s["id"] == "cursor")
    assert step["state"] == "error" and "not valid JSON" in step["info"]["message"]
    assert step["info"]["code"] == "BAD_CONFIG"  # the page turns the code into a plain sentence
    assert bad.read_text("utf-8") == "{not json"


def test_dry_run_writes_nothing(home):
    w = Wizard(launcher="python", dry_run=True, runner=FakeRunner()).start_background()
    try:
        assert _call(w, "GET", "/api/info")[1]["dry_run"] is True
        _call(w, "POST", "/api/start", {"clients": ["cursor"]})
        st = _wait(w)
        assert st["phase"] == "done" and st["result"]["clients"][0]["status"] == "would be added"
        assert _call(w, "POST", "/api/open-folder", {})[1]["error"]["code"] == "NO_FOLDER"
        assert not (home / ".cursor").exists() and not (home / "AgentCAD").exists()
    finally:
        w.stop()


def test_bad_requests(wizard):
    assert _call(wizard, "POST", "/api/start", {"clients": []})[1]["error"]["code"] == "NO_APP"
    assert _call(wizard, "POST", "/api/start", {"clients": ["notepad"]})[1]["error"]["code"] == "NO_APP"
    assert _call(wizard, "GET", "/api/nope")[0] == 404
    assert _call(wizard, "POST", "/api/quit", {})[1]["ok"]
    assert wizard.done.wait(5)


def test_setup_progress_callback(home):
    seen = []
    install.setup(["cursor"], launcher="python", progress=lambda step, state, info: seen.append((step, state)))
    assert seen == [("workspace", "run"), ("workspace", "done"), ("freecad", "run"), ("freecad", "done"),
                    ("autocad", "run"), ("autocad", "done"), ("cursor", "run"), ("cursor", "done")]


def test_archive_install_keeps_its_source(monkeypatch):
    """Installed from GitHub's .zip (the double-click installers): the apps start AgentCAD from the same .zip, so
    they need no git."""
    url = "https://github.com/lizaixi01/AgentCAD/archive/refs/heads/main.zip"

    class Dist:
        version = "0.1.0"

        def read_text(self, name):
            return json.dumps({"url": url, "archive_info": {}}) if name == "direct_url.json" else None

    from importlib import metadata
    monkeypatch.setattr(metadata, "distribution", lambda name: Dist())
    assert install.install_info()["source"] == url


def test_doctor_page(wizard, home):
    code, r = _call(wizard, "GET", "/api/doctor")
    assert code == 200 and "self_cmd" not in r
    names = {c["name"] for c in r["checks"]}
    assert {"Python", "AgentCAD", "Workspace", "FreeCAD", "Cursor config"} <= names
    assert next(c for c in r["checks"] if c["name"] == "Workspace")["status"] == "missing"  # not set up yet


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_desktop_icon_posix(home, platform):
    root = home / "AgentCAD"
    out = install.create_shortcut(root, "uvx", "https://example.org/a.zip", platform=platform)
    path = Path(out["path"])
    assert out["status"] == "added" and path.parent == home / "Desktop"
    text = path.read_text("utf-8")
    assert "https://example.org/a.zip" in text and "viewer" in text and "--open" in text
    assert str(root) in text and "agentcad-mcp" not in text
    if platform == "linux":
        assert text.startswith("[Desktop Entry]") and (root / ".agentcad" / "agentcad.png").is_file()
    else:
        assert text.startswith("#!/bin/sh")
    if os.name != "nt":
        assert path.stat().st_mode & 0o111
    assert install.create_shortcut(root, "uvx", platform=platform)["status"] == "updated"


def test_desktop_icon_windows_uses_powershell(home):
    root = home / "AgentCAD"
    run = FakeRunner()
    out = install.create_shortcut(root, "python", platform="win32", runner=run)
    assert out == {"status": "added", "path": "C:/fake/Desktop/AgentCAD.lnk"}
    script = run.calls[0][-1]
    assert "GetFolderPath('Desktop')" in script and "CreateShortcut" in script
    # no console: the icon starts a small progress window (launch-viewer.ps1) through conhost --headless
    assert "conhost.exe" in script and "--headless" in script and "launch-viewer.ps1" in script
    assert "WindowStyle = 7" not in script and "agentcad.ico" in script
    assert (root / ".agentcad" / "agentcad.ico").is_file()
    launch = (root / ".agentcad" / "launch-viewer.ps1").read_bytes()
    assert launch.startswith(b"\xef\xbb\xbf")  # BOM: Windows PowerShell would read Chinese text as ANSI otherwise
    text = launch.decode("utf-8-sig")
    assert '"agentcad.cli"' in text and '"viewer" "--open"' in text and "$fast = $null" in text  # python: no offline try
    assert "正在打开 AgentCAD" in text and "__" not in text.split("Add-Type", 1)[1]
    dry = install.create_shortcut(root, "python", platform="win32", runner=run, dry_run=True)
    assert dry["status"] == "would be added" and "CreateShortcut" not in run.calls[-1][-1]


def test_desktop_icon_failure_does_not_fail_setup(home, monkeypatch):
    def broken(*a, **k):
        raise OSError("no desktop here")
    monkeypatch.setattr(install, "create_shortcut", broken)
    res = install.setup(["cursor"], launcher="python", shortcut=True)
    assert res.ok and res.shortcut == {"status": "error", "code": "SHORTCUT_FAILED", "message": "no desktop here"}


def test_viewer_open_reuses_a_running_viewer(tmp_path, monkeypatch):
    import webbrowser
    from agentcad.policy import Policy
    from agentcad.viewer import Viewer, open_or_serve
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url))
    v = Viewer(Policy(root=tmp_path), port=0).start()
    try:
        assert open_or_serve(Policy(root=tmp_path)) == ({"ok": True}, 0)
        assert opened == [v.url]
    finally:
        v.stop()


def test_powershell_quoting_survives_typographic_apostrophes():
    tricky = "C:/Users/x/Mum\u2019s drawings/\u2018a\u2019 \u201ab\u201b 'c'; Write-Output pwned"
    quoted = install._ps_quote(tricky)
    for q in install.PS_QUOTES:
        assert quoted[1:-1].count(q) == 2 * tricky.count(q)
    if os.name == "nt":  # PowerShell itself reads it back as one string, not as code
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Write-Output " + quoted],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0 and p.stdout.strip() == tricky


def test_desktop_exec_quoting():
    assert install._desktop_quote("/home/a/100%parts") == '"/home/a/100%%parts"'
    assert install._desktop_quote('/x/a"b$c`d') == '"/x/a\\\\"b\\\\$c\\\\`d"'
    assert install._desktop_quote("/x/back\\slash") == '"/x/back\\\\\\\\slash"'


def test_demo_draws_and_revises_the_plate(tmp_path):
    from agentcad import demo
    root = demo.demo_root(tmp_path)
    demo.prepare(root)
    waits = []
    results = demo.draw(root, sleep=waits.append)
    assert all(r["ok"] for r in results) and len(results) == 1 + len(demo.STEPS)
    assert waits == [w for w, _, _ in demo.STEPS]  # a pause before each step, so people can follow
    assert results[-1]["changes"]["modified"] and not results[-1]["changes"]["added"]  # the revision edits
    assert (root / "plate.dxf").is_file() and (root / demo.MARKER).is_file()
    # what people see last: 240 wide, holes 15 from the edges, the bore with its centre mark and callout centred
    import ezdxf
    msp = ezdxf.readfile(root / "plate.dxf").modelspace()
    assert max(p[0] for p in msp.query("LWPOLYLINE")[0].get_points()) == pytest.approx(240)
    circles = sorted((round(c.dxf.center.x, 3), round(c.dxf.center.y, 3), c.dxf.radius) for c in msp.query("CIRCLE"))
    assert circles == [(15, 15, 6), (15, 85, 6), (120, 50, 20), (225, 15, 6), (225, 85, 6)]
    lines = msp.query("LINE")
    assert len(lines) == 2 and all((ln.dxf.start.x + ln.dxf.end.x) / 2 == pytest.approx(120) for ln in lines)
    dims = msp.query("DIMENSION")
    linear = sorted((round(d.get_measurement(), 3), round(d.dxf.defpoint.x, 3)) for d in dims if d.dxf.dimtype & 7 == 0)
    assert linear == [(100, -14), (240, 0)]  # the height dimension sits left of the plate, not across the holes
    bore_dim = next(d for d in dims if d.dxf.dimtype & 7 == 3 and d.get_measurement() == pytest.approx(40))
    assert (bore_dim.dxf.defpoint.x + bore_dim.dxf.defpoint4.x) / 2 == pytest.approx(120)  # moved with the bore
    demo.prepare(root)  # a second run starts clean
    assert not (root / "plate.dxf").exists()


def test_demo_never_clears_a_folder_it_did_not_make(tmp_path):
    from agentcad import demo
    root = demo.demo_root(tmp_path)
    root.mkdir()
    (root / "mine.dxf").write_text("x")
    with pytest.raises(FileExistsError):
        demo.prepare(root)
    assert (root / "mine.dxf").read_text() == "x"


def test_demo_icon(home):
    root = home / "AgentCAD"
    out = install.create_shortcut(root, "uvx", "https://example.org/a.zip", platform="linux",
                                  name="AgentCAD Demo", action=install.DEMO)
    text = Path(out["path"]).read_text("utf-8")
    assert Path(out["path"]).name == "AgentCAD Demo.desktop" and "Name=AgentCAD Demo" in text
    assert '"demo"' in text and "viewer" not in text
    run = FakeRunner()
    install.create_shortcut(root, "python", platform="win32", runner=run, name="AgentCAD 演示", action=install.DEMO)
    assert "'AgentCAD 演示.lnk'" in run.calls[0][-1] and "demo" in run.calls[0][-1]


def test_setup_puts_both_icons(home):
    run = FakeRunner()
    res = install.setup(["cursor"], launcher="python", shortcut=True, runner=run)
    assert res.shortcut["status"] == "added" and res.demo_shortcut["status"] == "added"
    if os.name == "nt":  # through (fake) PowerShell, each with its own launcher
        scripts = [c[-1] for c in run.calls]
        assert any("launch-viewer.ps1" in s for s in scripts) and any("launch-demo.ps1" in s for s in scripts)
        assert '"demo"' in (home / "AgentCAD" / ".agentcad" / "launch-demo.ps1").read_text("utf-8-sig")
    else:
        assert {p.stem for p in (home / "Desktop").iterdir()} == {"AgentCAD", install.demo_name()}


def test_launcher_tries_the_download_it_has_first(tmp_path):
    """With uvx the icon first starts what is already downloaded (--offline, about a second) and downloads only if
    that fails, so a double-click does not wait on GitHub."""
    path = install.write_launcher(tmp_path, "C:/uv/uvx.exe", ["--from", "https://x/a.zip", "agentcad", "--root",
                                                               "C:/Users/me/My Drawings", "demo"], "uvx", install.DEMO)
    text = path.read_text("utf-8-sig")
    assert path.name == "launch-demo.ps1"
    fast = next(ln for ln in text.splitlines() if ln.startswith("$fast"))
    full = next(ln for ln in text.splitlines() if ln.startswith("$full"))
    assert '"--offline" "--from" "https://x/a.zip"' in fast and "--offline" not in full
    assert '"C:/Users/me/My Drawings"' in full  # a folder with a space stays one argument
    assert "正在准备演示" in text and "Getting the demo ready" in text
    if os.name == "nt":  # PowerShell can parse what we wrote
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "$e = $null; [void][Management.Automation.Language.Parser]::ParseFile("
                            + install._ps_quote(str(path)) + ", [ref]$null, [ref]$e); $e.Count"],
                           capture_output=True, text=True)
        assert p.returncode == 0 and p.stdout.strip() == "0", p.stdout + p.stderr


def test_launcher_keeps_special_characters_in_their_argument(tmp_path):
    """An account called R&D or a folder D:\\Drawings&Models: cmd must not split the command at the &."""
    root = r"D:\Drawings&Models (v2)^x"
    path = install.write_launcher(tmp_path, "C:/Users/R&D/.local/bin/uvx.exe",
                                  ["--from", "https://x/a.zip", "agentcad", "--root", root, "viewer", "--open"],
                                  "uvx", install.VIEWER)
    full = next(ln for ln in path.read_text("utf-8-sig").splitlines() if ln.startswith("$full"))
    assert '"C:/Users/R&D/.local/bin/uvx.exe"' in full and '"' + root + '"' in full
    if os.name == "nt":  # cmd /d /s /c hands every argument over whole
        echo = tmp_path / "args.py"
        echo.write_text("import sys, json; print(json.dumps(sys.argv[1:]))", "utf-8")
        line = install._cmd_line([sys.executable, str(echo), "--root", root, "a b", "C:\\dir\\"])
        p = subprocess.run("cmd.exe /d /s /c \"" + line + "\"", capture_output=True, text=True)
        assert json.loads(p.stdout) == ["--root", root, "a b", "C:\\dir\\"], p.stdout + p.stderr
