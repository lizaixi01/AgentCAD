"""Which assistants are connected: one small file per MCP server process, so the live viewer can say "Claude Code is
connected" and who made each change.

An MCP client (Claude Code, Codex, Claude Desktop, Cursor) starts one server process per conversation and names
itself when it connects (clientInfo). MCP carries no conversation title, so the assistant may give one through
agentcad_status(label=...).

    <root>/.agentcad/sessions/<pid>.json   {"pid", "client", "client_raw", "version", "label", "started",
                                            "last_seen", "last_tool", "drawing"}

A file is removed when its server exits; one left by a crash is ignored once its process is gone.
"""
from __future__ import annotations

import atexit
import json
import os
import time
from pathlib import Path
from typing import Any

from .policy import STATE_DIR, Policy

DIR = "sessions"
CLIENTS = (("claude-code", "Claude Code"), ("codex", "Codex"), ("cursor", "Cursor"), ("claude", "Claude Desktop"),
           ("vscode", "VS Code"), ("windsurf", "Windsurf"))

# This process's session; progress events and journal records carry its client and label (tag).
CURRENT: dict[str, Any] = {}


def friendly(raw: str | None) -> str | None:
    """The app's name as people know it, from the clientInfo name it sends (e.g. "claude-code" -> "Claude Code")."""
    if not raw:
        return None
    low = raw.lower()
    for key, name in CLIENTS:
        if key in low:
            return name
    return raw[:40]


def tag() -> dict[str, Any]:
    """What a progress event or journal record says about who made it: {} until a client is known. ("label" is
    taken: a journal record's label describes the change; this is the conversation's.)"""
    out: dict[str, Any] = {}
    if CURRENT.get("client"):
        out["client"] = CURRENT["client"]
    if CURRENT.get("label"):
        out["conversation"] = CURRENT["label"]
    if out and CURRENT.get("pid"):
        out["session"] = CURRENT["pid"]
    return out


class Session:
    def __init__(self, policy: Policy) -> None:
        self.path = policy.root / STATE_DIR / DIR / f"{os.getpid()}.json"
        now = round(time.time(), 3)
        CURRENT.clear()
        CURRENT.update(pid=os.getpid(), created=created(os.getpid()), client=None, client_raw=None, version=None,
                       label=None, started=now, last_seen=now, last_tool=None, drawing=None)
        self._written = 0.0
        self.write(force=True)
        atexit.register(self.close)

    def note(self, client_raw: str | None = None, version: str | None = None, tool: str | None = None,
             drawing: str | None = None, label: str | None = None) -> None:
        """Record what this request tells about the client. Writes at most every 2 s unless something changed."""
        changed = False
        if client_raw and client_raw != CURRENT.get("client_raw"):
            CURRENT.update(client_raw=client_raw, client=friendly(client_raw), version=version)
            changed = True
        if label is not None and label.strip()[:60] != CURRENT.get("label"):
            CURRENT["label"] = label.strip()[:60] or None
            changed = True
        if tool:
            CURRENT["last_tool"] = tool
        if drawing:
            CURRENT["drawing"] = drawing
        CURRENT["last_seen"] = round(time.time(), 3)
        self.write(force=changed)

    def write(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._written < 2:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(CURRENT, ensure_ascii=False), "utf-8")
            os.replace(tmp, self.path)
            self._written = time.monotonic()
        except OSError:  # a convenience: never a reason to fail a call
            pass

    def close(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


def created(pid: int) -> int | None:
    """When the process started, as the OS counts it (Windows: FILETIME; Linux: clock ticks since boot), or None.
    With the pid it tells a session's server from an unrelated process that later got the same pid."""
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                times = [ctypes.c_ulonglong() for _ in range(4)]
                ok = k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times])
                return int(times[0].value) if ok else None
            finally:
                k32.CloseHandle(h)
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[19])  # field 22, starttime
    except (OSError, ValueError, IndexError, AttributeError):
        return None  # macOS has no /proc: the pid alone decides


def alive(pid: int, started: int | None = None) -> bool:
    """Is ``pid`` running, and (when ``started`` is known) still the process that wrote the session file?"""
    if pid <= 0:
        return False
    if started is not None:
        now = created(pid)
        if now is not None and now != started:
            return False  # the pid was reused after the server died without removing its file
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:  # access denied: it runs, as another user or elevated (an assistant started as admin)
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def list_sessions(root: Path) -> list[dict[str, Any]]:
    """The sessions whose server is still running, most recently active first; stale files are removed."""
    out = []
    folder = root / STATE_DIR / DIR
    for f in folder.glob("*.json") if folder.is_dir() else []:
        try:
            s = json.loads(f.read_text("utf-8-sig"))
            pid = int(s.get("pid") or f.stem)
        except (OSError, ValueError, TypeError):
            continue
        if alive(pid, s.get("created")):
            out.append({k: s.get(k) for k in ("pid", "client", "version", "label", "started", "last_seen",
                                              "last_tool", "drawing")})
        else:
            try:
                f.unlink()
            except OSError:
                pass
    return sorted(out, key=lambda s: -(s.get("last_seen") or 0))
