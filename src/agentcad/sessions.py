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

# This process's session; progress events and journal records carry its client and label.
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
    """What a progress event or journal record says about who made it: {} until a client is known."""
    out = {k: CURRENT[k] for k in ("client", "label") if CURRENT.get(k)}
    if out and CURRENT.get("pid"):
        out["session"] = CURRENT["pid"]
    return out


class Session:
    def __init__(self, policy: Policy) -> None:
        self.path = policy.root / STATE_DIR / DIR / f"{os.getpid()}.json"
        now = round(time.time(), 3)
        CURRENT.clear()
        CURRENT.update(pid=os.getpid(), client=None, client_raw=None, version=None, label=None, started=now,
                       last_seen=now, last_tool=None, drawing=None)
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


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
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
            s = json.loads(f.read_text("utf-8"))
            pid = int(s.get("pid") or f.stem)
        except (OSError, ValueError, TypeError):
            continue
        if alive(pid):
            out.append({k: s.get(k) for k in ("pid", "client", "version", "label", "started", "last_seen",
                                              "last_tool", "drawing")})
        else:
            try:
                f.unlink()
            except OSError:
                pass
    return sorted(out, key=lambda s: -(s.get("last_seen") or 0))
