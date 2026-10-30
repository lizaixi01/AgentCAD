"""Minimal HTTP JSON API (stdlib only), sharing ``Runtime`` with CLI and MCP.

    GET  /v1/tools            -> tool names
    POST /v1/<tool>  {kwargs} -> the tool's JSON envelope
"""
from __future__ import annotations

import inspect
import ipaddress
import json
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .errors import policy_error
from .policy import Policy
from .service import TOOLS, Runtime

MAX_BODY = 8 * 1024 * 1024
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_handler(rt: Runtime, *, token: str | None = None,
                 allowed_hosts: frozenset[str] | None = LOOPBACK_HOSTS):
    # Runtime and native CAD libraries are shared by request threads.
    execution_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def _send(self, code: int, obj) -> None:
            data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _refuse(self, status, code, message, category="policy"):
            # Closing a socket with unread request bytes can reset it on Windows,
            # discarding the JSON refusal. Drain only a bounded body, with a short
            # timeout; authorization still precedes parsing or Runtime execution.
            if self.command == "POST":
                self.connection.settimeout(0.2)
                try:
                    raw_length = self.headers.get("Content-Length", "")
                    size = int(raw_length) if raw_length.isascii() and raw_length.isdigit() and len(raw_length) <= 10 else 0
                    if 0 < size <= MAX_BODY:
                        self.rfile.read(size)
                    else:
                        self.rfile.read1(8192)
                except (OSError, ValueError):
                    pass
                finally:
                    self.connection.settimeout(10)
            self._send(status, {"ok": False, "error": {"code": code, "category": category, "message": message}})
            return False

        def _authorized(self):
            hosts = self.headers.get_all("Host", [])
            try:
                authority = urlsplit("//" + hosts[0]) if len(hosts) == 1 else None
                hostname = authority.hostname if authority else None
                valid = (hostname and not authority.username and not authority.password
                         and not authority.path and not authority.query and not authority.fragment)
                if authority:
                    authority.port  # validate the optional port
            except ValueError:
                valid = False
            if not valid or allowed_hosts is not None and hostname not in allowed_hosts:
                return self._refuse(403, "HOST_NOT_ALLOWED", "Host is not allowed for this API")
            # This is a native JSON API, with no browser/CORS credentials contract.
            if self.headers.get("Origin") is not None:
                return self._refuse(403, "ORIGIN_NOT_ALLOWED", "Browser-origin requests are not enabled")
            if token is not None:
                values = self.headers.get_all("Authorization", [])
                if len(values) != 1 or not secrets.compare_digest(values[0].encode(), ("Bearer " + token).encode()):
                    return self._refuse(401, "UNAUTHORIZED", "A valid bearer token is required")
            return True

        def do_GET(self):  # noqa: N802
            if not self._authorized():
                return
            if self.path.rstrip("/") == "/v1/tools":
                self._send(200, {"ok": True, "tools": {n: list(inspect.signature(f).parameters)[1:] for n, f in TOOLS.items()}})
            else:
                self._send(404, {"ok": False, "error": {"code": "NOT_FOUND", "category": "input", "message": self.path}})

        def do_POST(self):  # noqa: N802
            if not self._authorized():
                return
            if self.headers.get_content_type() != "application/json":
                return self._refuse(415, "CONTENT_TYPE_REQUIRED", "Use application/json")
            name = self.path.strip("/").removeprefix("v1/")
            if name not in TOOLS:
                return self._refuse(404, "UNKNOWN_TOOL", f"No tool {name!r}", category="input")
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                return self._refuse(400, "INVALID_BODY_LENGTH", "One nonnegative Content-Length is required")
            if len(lengths[0]) > 10:
                return self._refuse(413, "BODY_TOO_LARGE", "Request exceeds the body limit")
            n = int(lengths[0])
            if n > MAX_BODY:
                return self._refuse(413, "BODY_TOO_LARGE", str(n))
            try:
                raw = self.rfile.read(n)
                if len(raw) != n:
                    raise ValueError("incomplete request body")
                kwargs = json.loads(raw or b"{}")
                if not isinstance(kwargs, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, TimeoutError) as exc:
                return self._send(400, {"ok": False, "error": {"code": "INVALID_JSON", "category": "input", "message": str(exc)}})
            try:
                # Reject signature errors before entering Runtime's exception envelope.
                inspect.signature(getattr(rt, name)).bind(**kwargs)
                with execution_lock:
                    res = getattr(rt, name)(**kwargs)
            except TypeError as exc:
                return self._send(400, {"ok": False, "error": {"code": "INVALID_ARGUMENTS", "category": "input", "message": str(exc)}})
            self._send(200, res)

        def log_message(self, fmt, *args):  # keep stdout clean
            pass

    return Handler


def make_server(policy: Policy, host: str = "127.0.0.1", port: int = 8765,
                *, token: str | None = None) -> ThreadingHTTPServer:
    if token is not None and (len(token) < 32 or not token.isascii() or not token.isprintable()
                              or any(c.isspace() for c in token)):
        raise policy_error("HTTP_TOKEN_INVALID", "HTTP bearer token must contain at least 32 non-whitespace ASCII characters")
    if not is_loopback(host) and token is None:
        raise policy_error("HTTP_AUTH_REQUIRED", "Non-loopback HTTP requires AGENTCAD_HTTP_TOKEN",
                           hint="Bind to 127.0.0.1, or configure a bearer token and a trusted TLS proxy")
    allowed = LOOPBACK_HOSTS | {host.lower()} if is_loopback(host) else None
    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
        daemon_threads = True
    return Server((host, port), make_handler(Runtime(policy), token=token, allowed_hosts=allowed))


def serve(policy: Policy, host: str = "127.0.0.1", port: int = 8765) -> None:
    srv = make_server(policy, host, port, token=os.environ.get("AGENTCAD_HTTP_TOKEN"))
    print(json.dumps({"ok": True, "listening": f"http://{host}:{port}/v1"}), flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
