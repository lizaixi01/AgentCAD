"""Setup wizard: ``agentcad setup --gui`` does what ``agentcad setup`` does, in a local web page instead of a terminal.

The double-click installers (installer/) start it, so people who never open a terminal get big buttons, a progress
bar and plain sentences. It runs ``install.setup`` in a thread and the page polls its state.

    GET  /                  the page (viewer_static/setup.html)
    GET  /api/info          workspace folder, apps (found on this computer or not), dry run
    POST /api/start         {"clients": [...]}: run setup for these apps
    GET  /api/state         {"phase": ready|running|done|error, "steps": [...], "result": ...}
    POST /api/open-folder   open the workspace folder in Explorer / Finder
    POST /api/quit          stop the wizard (the installer window then closes)

It listens on 127.0.0.1 only and checks the Host header (as the viewer does). Every /api call must carry the random
token of the URL it opened (header X-AgentCAD-Token), so another web page cannot start a setup.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import install
from .errors import AgentCADError
from .viewer import LOOPBACK, STATIC, _host_name, _server

IDLE_EXIT = 3600.0  # nobody has asked anything for an hour: the page was closed, stop
STATIC_FILES = {"/": ("setup.html", "text/html; charset=utf-8"), "/logo.svg": ("logo.svg", "image/svg+xml")}


class Wizard:
    def __init__(self, root: str | None = None, *, dry_run: bool = False, launcher: str = "auto",
                 source: str | None = None, freecad: str | None = None, name: str = install.NAME,
                 read_only: bool = False, allow_scripts: bool = False,
                 runner: install.Runner | None = None, host: str = "127.0.0.1", port: int = 0) -> None:
        self.root = install.workspace_root(root)
        self.opts = dict(launcher=launcher, source=source, freecad=freecad, dry_run=dry_run, name=name,
                         read_only=read_only, allow_scripts=allow_scripts, runner=runner)
        self.token = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"phase": "ready", "steps": [], "result": None, "error": None}
        self.last_seen = time.monotonic()
        self.done = threading.Event()
        self.httpd = _server(host)((host, port), _handler(self))
        self.httpd.daemon_threads = True
        p = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{p}/?t={self.token}"

    # --- what the page asks for -----------------------------------------------------------------------------------
    def info(self) -> dict[str, Any]:
        found = install.detect_clients()
        return {"workspace": str(self.root), "dry_run": self.opts["dry_run"], "platform": sys.platform,
                "apps": [{"id": c, "label": install.LABELS[c], "found": found[c]} for c in install.CLIENTS]}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))

    def start(self, clients: list[str]) -> dict[str, Any]:
        clients = [c for c in dict.fromkeys(clients) if c in install.CLIENTS]
        if not clients:
            return {"ok": False, "error": {"code": "NO_APP", "message": "Choose at least one app"}}
        with self.lock:
            if self.state["phase"] == "running":
                return {"ok": False, "error": {"code": "BUSY", "message": "Setup is already running"}}
            steps = ["workspace", "freecad", "autocad", *clients]
            self.state = {"phase": "running", "result": None, "error": None,
                          "steps": [{"id": s, "state": "wait", "info": {}} for s in steps]}
        threading.Thread(target=self._run, args=(clients,), name="agentcad-setup", daemon=True).start()
        return {"ok": True}

    def _progress(self, step: str, state: str, info: dict[str, Any]) -> None:
        with self.lock:
            for s in self.state["steps"]:
                if s["id"] == step:
                    s["state"], s["info"] = state, {k: v for k, v in info.items() if k != "commands"}

    def _run(self, clients: list[str]) -> None:
        try:
            res = install.setup(clients, self.root, progress=self._progress, **self.opts)
            result = res.to_dict()
            result.pop("server", None)  # the command line and env: not for this page
            for c in result["clients"]:
                c.pop("commands", None)
            with self.lock:
                self.state.update(phase="done" if res.ok else "error", result=result)
        except AgentCADError as exc:
            with self.lock:
                self.state.update(phase="error", error={"code": exc.code, "message": exc.message, "hint": exc.hint})
        except Exception as exc:  # noqa: BLE001 - show it on the page instead of a dead progress bar
            with self.lock:
                self.state.update(phase="error", error={"code": "SETUP_FAILED", "message": str(exc)})

    def open_folder(self) -> dict[str, Any]:
        """Open the workspace (only that folder) in the file manager. A dry run never creates it."""
        if self.opts["dry_run"] and not self.root.is_dir():
            return {"ok": False, "error": {"code": "NO_FOLDER", "message": f"demo mode did not create {self.root}"}}
        try:
            install.open_folder(self.root)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": {"code": "OPEN_FAILED", "message": str(exc)}}

    # --- running ---------------------------------------------------------------------------------------------------
    def start_background(self) -> "Wizard":
        threading.Thread(target=self.httpd.serve_forever, name="agentcad-setup-gui", daemon=True).start()
        return self

    def serve(self, open_browser: bool = True) -> None:
        self.start_background()
        print(json.dumps({"ok": True, "setup": self.url}), flush=True)
        if open_browser:
            import webbrowser
            webbrowser.open(self.url)
        try:
            while not self.done.wait(5):
                if time.monotonic() - self.last_seen > IDLE_EXIT and self.state["phase"] != "running":
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self.done.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def _handler(wiz: Wizard):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _refused(self) -> bool:
            if _host_name(self.headers.get("Host")) not in LOOPBACK:
                self._json({"ok": False, "error": {"code": "HOST_NOT_ALLOWED", "message": "localhost only"}}, 403)
                return True
            path = urlparse(self.path).path
            if path.startswith("/api/") and not secrets.compare_digest(self.headers.get("X-AgentCAD-Token", ""),
                                                                      wiz.token):
                self._json({"ok": False, "error": {"code": "BAD_TOKEN", "message": "Open the link the installer "
                                                                                    "printed"}}, 403)
                return True
            wiz.last_seen = time.monotonic()
            return False

        def do_GET(self):  # noqa: N802
            if self._refused():
                return
            path = urlparse(self.path).path
            if path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            if path == "/api/info":
                return self._json(wiz.info())
            if path == "/api/state":
                return self._json(wiz.snapshot())
            self._json({"ok": False, "error": {"code": "NOT_FOUND"}}, 404)

        def do_POST(self):  # noqa: N802
            if self._refused():
                return
            path = urlparse(self.path).path
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 65536)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json({"ok": False, "error": {"code": "BAD_JSON"}}, 400)
            if path == "/api/start":
                clients = body.get("clients") if isinstance(body, dict) else None
                return self._json(wiz.start([c for c in clients or [] if isinstance(c, str)]))
            if path == "/api/open-folder":
                return self._json(wiz.open_folder())
            if path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=wiz.done.set, daemon=True).start()
                return
            self._json({"ok": False, "error": {"code": "NOT_FOUND"}}, 404)

        def log_message(self, fmt, *args):  # keep the installer window clean
            pass

    return Handler
