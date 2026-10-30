"""Install helpers for people, not agents: the default workspace folder, ``agentcad setup`` (writes the MCP
config of Claude Code, Codex, Claude Desktop and Cursor) and ``agentcad doctor`` (checks the install).

Every path comes from ``Path.home()`` and the environment (APPDATA, LOCALAPPDATA), and every external command goes
through ``runner``, so tests point them at temp folders and fakes."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

from .errors import AgentCADError, input_error

REPO = "https://github.com/lizaixi01/AgentCAD"
DIST = "agentcad-runtime"
NAME = "agentcad"
CLIENTS = ("claude-code", "codex", "claude-desktop", "cursor")
LABELS = {"claude-code": "Claude Code", "codex": "Codex", "claude-desktop": "Claude Desktop", "cursor": "Cursor"}
FIRST_PROMPT = ("Draw a 200 x 100 mounting plate with R8 corners and four 12 mm holes 15 mm from the edges. "
                "Save it as plate.dxf, check it, and export plate.svg.")
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


# --- workspace ---------------------------------------------------------------------------------------------------
def default_root() -> Path:
    """Where drawings go when nothing says otherwise: ~/AgentCAD (C:\\Users\\<you>\\AgentCAD on Windows)."""
    return Path.home() / "AgentCAD"


def workspace_root(explicit: str | os.PathLike | None = None) -> Path:
    """--root, else $AGENTCAD_ROOT, else ~/AgentCAD. Never the directory the client happens to start in."""
    raw = explicit or os.environ.get("AGENTCAD_ROOT") or default_root()
    return Path(raw).expanduser().resolve()


def ensure_workspace(explicit: str | os.PathLike | None = None) -> Path:
    root = workspace_root(explicit)
    root.mkdir(parents=True, exist_ok=True)
    return root


# --- how this copy was installed, and how a client should start it ----------------------------------------------
def install_info() -> dict[str, Any]:
    """version, source ('git+...' when installed from git), editable, ephemeral (a uvx / pipx run cache)."""
    from importlib import metadata
    info: dict[str, Any] = {"version": None, "source": None, "editable": False,
                            "ephemeral": _is_ephemeral(Path(sys.prefix))}
    try:
        dist = metadata.distribution(DIST)
    except metadata.PackageNotFoundError:
        from . import __version__
        info["version"] = __version__
        return info
    info["version"] = dist.version
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "null") or {}
    except ValueError:
        direct = {}
    vcs = direct.get("vcs_info") or {}
    if vcs.get("vcs") == "git":
        rev = vcs.get("requested_revision")
        info["source"] = f"git+{direct['url']}" + (f"@{rev}" if rev else "")
    info["editable"] = bool((direct.get("dir_info") or {}).get("editable"))
    return info


def _is_ephemeral(prefix: Path) -> bool:
    """True inside a throw-away environment, whose interpreter may vanish when the cache is cleaned, so a client
    config must not point at it: uvx / ``uv tool run`` (<uv cache>/archive-v0/<id>, checked on Windows) and
    ``pipx run`` (Windows %LOCALAPPDATA%\\pipx\\pipx\\Cache\\<id>, checked; macOS ~/Library/Caches/pipx/<id>, Linux
    ~/.cache/pipx/<id>, older pipx or PIPX_HOME <home>/.cache/<id>: not run on macOS/Linux)."""
    parts = [p.lower() for p in prefix.parts]
    if "archive-v0" in parts:
        return True
    return any("pipx" in p for p in parts) and any(p in (".cache", "cache", "caches") for p in parts)


def launcher_command(launcher: str, source: str | None = None) -> tuple[str, list[str]]:
    """(command, args) that starts the MCP server. 'python': this interpreter (a clone, pipx install or
    ``uv tool install``). 'uvx' / 'pipx': they fetch the package themselves, so it keeps working when their caches
    are cleaned."""
    src = source or f"git+{REPO}"
    if launcher in ("uvx", "pipx"):
        found = shutil.which(launcher)
        cmd = Path(found).as_posix() if found else launcher  # absolute: desktop apps do not see the shell's PATH
        return cmd, (["--from", src, "agentcad-mcp"] if launcher == "uvx" else ["run", "--spec", src, "agentcad-mcp"])
    return Path(sys.executable).absolute().as_posix(), ["-m", "agentcad.mcp_server"]


def choose_launcher(launcher: str, info: dict[str, Any]) -> str:
    if launcher != "auto":
        return launcher
    if not info["ephemeral"]:
        return "python"
    return "pipx" if not shutil.which("uvx") and shutil.which("pipx") else "uvx"


def self_command(info: dict[str, Any]) -> str:
    """How the user runs ``agentcad`` again (for 'agentcad doctor' in the next steps)."""
    if info["ephemeral"]:
        src = info["source"] or "git+" + REPO
        if not shutil.which("uvx") and shutil.which("pipx"):
            return f"pipx run --spec {src} agentcad"
        return f"uvx --from {src} agentcad"
    exe = shutil.which("agentcad")
    here = Path(sys.executable).parent
    if exe and Path(exe).parent.resolve() == here.resolve():
        return "agentcad"
    mine = here / ("agentcad.exe" if os.name == "nt" else "agentcad")
    if mine.is_file():
        return f'"{mine}"' if " " in str(mine) else str(mine)
    return f'"{Path(sys.executable)}" -m agentcad.cli'


def server_entry(root: Path, launcher: str, source: str | None = None, *, freecad: str | None = None,
                 read_only: bool = False, allow_scripts: bool = False) -> dict[str, Any]:
    command, args = launcher_command(launcher, source)
    env = {"AGENTCAD_ROOT": root.as_posix(), "PYTHONIOENCODING": "utf-8"}
    if read_only:
        env["AGENTCAD_READ_ONLY"] = "1"
    if allow_scripts:
        env["AGENTCAD_ALLOW_SCRIPTS"] = "1"
    if freecad:
        env["AGENTCAD_FREECAD"] = Path(freecad).as_posix()
    for key in ("AGENTCAD_FREECAD", "FREECAD_LIB"):
        if key not in env and os.environ.get(key):
            env[key] = os.environ[key]
    return {"command": command, "args": args, "env": env}


# --- where each client keeps its config ---------------------------------------------------------------------------
def claude_desktop_config() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        # the Microsoft Store (MSIX) build reads a virtualized copy of %APPDATA%
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        for pkg in sorted(local.glob("Packages/Claude_*/LocalCache/Roaming/Claude")):
            if (pkg / "claude_desktop_config.json").is_file():
                return pkg / "claude_desktop_config.json"
        appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return appdata / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "Claude" / "claude_desktop_config.json"


def config_path(client: str, root: Path) -> Path:
    home = Path.home()
    return {"claude-code": root / ".mcp.json",  # used only when the claude CLI is not on PATH
            "codex": Path(os.environ.get("CODEX_HOME") or home / ".codex") / "config.toml",
            "claude-desktop": claude_desktop_config(),
            "cursor": home / ".cursor" / "mcp.json"}[client]


def detect_clients() -> dict[str, bool]:
    home = Path.home()
    return {"claude-code": bool(shutil.which("claude")) or (home / ".claude").is_dir() or (home / ".claude.json").is_file(),
            "codex": bool(shutil.which("codex")) or config_path("codex", home).parent.is_dir(),
            "claude-desktop": claude_desktop_config().parent.is_dir(),
            "cursor": bool(shutil.which("cursor")) or (home / ".cursor").is_dir()}


# --- writers: each keeps the other servers and is a no-op when the entry is already right -------------------------
def _read_json(path: Path) -> dict[str, Any]:
    text = path.read_text("utf-8-sig") if path.is_file() else ""  # -sig: files saved by Notepad start with a BOM
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise input_error("BAD_CONFIG", f"{path} is not valid JSON: {exc}", hint="Fix or move that file, then run setup again")
    if not isinstance(data, dict):
        raise input_error("BAD_CONFIG", f"{path} does not hold a JSON object")
    return data


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".agentcad-tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)


def write_json_config(path: Path, name: str, entry: dict[str, Any], dry_run: bool = False) -> str:
    data = _read_json(path)
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise input_error("BAD_CONFIG", f"{path}: mcpServers is not an object")
    if (servers or {}).get(name) == entry:
        return "unchanged"
    status = "updated" if name in (servers or {}) else "added"
    if not dry_run:
        data.setdefault("mcpServers", {})[name] = entry
        _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return status


_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


def _drop_toml_table(text: str, name: str) -> tuple[str, bool]:
    """Remove every definition of mcp_servers.<name>: its [table] and sub-tables ([mcp_servers.<name>.env]), an
    inline ``<name> = {...}`` or dotted ``<name>.key = ...`` under [mcp_servers], and top-level dotted
    ``mcp_servers.<name>... = ...`` keys. (Inline tables are one line in TOML 1.0.)"""
    names = (name, f'"{name}"', f"'{name}'")
    tables = {f"mcp_servers.{n}" for n in names}
    out, table, skipping, found = [], "", False, False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line)
        if m:
            table = m.group(1).replace(" ", "")
            skipping = table in tables or any(table.startswith(k + ".") for k in tables)
            found = found or skipping
        elif not skipping and "=" in line:
            key = "".join(line.split("=", 1)[0].split())
            if (table == "mcp_servers" and any(key == n or key.startswith(n + ".") for n in names)) or \
                    (table == "" and any(key == k or key.startswith(k + ".") for k in tables)):
                found = True
                continue
        if not skipping:
            out.append(line)
    return "".join(out), found


def codex_table(name: str, entry: dict[str, Any], launcher: str) -> str:
    from .mcp_config import codex_toml
    toml = codex_toml(name, entry)
    if launcher in ("uvx", "pipx"):  # the first start may download the package; Codex's default is 10 s
        toml = toml.rstrip("\n") + "\nstartup_timeout_sec = 120\n"
    return toml


def _parse_toml(text: str, path: Path, what: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except ValueError as exc:
        raise input_error("BAD_CONFIG", f"{path} {what} is not valid TOML: {exc}",
                          hint="Fix or move that file, then run setup again")


def write_codex_config(path: Path, name: str, table: str, dry_run: bool = False) -> str:
    """Replace this server's entry and keep everything else. Both the old and the new file must parse:
    an invalid file is left alone, and an invalid result is never written."""
    text = path.read_text("utf-8-sig") if path.is_file() else ""
    _parse_toml(text, path, "as it is")
    rest, found = _drop_toml_table(text, name)
    rest = rest.rstrip("\n")
    new = (rest + "\n\n" if rest else "") + table
    if new == text:
        return "unchanged"
    parsed = _parse_toml(new, path, "after the change")
    want = _parse_toml(table, path, "entry")
    if parsed["mcp_servers"][name] != want["mcp_servers"][name]:
        raise input_error("BAD_CONFIG", f"{path}: could not replace mcp_servers.{name} cleanly",
                          hint=f"Delete the {name} entry from that file, then run setup again")
    if not dry_run:
        _write(path, new)
    return "updated" if found else "added"


def claude_cli_commands(name: str, entry: dict[str, Any]) -> list[list[str]]:
    """``claude mcp`` calls that register the server for the user: add; if it is already there, remove + add."""
    claude = shutil.which("claude") or "claude"
    return [_claude_add(claude, name, entry), [claude, "mcp", "remove", name, "--scope", "user"]]


def _claude_add(claude: str, name: str, entry: dict[str, Any]) -> list[str]:
    add = [claude, "mcp", "add", name, "--scope", "user"]
    for k, v in (entry.get("env") or {}).items():
        add += ["-e", f"{k}={v}"]
    return add + ["--", entry["command"], *(entry.get("args") or [])]


CMD_META = set('&|<>^%"!')


def cmd_unsafe(cmd: list[str]) -> str | None:
    """Windows runs a .cmd / .bat (npm's claude.cmd) through cmd.exe, which interprets these characters even in a
    list-form call with shell=False. Returns the first argument that has one, or None."""
    if Path(cmd[0]).suffix.lower() not in (".cmd", ".bat"):
        return None
    return next((a for a in cmd[1:] if CMD_META & set(a)), None)


def _register_with_claude(name: str, entry: dict[str, Any], run: Runner) -> dict[str, Any]:
    """Register via ``claude mcp``. The previous registration is removed only after a first add fails (it exists),
    and put back when the second add fails too."""
    add, remove = claude_cli_commands(name, entry)
    if run(add).returncode == 0:
        return {"status": "registered"}
    old = _claude_user_entry(name)
    run(remove)
    p = run(add)
    if p.returncode == 0:
        return {"status": "registered"}
    msg = (p.stderr or p.stdout).strip()[:500]
    if old is not None:
        back = _claude_add(add[0], name, old)
        restored = cmd_unsafe(back) is None and run(back).returncode == 0
        msg += (" (your previous agentcad registration was restored)" if restored else
                " (your previous agentcad registration was removed and could not be restored)")
    return {"status": "error", "message": msg}


def _claude_user_entry(name: str) -> dict[str, Any] | None:
    """The user-scope entry Claude Code stored in ~/.claude.json, as {command, args, env}."""
    try:
        e = (_read_json(Path.home() / ".claude.json").get("mcpServers") or {}).get(name)
    except (AgentCADError, OSError):
        return None
    return {k: e.get(k, [] if k == "args" else {}) for k in ("command", "args", "env")} if isinstance(e, dict) else None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)


# --- setup -----------------------------------------------------------------------------------------------------
@dataclass
class SetupResult:
    root: Path
    launcher: str
    entry: dict[str, Any]
    dry_run: bool
    clients: list[dict[str, Any]] = field(default_factory=list)
    freecad: str | None = None
    autocad: str | None = None
    self_cmd: str = "agentcad"

    @property
    def ok(self) -> bool:
        return all(c["status"] != "error" for c in self.clients)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "dry_run": self.dry_run, "workspace": str(self.root), "launcher": self.launcher,
                "server": self.entry, "clients": self.clients, "freecad": self.freecad, "autocad": self.autocad}


def find_freecad_path() -> str | None:
    from .backends import freecad
    hit = freecad.find_freecad()
    return hit[0][0] if hit else None


def freecad_at(path: str) -> bool:
    """Is there a usable FreeCAD at this AGENTCAD_FREECAD value?"""
    from .backends import freecad as fc
    old = os.environ.get("AGENTCAD_FREECAD")
    os.environ["AGENTCAD_FREECAD"] = path
    try:
        return fc.find_freecad() is not None
    finally:
        if old is None:
            del os.environ["AGENTCAD_FREECAD"]
        else:
            os.environ["AGENTCAD_FREECAD"] = old


def configured_freecad(root: Path) -> str | None:
    """A working AGENTCAD_FREECAD from any app's agentcad entry."""
    for client in CLIENTS:
        _, entry = _client_entry(client, root)
        path = ((entry or {}).get("env") or {}).get("AGENTCAD_FREECAD")
        if path and freecad_at(path):
            return path
    return None


def find_autocad_path() -> str | None:
    if os.name != "nt":
        return None
    from .backends.autocad import find_accoreconsole
    p = find_accoreconsole()
    return str(p) if p else None


def setup(clients: list[str], root: str | os.PathLike | None = None, *, launcher: str = "auto",
          source: str | None = None, freecad: str | None = None, dry_run: bool = False, read_only: bool = False,
          allow_scripts: bool = False, name: str = NAME, runner: Runner | None = None) -> SetupResult:
    info = install_info()
    launcher = choose_launcher(launcher, info)
    if freecad and not freecad_at(freecad):
        raise input_error("FREECAD_NOT_FOUND", f"No FreeCAD found at {freecad}",
                          hint="Give FreeCAD's install folder, its bin folder or its python / freecadcmd")
    root_path = workspace_root(root)
    found = find_freecad_path()
    if not freecad and not found:  # keep a FreeCAD that an earlier 'setup --freecad' wrote
        freecad = configured_freecad(root_path)
    if not dry_run:
        root_path.mkdir(parents=True, exist_ok=True)
    entry = server_entry(root_path, launcher, source or info["source"], freecad=freecad, read_only=read_only,
                         allow_scripts=allow_scripts)
    res = SetupResult(root_path, launcher, entry, dry_run, self_cmd=self_command(info))
    res.freecad = freecad or found
    res.autocad = find_autocad_path()
    run = runner or _run
    for client in clients:
        rec: dict[str, Any] = {"client": client, "label": LABELS[client]}
        try:
            cmds = claude_cli_commands(name, entry) if client == "claude-code" and shutil.which("claude") else None
            bad = cmd_unsafe(cmds[0]) if cmds else None
            if bad:
                cmds = None
                rec["message"] = (f"{shutil.which('claude')} runs through cmd.exe, which would garble {bad!r}, so "
                                  "this wrote .mcp.json instead. A folder name without & | < > ^ % \" ! lets setup "
                                  "use claude mcp add.")
            if cmds:
                rec.update(target="claude mcp (user scope)", commands=cmds)
                if _claude_user_entry(name) == entry:
                    rec["status"] = "unchanged"
                elif dry_run:
                    rec["status"] = "would run"
                else:
                    rec.update(_register_with_claude(name, entry, run))
            else:
                path = config_path(client, root_path)
                rec["target"] = str(path)
                if client == "codex":
                    rec["status"] = write_codex_config(path, name, codex_table(name, entry, launcher), dry_run)
                else:
                    rec["status"] = write_json_config(path, name, entry, dry_run)
                if dry_run and rec["status"] != "unchanged":
                    rec["status"] = "would be " + rec["status"]
        except AgentCADError as exc:  # a config file that is not valid JSON: left alone
            rec.update(status="error", message=exc.message + (f" ({exc.hint})" if exc.hint else ""))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            rec.update(status="error", message=str(exc))
        res.clients.append(rec)
    return res


_RESTART = {"claude-code": "Start a new Claude Code session (type /mcp to see agentcad listed).",
            "codex": "Start a new Codex session (type /mcp to see agentcad listed).",
            "claude-desktop": "Quit Claude Desktop completely (also from the tray / menu bar) and open it again.",
            "cursor": "Restart Cursor, then turn agentcad on under Settings > MCP if it is off."}


def render_setup(res: SetupResult) -> str:
    L = []
    if res.dry_run:
        L += ["Dry run: nothing was written.", ""]
    L.append(f"Workspace (your drawings are saved here): {res.root}")
    how = (f"{res.launcher} (downloads AgentCAD from GitHub when needed)" if res.launcher in ("uvx", "pipx")
           else "this Python: " + res.entry["command"])
    L += [f"Server starts with: {how}", ""]
    for c in res.clients:
        line = f"  {c['label']:<15} {c['status']:<16} {c.get('target', '')}"
        L.append(line.rstrip())
        if c.get("message"):
            L.append(f"      {c['message']}")
        if res.dry_run and c.get("commands"):
            L += ["      " + subprocess.list2cmdline(cmd) for cmd in c["commands"]]
    if not res.clients:
        L.append("  No client chosen. Pass --client claude-code|codex|claude-desktop|cursor|all.")
    L.append("")
    if res.freecad:
        L.append(f"FreeCAD found: {res.freecad}  (3D parts work)")
    else:
        L.append("FreeCAD not found: 2D drawings work; for 3D parts install FreeCAD 1.1 (freecad.org), then run "
                 "setup again with --freecad <FreeCAD folder>.")
    if res.autocad:
        L.append(f"AutoCAD found: {res.autocad}  (DWG import/export)")
    else:
        L.append("AutoCAD not found (optional: only needed for DWG files).")
    done = [c for c in res.clients if c["status"] not in ("error",) and not c["status"].startswith("would")]
    if done and not res.dry_run:
        L += ["", "Next steps:"]
        n = 1
        for c in done:
            if c["client"] == "claude-code" and "commands" not in c:
                L.append(f"  {n}. Open Claude Code in {res.root} and approve the agentcad server when asked.")
            else:
                L.append(f"  {n}. {_RESTART[c['client']]}")
            n += 1
        L += [f"  {n}. Ask your agent:", f"     \"{FIRST_PROMPT}\"",
              f"  {n + 1}. Open {res.root} to see plate.svg.", "",
              f"Something not working? Run: {res.self_cmd} doctor"]
    elif res.dry_run:
        L += ["", "Run the same command without --dry-run to write it."]
    return "\n".join(L)


def ask_clients(detected: dict[str, bool], ask: Callable[[str], str] = input,
                out: Callable[[str], None] = print) -> list[str]:
    out("Which apps should use AgentCAD?")
    for i, c in enumerate(CLIENTS, 1):
        out(f"  {i}. {LABELS[c]}{'  (found on this computer)' if detected[c] else ''}")
    default = [c for c in CLIENTS if detected[c]]
    hint = ", ".join(str(CLIENTS.index(c) + 1) for c in default) or "none"
    ans = ask(f"Numbers separated by spaces [Enter = {hint}]: ").strip()
    if not ans:
        return default
    picked = []
    for tok in re.split(r"[\s,]+", ans):
        if tok.isdigit() and 1 <= int(tok) <= len(CLIENTS) and CLIENTS[int(tok) - 1] not in picked:
            picked.append(CLIENTS[int(tok) - 1])
    return picked


# --- doctor ----------------------------------------------------------------------------------------------------
def _client_entry(client: str, root: Path) -> tuple[str | None, dict[str, Any] | None]:
    """(where, entry) of the agentcad server in this client's config, or (None, None)."""
    home = Path.home()
    if client == "claude-code":
        places = [(home / ".claude.json", "user"), (root / ".mcp.json", "project"), (Path.cwd() / ".mcp.json", "project")]
    elif client == "codex":
        path = config_path("codex", root)
        if not path.is_file():
            return None, None
        try:
            data = tomllib.loads(path.read_text("utf-8-sig"))
        except ValueError:
            return str(path) + " (not valid TOML)", None
        e = (data.get("mcp_servers") or {}).get(NAME)
        return (str(path), e) if e is not None else (None, None)
    else:
        places = [(config_path(client, root), "")]
    for path, _ in places:
        try:
            data = _read_json(path)
        except Exception:
            continue
        e = (data.get("mcpServers") or {}).get(NAME)
        if e is not None:
            return str(path), e
    return None, None


def _check_entry(entry: dict[str, Any]) -> str | None:
    """Problem with a configured entry, or None."""
    cmd = entry.get("command")
    if cmd and not (Path(cmd).is_file() or shutil.which(cmd)):
        return f"its command {cmd} does not exist"
    root = (entry.get("env") or {}).get("AGENTCAD_ROOT")
    if root and not Path(root).is_dir():
        return f"its workspace {root} does not exist"
    return None


def doctor(root: str | os.PathLike | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str, fix: str = "", required: bool = False) -> None:
        checks.append({"name": name, "status": status, "detail": detail, "fix": fix, "required": required})

    info = install_info()
    v = sys.version_info
    add("Python", "ok" if v >= (3, 10) else "missing", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})",
        "Install Python 3.10 or newer (uv does it for you: uv python install 3.12)", required=True)
    where = "editable checkout" if info["editable"] else (info["source"] or "installed")
    add("AgentCAD", "ok", f"{DIST} {info['version']} ({where})", required=True)
    for mod, pkg in (("ezdxf", "ezdxf"), ("mcp", "mcp"), ("pypdf", "pypdf")):
        try:
            __import__(mod)
            add(pkg, "ok", "installed", required=True)
        except ImportError:
            add(pkg, "missing", "not importable", f"Reinstall AgentCAD (it brings {pkg})", required=True)
    try:
        import PIL
        add("Pillow", "ok", f"{PIL.__version__} (SVG export, image previews)", required=True)
    except ImportError:
        add("Pillow", "missing", "SVG export and image previews will not work",
            "Reinstall AgentCAD (it brings Pillow), or pip install pillow into this Python", required=True)
    ws = workspace_root(root)
    if ws.is_dir() and os.access(ws, os.W_OK):
        add("Workspace", "ok", str(ws))
    else:
        add("Workspace", "missing", f"{ws} does not exist or is not writable",
            "Run agentcad setup (it creates the folder), or set AGENTCAD_ROOT to a folder you own")
    fc = find_freecad_path()
    if not fc:
        fc = configured_freecad(ws)
        fc = f"{fc} (set in the app configs)" if fc else None
    add("FreeCAD", "ok" if fc else "missing", fc or "not found: 3D parts (.FCStd) will not work",
        "" if fc else "Install FreeCAD 1.1 from freecad.org, then: agentcad setup --freecad <FreeCAD folder>")
    if os.name == "nt":
        ac = find_autocad_path()
        add("AutoCAD", "ok" if ac else "missing", ac or "not found (optional: DWG import/export)",
            "" if ac else "Optional. Install AutoCAD, or set AGENTCAD_ACCORECONSOLE to accoreconsole.exe")
    else:
        add("AutoCAD", "skip", "Windows only (optional: DWG import/export)")
    detected = detect_clients()
    for client in CLIENTS:
        label = f"{LABELS[client]} config"
        place, entry = _client_entry(client, ws)
        if entry is not None:
            problem = _check_entry(entry)
            add(label, "missing" if problem else "ok", f"{place}" + (f": {problem}" if problem else ""),
                f"Run agentcad setup --client {client}" if problem else "")
        elif detected[client]:
            add(label, "missing", "installed, but AgentCAD is not configured", f"Run agentcad setup --client {client}")
        else:
            add(label, "skip", "app not found")
    ok = all(c["status"] == "ok" for c in checks if c["required"])
    return {"ok": ok, "checks": checks, "self_cmd": self_command(info)}


def render_doctor(r: dict[str, Any]) -> str:
    L = ["AgentCAD doctor", ""]
    for c in r["checks"]:
        L.append(f"  {c['status']:<8} {c['name']:<22} {c['detail']}")
        if c["fix"] and c["status"] != "ok":
            fix = c["fix"].replace("agentcad setup", r["self_cmd"] + " setup")
            L.append(f"  {'':<8} {'':<22} fix: {fix}")
    L += ["", "All required parts are working." if r["ok"] else "Some required parts are missing: see the fixes above."]
    return "\n".join(L)
