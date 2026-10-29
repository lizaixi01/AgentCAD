"""Test Q (install): the default workspace, ``agentcad setup`` and ``agentcad doctor``. Every config lives in a
temp home folder; the real ~/.codex, %APPDATA%\\Claude, ~/.claude.json and ~/.cursor are never touched."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from agentcad import install

PY = sys.executable
tomllib = pytest.importorskip("tomllib")


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """A fake home: Path.home(), APPDATA, LOCALAPPDATA and XDG point inside tmp; no agent CLI is on PATH."""
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
    monkeypatch.chdir(tmp_path)  # doctor also reads ./.mcp.json
    assert Path.home() == h
    return h


def _env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("AGENTCAD_ROOT", "CODEX_HOME")}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"), XDG_CONFIG_HOME=str(home / ".config"),
               PATH=str(Path(PY).parent))  # no claude / codex / cursor CLI
    return env


def _paths(home: Path) -> dict[str, Path]:
    return {c: install.config_path(c, home / "AgentCAD") for c in install.CLIENTS}


async def _create_via(command: str, args: list[str], env: dict[str, str], cwd: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async with stdio_client(StdioServerParameters(command=command, args=args, env=env, cwd=cwd)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("create_drawing", {"path": "c.dxf", "units": "mm"})
            return json.loads(res.content[0].text)


@pytest.mark.parametrize("args", [["-m", "agentcad.mcp_server"], ["-m", "agentcad.cli", "mcp"]])
def test_server_defaults_to_home_workspace(home, tmp_path, args):
    """Without AGENTCAD_ROOT the server works in ~/AgentCAD (created), not in the folder the client starts in."""
    start = tmp_path / "client-start"
    start.mkdir()
    out = anyio.run(_create_via, PY, args, _env(home), start)
    assert out["ok"], out
    assert (home / "AgentCAD" / "c.dxf").is_file() and not (start / "c.dxf").exists()


def test_workspace_root_order(home, monkeypatch, tmp_path):
    assert install.workspace_root() == (home / "AgentCAD").resolve()
    monkeypatch.setenv("AGENTCAD_ROOT", str(tmp_path / "env"))
    assert install.workspace_root() == (tmp_path / "env").resolve()
    assert install.workspace_root(tmp_path / "flag") == (tmp_path / "flag").resolve()
    assert install.ensure_workspace().is_dir()


def _seed(home: Path) -> dict[str, Path]:
    """Each client already has another server; Codex also has a stale agentcad table with an env sub-table."""
    p = _paths(home)
    for c in ("claude-code", "claude-desktop", "cursor"):
        p[c].parent.mkdir(parents=True, exist_ok=True)
        p[c].write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}), "utf-8")
    p["codex"].parent.mkdir(parents=True)
    p["codex"].write_text('model = "gpt"\n\n[mcp_servers.agentcad]\ncommand = "old"\n\n[mcp_servers.agentcad.env]\n'
                          'A = "1"\n\n[mcp_servers.other]\ncommand = "y"\nargs = ["z"]\n', "utf-8")
    return p


def test_setup_all_clients_idempotent(home):
    p = _seed(home)
    res = install.setup(list(install.CLIENTS))
    assert res.ok and res.launcher == "python"
    assert {c["client"]: c["status"] for c in res.clients} == {
        "claude-code": "added", "codex": "updated", "claude-desktop": "added", "cursor": "added"}
    root = (home / "AgentCAD").resolve()
    assert root.is_dir()
    for c in ("claude-code", "claude-desktop", "cursor"):
        data = json.loads(p[c].read_text("utf-8"))
        assert data["theme"] == "dark" and set(data["mcpServers"]) == {"other", "agentcad"}
        e = data["mcpServers"]["agentcad"]
        assert Path(e["command"]).samefile(PY) and e["args"] == ["-m", "agentcad.mcp_server"]
        assert e["env"]["AGENTCAD_ROOT"] == root.as_posix()
    cfg = tomllib.loads(p["codex"].read_text("utf-8"))
    assert cfg["model"] == "gpt" and cfg["mcp_servers"]["other"] == {"command": "y", "args": ["z"]}
    codex = cfg["mcp_servers"]["agentcad"]
    assert Path(codex["command"]).samefile(PY) and codex["default_tools_approval_mode"] == "approve"
    assert codex["env"] == {"AGENTCAD_ROOT": root.as_posix(), "PYTHONIOENCODING": "utf-8",
                            **{k: os.environ[k] for k in ("AGENTCAD_FREECAD", "FREECAD_LIB") if os.environ.get(k)}}

    before = {c: p[c].read_bytes() for c in install.CLIENTS}
    again = install.setup(list(install.CLIENTS))
    assert {c["status"] for c in again.clients} == {"unchanged"}
    assert {c: p[c].read_bytes() for c in install.CLIENTS} == before

    out = install.render_setup(again)
    assert install.FIRST_PROMPT in out and str(root) in out and "doctor" in out


def test_setup_dry_run_writes_nothing(home):
    res = install.setup(list(install.CLIENTS), dry_run=True)
    assert [c["status"] for c in res.clients] == ["would be added"] * 4
    assert not any(path.exists() for path in _paths(home).values())
    assert not (home / "AgentCAD").exists()
    assert "Dry run" in install.render_setup(res)


def test_setup_written_config_starts_server(home, tmp_path):
    install.setup(["cursor"], tmp_path / "my drawings")
    entry = json.loads(_paths(home)["cursor"].read_text("utf-8"))["mcpServers"]["agentcad"]
    start = tmp_path / "start"
    start.mkdir()
    out = anyio.run(_create_via, entry["command"], entry["args"], {**_env(home), **entry["env"]}, start)
    assert out["ok"] and (tmp_path / "my drawings" / "c.dxf").is_file()


def test_bad_config_left_alone(home):
    p = _paths(home)
    p["cursor"].parent.mkdir(parents=True)
    p["cursor"].write_text("{not json", "utf-8")
    res = install.setup(["cursor", "claude-desktop"])
    st = {c["client"]: c for c in res.clients}
    assert st["cursor"]["status"] == "error" and "not valid JSON" in st["cursor"]["message"]
    assert p["cursor"].read_text("utf-8") == "{not json"
    assert st["claude-desktop"]["status"] == "added" and not res.ok


def test_claude_code_uses_cli_when_present(home, monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name, *a, **k: "/bin/claude" if name == "claude" else None)
    calls: list[list[str]] = []

    def runner(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[2] == "remove" else 0, "", "")

    dry = install.setup(["claude-code"], dry_run=True, runner=runner)
    assert calls == [] and dry.clients[0]["status"] == "would run"
    res = install.setup(["claude-code"], runner=runner, freecad=None)
    assert res.clients[0]["status"] == "registered"
    assert calls[0] == ["/bin/claude", "mcp", "remove", "agentcad", "--scope", "user"]
    add = calls[1]
    assert add[:6] == ["/bin/claude", "mcp", "add", "agentcad", "--scope", "user"]
    assert f"AGENTCAD_ROOT={(home / 'AgentCAD').resolve().as_posix()}" in add
    assert add[add.index("--") + 1:] == [res.entry["command"], "-m", "agentcad.mcp_server"]
    assert not (home / "AgentCAD" / ".mcp.json").exists()

    failing = install.setup(["claude-code"], runner=lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    assert failing.clients[0]["status"] == "error" and failing.clients[0]["message"] == "boom"


def test_uvx_launcher(home):
    res = install.setup(["codex", "claude-desktop"], launcher="uvx", source="git+https://example.org/x@br")
    e = res.entry
    assert Path(e["command"]).stem.lower() == "uvx" or e["command"] == "uvx"
    assert e["args"] == ["--from", "git+https://example.org/x@br", "--with", "pillow", "agentcad-mcp"]
    cfg = tomllib.loads(_paths(home)["codex"].read_text("utf-8"))["mcp_servers"]["agentcad"]
    assert cfg["startup_timeout_sec"] == 120 and cfg["args"] == e["args"]


def test_ephemeral_detection():
    assert install._is_ephemeral(Path("C:/Users/u/AppData/Local/uv/cache/archive-v0/abc"))
    assert install._is_ephemeral(Path("/home/u/.local/pipx/.cache/abc"))
    assert not install._is_ephemeral(Path("/home/u/.local/share/uv/tools/agentcad-runtime"))
    assert not install._is_ephemeral(Path("/home/u/.local/pipx/venvs/agentcad-runtime"))
    assert install.choose_launcher("auto", {"ephemeral": True}) == "uvx"
    assert install.choose_launcher("auto", {"ephemeral": False}) == "python"
    assert install.choose_launcher("uvx", {"ephemeral": False}) == "uvx"


def test_freecad_option(home, tmp_path):
    with pytest.raises(install.AgentCADError) as ei:
        install.setup(["cursor"], freecad=str(tmp_path / "nope"))
    assert ei.value.code == "FREECAD_NOT_FOUND" and not _paths(home)["cursor"].exists()
    fc = tmp_path / "FreeCAD" / "bin"
    fc.mkdir(parents=True)
    (fc / ("freecadcmd.exe" if os.name == "nt" else "freecadcmd")).write_text("", "utf-8")
    res = install.setup(["cursor"], freecad=str(tmp_path / "FreeCAD"))
    assert res.entry["env"]["AGENTCAD_FREECAD"] == (tmp_path / "FreeCAD").as_posix()
    assert res.freecad == str(tmp_path / "FreeCAD")


def test_ask_clients():
    detected = {"claude-code": True, "codex": False, "claude-desktop": True, "cursor": False}
    quiet = lambda s: None
    assert install.ask_clients(detected, lambda p: "", quiet) == ["claude-code", "claude-desktop"]
    assert install.ask_clients(detected, lambda p: "2, 4 4 9 x", quiet) == ["codex", "cursor"]


def test_doctor(home):
    r = install.doctor()
    by = {c["name"]: c for c in r["checks"]}
    assert r["ok"] and by["Python"]["status"] == "ok" and by["ezdxf"]["status"] == "ok"
    assert by["Workspace"]["status"] == "missing" and "setup" in by["Workspace"]["fix"]
    assert {by[f"{install.LABELS[c]} config"]["status"] for c in install.CLIENTS} == {"skip"}  # no apps in this home

    (home / ".cursor").mkdir()
    by = {c["name"]: c for c in install.doctor()["checks"]}
    assert by["Cursor config"]["status"] == "missing" and by["Cursor config"]["fix"].endswith("--client cursor")

    install.setup(list(install.CLIENTS))
    by = {c["name"]: c for c in install.doctor()["checks"]}
    assert by["Workspace"]["status"] == "ok"
    for c in install.CLIENTS:
        assert by[f"{install.LABELS[c]} config"]["status"] == "ok", by
    text = install.render_doctor(install.doctor())
    assert "Cursor config" in text and "All required parts are working." in text

    p = _paths(home)["claude-desktop"]
    data = json.loads(p.read_text("utf-8"))
    data["mcpServers"]["agentcad"]["command"] = str(home / "gone" / "python")
    p.write_text(json.dumps(data), "utf-8")
    by = {c["name"]: c for c in install.doctor()["checks"]}
    assert by["Claude Desktop config"]["status"] == "missing" and "does not exist" in by["Claude Desktop config"]["detail"]


def test_cli_setup_and_doctor(home, tmp_path):
    env = _env(home)
    run = lambda *a: subprocess.run([PY, "-m", "agentcad.cli", *a], capture_output=True, text=True, encoding="utf-8",
                                    env=env, cwd=tmp_path, timeout=120)
    p = run("setup", "--dry-run", "--client", "all", "--json")
    assert p.returncode == 0, p.stderr
    r = json.loads(p.stdout)
    assert r["dry_run"] and len(r["clients"]) == 4 and not (home / "AgentCAD").exists()
    p = run("setup", "--client", "cursor", "--client", "codex", "--root", str(tmp_path / "ws"))
    assert p.returncode == 0, p.stderr
    assert "Cursor" in p.stdout and "Next steps" in p.stdout and (tmp_path / "ws").is_dir()
    entry = json.loads(_paths(home)["cursor"].read_text("utf-8"))["mcpServers"]["agentcad"]
    assert entry["env"]["AGENTCAD_ROOT"] == (tmp_path / "ws").resolve().as_posix()
    p = run("setup", "--yes", "--json")  # nothing detected in an empty home except the folders setup just made
    assert p.returncode == 0 and {c["client"] for c in json.loads(p.stdout)["clients"]} <= set(install.CLIENTS)
    p = run("doctor", "--json", "--root", str(tmp_path / "ws"))
    assert p.returncode == 0, p.stdout
    by = {c["name"]: c["status"] for c in json.loads(p.stdout)["checks"]}
    assert by["Cursor config"] == "ok" and by["Codex config"] == "ok" and by["Workspace"] == "ok"
    p = run("setup", "--help")
    assert p.returncode == 0 and "--dry-run" in p.stdout and "claude-desktop" in p.stdout
