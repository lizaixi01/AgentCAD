"""Test Q (who is connected): each MCP server process records which app it serves (sessions.py), the live viewer lists
them, progress events and journal records say who made a change, and agentcad_status checks the connection."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import anyio
import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from agentcad import install, mcp_server, progress, sessions
from agentcad.policy import Policy
from agentcad.service import Runtime


@pytest.fixture
def session(tmp_path):
    """A session for this process, as serve_stdio makes one; removed afterwards so no other test sees a client."""
    s = sessions.Session(Policy(root=tmp_path))
    mcp_server.SESSION = s
    yield s
    mcp_server.SESSION = None
    s.close()
    sessions.CURRENT.clear()


def test_friendly_names():
    assert sessions.friendly("claude-code") == "Claude Code"
    assert sessions.friendly("codex-mcp-client") == "Codex"
    assert sessions.friendly("claude-ai") == "Claude Desktop"
    assert sessions.friendly("cursor-vscode") == "Cursor"
    assert sessions.friendly("my-agent") == "my-agent" and sessions.friendly(None) is None


def test_session_file_tag_and_list(tmp_path, session):
    assert sessions.tag() == {}  # nothing known about the client yet
    listed = sessions.list_sessions(tmp_path)
    assert [s["pid"] for s in listed] == [os.getpid()] and listed[0]["client"] is None  # connected, not named yet
    session.note("claude-code", "2.1.0", tool="apply_operations", drawing="plate.dxf", label="mounting plate")
    assert sessions.tag() == {"client": "Claude Code", "conversation": "mounting plate", "session": os.getpid()}
    s = sessions.list_sessions(tmp_path)[0]
    assert (s["client"], s["label"], s["drawing"], s["last_tool"]) == ("Claude Code", "mounting plate", "plate.dxf",
                                                                     "apply_operations")
    # a file left by a server that crashed is dropped
    dead = tmp_path / ".agentcad" / "sessions" / "4000000.json"
    dead.write_text(json.dumps({"pid": 4000000, "client": "Codex"}), "utf-8")
    assert [s["pid"] for s in sessions.list_sessions(tmp_path)] == [os.getpid()] and not dead.exists()
    session.close()
    assert sessions.list_sessions(tmp_path) == []


def test_changes_say_who_made_them(tmp_path, session):
    session.note("codex-mcp-client", "0.163", label="bracket")
    rt = Runtime(Policy(root=tmp_path))
    r = rt.apply_operations("a.dxf", [{"op": "add_circle", "center": [0, 0], "radius": 5}], create={"units": "mm"})
    assert r["ok"], r
    events = [json.loads(ln) for ln in progress.log_path(rt.policy).read_text("utf-8").splitlines()]
    assert events and all(e["client"] == "Codex" and e["conversation"] == "bracket" for e in events)
    rec = rt.history("a.dxf")["records"][-1]
    assert rec["client"] == "Codex" and rec["conversation"] == "bracket"


def test_no_session_no_tag(tmp_path):
    rt = Runtime(Policy(root=tmp_path))
    assert rt.apply_operations("a.dxf", [{"op": "add_circle", "center": [0, 0], "radius": 5}],
                               create={"units": "mm"})["ok"]
    rec = rt.history("a.dxf")["records"][-1]
    assert "client" not in rec and "conversation" not in rec


def test_viewer_lists_sessions(tmp_path, session):
    from agentcad.viewer import Viewer
    session.note("claude-code", "2.1.0", label="flange")
    v = Viewer(Policy(root=tmp_path), port=0).start()
    try:
        with urllib.request.urlopen(v.url + "api/sessions", timeout=5) as r:
            body = json.loads(r.read())
    finally:
        v.stop()
    assert body["ok"] and body["sessions"][0]["client"] == "Claude Code" and body["sessions"][0]["label"] == "flange"


def test_agentcad_status_names_the_client_and_conversation(tmp_path, session, monkeypatch):
    monkeypatch.setenv("AGENTCAD_VIEWER", "0")  # no background viewer in a test

    async def run():
        server = mcp_server.build_server(Policy(root=tmp_path))
        async with create_connected_server_and_client_session(
                server, client_info=types.Implementation(name="claude-code", version="2.1.0")) as client:
            await client.list_tools()  # the client is named as soon as it lists the tools
            assert sessions.CURRENT["client"] == "Claude Code"
            res = await client.call_tool("agentcad_status", {"label": "mounting plate"})
            return json.loads(res.content[0].text)

    out = anyio.run(run)
    assert out["ok"] and out["connected"] and out["app"] == "Claude Code" and out["label"] == "mounting plate"
    assert out["workspace"] == str(tmp_path)
    assert sessions.list_sessions(tmp_path)[0]["label"] == "mounting plate"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    for k in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(k, str(h))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert Path.home() == h
    return h


def test_setup_installs_the_agentcad_skill(home):
    paths = {c: install.skill_path(c) for c in ("claude-code", "codex")}
    assert paths["claude-code"] == home / ".claude" / "skills" / "agentcad" / "SKILL.md"
    assert paths["codex"] == home / ".codex" / "skills" / "agentcad" / "SKILL.md"
    for c, p in paths.items():
        assert install.write_skill(c) == str(p)
        text = p.read_text("utf-8")
        assert text.startswith("---\nname: agentcad\n") and "agentcad_status" in text
    assert install.write_skill("cursor") is None  # no skills there
    mine = paths["codex"]
    mine.write_text("---\nname: agentcad\n---\nmy own\n", "utf-8")
    assert install.write_skill("codex") is None and mine.read_text("utf-8").endswith("my own\n")  # left alone
    dry = home / "dry"
    os.environ["CODEX_HOME"] = str(dry)
    try:
        install.write_skill("codex", dry_run=True)
        assert not dry.exists()
    finally:
        del os.environ["CODEX_HOME"]


def test_a_reused_pid_is_not_a_session(tmp_path, session):
    """A server killed without removing its file: if the OS gives its pid to another program, that program's start
    time differs, so the viewer does not show it as connected."""
    if os.name == "nt" or sys.platform.startswith("linux"):  # macOS has no /proc: the pid alone decides there
        assert sessions.CURRENT.get("created") is not None
    if sessions.CURRENT.get("created") is None:
        pytest.skip("no process start time on this system")
    assert sessions.alive(os.getpid(), sessions.CURRENT["created"])
    assert not sessions.alive(os.getpid(), sessions.CURRENT["created"] + 1)
    f = session.path
    data = json.loads(f.read_text("utf-8"))
    data["created"] += 1
    f.write_text(json.dumps(data), "utf-8")
    assert sessions.list_sessions(tmp_path) == [] and not f.exists()


def test_skill_covers_the_short_tool_list():
    assert 'call_tool(name="agentcad_status"' in install.SKILL
