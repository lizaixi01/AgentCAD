"""Minimal HTTP JSON API (stdlib only), sharing ``Runtime`` with CLI and MCP.

    GET  /v1/tools            -> tool names
    POST /v1/<tool>  {kwargs} -> the tool's JSON envelope
"""
from __future__ import annotations

import inspect
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .policy import Policy
from .service import TOOLS, Runtime

MAX_BODY = 8 * 1024 * 1024


def make_handler(rt: Runtime):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj) -> None:
            data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/v1/tools":
                self._send(200, {"ok": True, "tools": {n: list(inspect.signature(f).parameters)[1:] for n, f in TOOLS.items()}})
            else:
                self._send(404, {"ok": False, "error": {"code": "NOT_FOUND", "category": "input", "message": self.path}})

        def do_POST(self):  # noqa: N802
            name = self.path.strip("/").removeprefix("v1/")
            if name not in TOOLS:
                return self._send(404, {"ok": False, "error": {"code": "UNKNOWN_TOOL", "category": "input",
                                                                "message": f"No tool {name!r}"}})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"ok": False, "error": {"code": "BODY_TOO_LARGE", "category": "policy", "message": str(n)}})
            try:
                kwargs = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(kwargs, dict):
                    raise ValueError("body must be a JSON object")
            except ValueError as exc:
                return self._send(400, {"ok": False, "error": {"code": "INVALID_JSON", "category": "input", "message": str(exc)}})
            try:
                res = getattr(rt, name)(**kwargs)
            except TypeError as exc:
                return self._send(400, {"ok": False, "error": {"code": "INVALID_ARGUMENTS", "category": "input", "message": str(exc)}})
            self._send(200, res)

        def log_message(self, fmt, *args):  # keep stdout clean
            pass

    return Handler


def serve(policy: Policy, host: str = "127.0.0.1", port: int = 8765) -> None:
    srv = ThreadingHTTPServer((host, port), make_handler(Runtime(policy)))
    print(json.dumps({"ok": True, "listening": f"http://{host}:{port}/v1"}), flush=True)
    srv.serve_forever()
