"""Test Q (setup wizard): ``agentcad setup --gui`` serves a local page that runs ``install.setup`` and reports each
step. Configs live in a temp home folder, as in test_q_install."""
from __future__ import annotations

import http.client
import json
import time
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


@pytest.fixture
def wizard(home):
    w = Wizard(launcher="python").start_background()
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
    assert [s["id"] for s in st["steps"]] == ["workspace", "freecad", "autocad", "cursor", "codex"]
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
    assert step["id"] == "cursor" and step["state"] == "error" and "not valid JSON" in step["info"]["message"]
    assert bad.read_text("utf-8") == "{not json"


def test_dry_run_writes_nothing(home):
    w = Wizard(launcher="python", dry_run=True).start_background()
    try:
        assert _call(w, "GET", "/api/info")[1]["dry_run"] is True
        _call(w, "POST", "/api/start", {"clients": ["cursor"]})
        st = _wait(w)
        assert st["phase"] == "done" and st["result"]["clients"][0]["status"] == "would be added"
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
