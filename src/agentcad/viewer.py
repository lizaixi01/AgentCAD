"""Live viewer: a local web page that shows a workspace's drawings and parts as agents change them (stdlib only).

    agentcad viewer --root <dir> [--port 8770]

It only reads the workspace. Every commit goes through the store (checkpoint, atomic replace, journal), so a
thread polls each drawing's file and journal (``stat`` only, no open) and pushes a change event to the page over
Server-Sent Events. Versions are addressed by sha256: a commit's journal record carries the sha of the file it
wrote, and each checkpoint the sha of the content it holds, so any committed version still on disk can be shown.
Files are read into a content-addressed cache outside the workspace before they are parsed or handed to FreeCAD.

    GET /                         the page (viewer_static/index.html)
    GET /api/drawings             drawings (.dxf) and parts (.FCStd) under the root
    GET /api/timeline?path=       journal records, each with the version it produced
    GET /api/svg?path=&v=&diff=1&hide=L1,L2    2D render (diff: added green, modified orange, rest grey)
    GET /api/layers?path=&v=      layers with entity counts
    GET /api/diff?path=&v=        what the commit that made version v changed (as get_diff reports it)
    GET /api/mesh?path=&v=        3D part: triangles and edges (JSON) for three.js
    GET /api/png?path=&v=         3D part: the shaded preview grid (fallback when WebGL is unavailable)
    GET /api/events               SSE: {"drawing", "kind": changed|added|removed, "id"}
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import AgentCADError, input_error
from .policy import STATE_DIR, Policy
from .store import DrawingStore, read_dxf, sha256_file

STATIC = Path(__file__).resolve().parent / "viewer_static"
SUFFIXES = (".dxf", ".fcstd")
SKIP_DIRS = {STATE_DIR, ".git", ".venv", "venv", "node_modules", "__pycache__", ".claude"}
MAX_FILES = 2000
ROUTES = {"/api/timeline", "/api/layers", "/api/diff", "/api/svg", "/api/mesh", "/api/png"}
INFO_FILE = "viewer.json"  # <root>/.agentcad/viewer.json: where a running viewer listens (see viewer_url)
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
COLORS = {"added": "#16a34a", "modified": "#ea580c", "other": "#b8bcc4"}
EMPTY_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600"><rect width="1000" height="600" '
             'fill="#ffffff"/><text x="500" y="300" text-anchor="middle" font-family="sans-serif" font-size="24" '
             'fill="#9aa1ad">nothing to show</text></svg>')


def _host_name(host: str | None) -> str | None:
    """Host header without the port: 'localhost:8770' -> 'localhost', '[::1]:8770' -> '::1'."""
    if not host:
        return None
    try:
        return urlparse(f"//{host}").hostname
    except ValueError:
        return None


def _retry(fn):
    """Windows refuses to open a file while the store is replacing it (PermissionError); that lasts milliseconds,
    so the viewer's reads try again instead of failing the request."""
    def wrapper(*args, **kwargs):
        deadline = time.monotonic() + 2.0
        while True:
            try:
                return fn(*args, **kwargs)
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    return wrapper


def _is_part(rel: str) -> bool:
    return rel.lower().endswith(".fcstd")


class Workspace:
    """Read-only access to the drawings under a root and to their committed versions."""

    def __init__(self, policy: Policy, cache_dir: Path | None = None) -> None:
        self.policy = policy
        root_key = hashlib.sha256(str(policy.root).encode()).hexdigest()[:12]
        self.cache = cache_dir or Path(tempfile.gettempdir()) / "agentcad-viewer" / root_key
        self.cache.mkdir(parents=True, exist_ok=True)
        self._sha_memo: dict[str, tuple[tuple[int, int], str]] = {}
        self._results: OrderedDict[tuple, Any] = OrderedDict()
        self._locks: dict[tuple, threading.Lock] = {}
        self._guard = threading.Lock()

    # --- discovery ----------------------------------------------------------------------------
    @_retry
    def list_drawings(self) -> list[str]:
        out: list[str] = []
        root = self.policy.root
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
            for f in sorted(files):
                if f.lower().endswith(SUFFIXES) and not f.endswith(".agentcad-tmp"):
                    out.append((Path(d) / f).relative_to(root).as_posix())
                    if len(out) >= MAX_FILES:
                        return out
        return out

    def store(self, rel: str) -> DrawingStore:
        p = self.policy.resolve(rel, must_exist=False, suffixes=(".dxf", ".fcstd"))
        if _is_part(rel):
            from .part.service import read_fcstd
            return DrawingStore(self.policy, p, reader=read_fcstd)
        return DrawingStore(self.policy, p)

    def signature(self, rel: str) -> tuple:
        """Cheap change detector: stat of the file and of the store's journal and head (nothing is opened)."""
        st = self.store(rel)
        sig = []
        for f in (st.path, st.journal_path, st.head_path):
            try:
                s = f.stat()
                sig.append((s.st_mtime_ns, s.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    # --- versions ---------------------------------------------------------------------------------
    def current_sha(self, st: DrawingStore) -> str | None:
        try:
            s = st.path.stat()
        except OSError:
            return None
        key = (s.st_mtime_ns, s.st_size)
        memo = self._sha_memo.get(str(st.path))
        if memo and memo[0] == key:
            return memo[1]
        sha = sha256_file(st.path)
        self._sha_memo[str(st.path)] = (key, sha)
        return sha

    def versions(self, st: DrawingStore) -> dict[str, Path]:
        """sha256 -> a file on disk holding exactly that content (a checkpoint or the current file)."""
        out = {c["sha256"]: st.cp_dir / f"{c['id']}{st.ext}" for c in st.list_checkpoints() if c.get("sha256")}
        cur = self.current_sha(st)
        if cur:
            out[cur] = st.path
        return out

    @_retry
    def timeline(self, rel: str) -> dict[str, Any]:
        from .service import _journal_line
        st = self.store(rel)
        have = self.versions(st)
        cps = {c["id"]: c.get("sha256") for c in st.list_checkpoints()}
        records = []
        for r in st.read_journal():
            line = _journal_line(r)
            sha = r.get("sha256") if r.get("ok") else None
            if sha:
                line["version"] = sha
                line["available"] = sha in have
                before = r.get("checkpoint_before")
                if before and cps.get(before):
                    line["before"] = cps[before]
            records.append(line)
        cur = self.current_sha(st)
        return {"drawing": rel, "kind": "part" if _is_part(rel) else "drawing", "current": cur,
                "modified_outside_runtime": bool(cur and st.head().get("sha256") and cur != st.head()["sha256"]),
                "records": records}

    @_retry
    def snapshot(self, rel: str, version: str | None) -> tuple[str, Path]:
        """(sha, cached copy) of a version; None or 'current' = the file as it is now. The copy lives outside the
        workspace and is never changed, so parsing it cannot race a commit."""
        st = self.store(rel)
        have = self.versions(st)
        if version in (None, "", "current"):
            version = self.current_sha(st)
            if version is None:
                raise input_error("FILE_NOT_FOUND", f"{rel} does not exist")
        if version not in have:
            raise input_error("VERSION_NOT_FOUND", f"{rel} has no stored version {version[:12]}",
                              hint="Older versions exist only as checkpoints")
        dst = self.cache / f"{version}{st.ext}"
        with self._guard if not dst.is_file() else nullcontext():  # created once: a cached copy is never replaced
            if not dst.is_file():
                data = have[version].read_bytes()  # one short read: the store may replace the file next
                if hashlib.sha256(data).hexdigest() != version:
                    raise AgentCADError("VERSION_CHANGED", f"{rel} changed while it was read", category="file",
                                        retryable=True)
                tmp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex[:8]}.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, dst)
        return version, dst

    def _memo(self, key: tuple, fn):
        """Results depend only on content shas, so they are cached (LRU) and computed once per key."""
        with self._guard:
            if key in self._results:
                self._results.move_to_end(key)
                return self._results[key]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                if key in self._results:
                    return self._results[key]
            val = fn()
            with self._guard:
                self._results[key] = val
                while len(self._results) > 256:
                    self._results.popitem(last=False)
                self._locks.pop(key, None)
            return val

    # --- 2D -------------------------------------------------------------------------------------------
    def _doc(self, rel: str, version: str | None):
        sha, f = self.snapshot(rel, version)
        return sha, read_dxf(f, self.policy)

    @_retry
    def layers(self, rel: str, version: str | None) -> dict[str, Any]:
        sha, doc = self._doc(rel, version)
        counts: dict[str, int] = {}
        for e in doc.modelspace():
            counts[e.dxf.layer] = counts.get(e.dxf.layer, 0) + 1
        return {"version": sha, "layers": [{"name": l.dxf.name, "entities": counts.get(l.dxf.name, 0),
                                            "off": l.is_off() or l.is_frozen()} for l in doc.layers]}

    def _change_sets(self, rel: str, sha: str, before: str | None) -> dict[str, Any] | None:
        if not before:
            return None
        return self._memo(("diff2d", sha, before), lambda: self._diff2d(rel, sha, before))

    def _diff2d(self, rel: str, sha: str, before: str) -> dict[str, Any]:
        from .service import diff_docs
        old = read_dxf(self.snapshot(rel, before)[1], self.policy)
        new = read_dxf(self.snapshot(rel, sha)[1], self.policy)
        d = diff_docs(old, new)
        brief = {k: [{f: e[f] for f in ("id", "type", "layer", "tag", "layout") if e.get(f) is not None}
                     for e in d[k]] for k in ("added", "deleted")}
        return {"summary": d["summary"], "added": brief["added"], "deleted": brief["deleted"],
                "modified": d["modified"], "layers": d["layers"]}

    @_retry
    def svg(self, rel: str, version: str | None, diff: bool = False, hide: tuple[str, ...] = ()) -> str:
        sha, _ = self.snapshot(rel, version)
        before = self.before(rel, sha) if diff else None
        return self._memo(("svg", sha, before, tuple(sorted(hide))), lambda: self._svg(rel, sha, before, hide))

    def _svg(self, rel: str, sha: str, before: str | None, hide: tuple[str, ...]) -> str:
        from ezdxf import bbox
        from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
        from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
        from ezdxf.math import BoundingBox2d
        _, doc = self._doc(rel, sha)
        msp = doc.modelspace()
        changes = self._change_sets(rel, sha, before)
        added = {e["id"] for e in changes["added"]} if changes else set()
        modified = {e["id"] for e in changes["modified"]} if changes else set()
        hidden = set(hide)

        def override(entity, props):
            if props.layer in hidden:
                props.is_visible = False
            if changes is not None:
                h = entity.dxf.handle
                props.color = COLORS["added"] if h in added else COLORS["modified"] if h in modified \
                    else COLORS["other"]

        backend = svg.SVGBackend()
        front = Frontend(RenderContext(doc), backend,
                         config=Configuration(background_policy=BackgroundPolicy.WHITE))
        front.push_property_override_function(override)
        front.draw_layout(msp)
        page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(5))
        box = None
        try:  # hiding layers must not re-frame the drawing
            ext = bbox.extents(msp, fast=True)
            if ext.has_data and ext.size.x > 0 and ext.size.y > 0:
                box = BoundingBox2d([ext.extmin.vec2, ext.extmax.vec2])
        except Exception:
            box = None
        try:
            return backend.get_string(page, render_box=box, xml_declaration=False)
        except ValueError:  # nothing visible (a new drawing, or every layer hidden)
            return EMPTY_SVG

    @_retry
    def before(self, rel: str, sha: str) -> str | None:
        """The version the last commit that produced ``sha`` started from (None for a creation)."""
        st = self.store(rel)
        cps = {c["id"]: c.get("sha256") for c in st.list_checkpoints()}
        for r in reversed(st.read_journal()):
            if r.get("ok") and r.get("sha256") == sha:
                return cps.get(r.get("checkpoint_before")) if r.get("checkpoint_before") else None
        return None

    @_retry
    def diff(self, rel: str, version: str | None) -> dict[str, Any]:
        sha, _ = self.snapshot(rel, version)
        before = self.before(rel, sha)
        if before is None:
            return {"version": sha, "before": None, "note": "no earlier version (created here, or edited outside "
                                                            "the runtime)"}
        if before not in self.versions(self.store(rel)):
            return {"version": sha, "before": before, "note": "the earlier version is no longer stored"}
        if _is_part(rel):
            from .part.service import compare
            d = self._memo(("diff3d", sha, before),
                           lambda: compare(self._summary(rel, before), self._summary(rel, sha)))
        else:
            d = self._change_sets(rel, sha, before)
        return {"version": sha, "before": before, **d}

    # --- 3D (FreeCAD) -------------------------------------------------------------------------------
    def _fc(self, job: dict[str, Any], src: Path, out: Path | None = None) -> dict[str, Any]:
        from .backends import freecad
        res = freecad.run(job, inputs={"input": src}, outputs={"output": out} if out else None)
        if not res.get("ok"):
            e = res.get("error") or {}
            raise AgentCADError(e.get("code", "FREECAD_ERROR"), e.get("message", "FreeCAD job failed"),
                                category="geometry" if e.get("category") == "geometry" else "internal",
                                hint=e.get("hint"))
        return res

    def _summary(self, rel: str, sha: str) -> dict[str, Any]:
        src = self.snapshot(rel, sha)[1]
        return self._memo(("summary", sha), lambda: self._fc({"action": "summary", "detail": True}, src)["summary"])

    @_retry
    def mesh(self, rel: str, version: str | None) -> Path:
        sha, src = self.snapshot(rel, version)
        out = self.cache / f"{sha}.mesh.json"
        if not out.is_file():
            self._memo(("mesh", sha), lambda: self._fc({"action": "mesh"}, src, out))
        return out

    @_retry
    def png(self, rel: str, version: str | None) -> Path:
        sha, src = self.snapshot(rel, version)
        out = self.cache / f"{sha}.png"
        if not out.is_file():
            self._memo(("png", sha), lambda: self._fc({"action": "render", "views": ["iso", "front", "right", "top"],
                                                       "size": 512}, src, out))
        return out


class ChangeFeed:
    """Polls the workspace and keeps a numbered list of change events; waiters block on ``wait``."""

    def __init__(self, ws: Workspace, interval: float = 0.4, rescan: float = 1.0) -> None:
        self.ws = ws
        self.interval = interval
        self.rescan = rescan
        self.events: list[dict[str, Any]] = []
        self.cond = threading.Condition()
        self.sigs: dict[str, tuple] = {}
        self.drawings: list[str] = []
        self._last_scan = 0.0
        self._stop = threading.Event()
        self.poll()  # baseline: what exists now is not news

    def _emit(self, drawing: str, kind: str) -> None:
        with self.cond:
            ev = {"id": len(self.events) + 1, "drawing": drawing, "kind": kind, "ts": time.time()}
            self.events.append(ev)
            del self.events[:-1000]
            self.cond.notify_all()

    @property
    def last_id(self) -> int:
        with self.cond:
            return self.events[-1]["id"] if self.events else 0

    def poll(self) -> None:
        first = not self._last_scan
        if first or time.monotonic() - self._last_scan >= self.rescan:
            self.drawings = self.ws.list_drawings()
            self._last_scan = time.monotonic()
        now: dict[str, tuple] = {}
        for rel in self.drawings:
            try:
                sig = self.ws.signature(rel)
            except AgentCADError:
                continue
            if sig[0] is not None:  # the file exists
                now[rel] = sig
        if not first:
            for rel, sig in now.items():
                old = self.sigs.get(rel)
                if old != sig:
                    self._emit(rel, "added" if old is None else "changed")
            for rel in self.sigs.keys() - now.keys():
                self._emit(rel, "removed")
        self.sigs = now

    def since(self, last: int) -> list[dict[str, Any]]:
        with self.cond:
            return [e for e in self.events if e["id"] > last]

    def wait(self, last: int, timeout: float) -> list[dict[str, Any]]:
        with self.cond:
            self.cond.wait_for(lambda: bool(self.events) and self.events[-1]["id"] > last, timeout)
            return [e for e in self.events if e["id"] > last]

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll()
            except Exception:  # a transient filesystem error must not stop the feed
                pass

    def start(self) -> "ChangeFeed":
        threading.Thread(target=self.run, name="agentcad-viewer-feed", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()


def make_handler(ws: Workspace, feed: ChangeFeed, allowed_hosts: frozenset[str] | None = LOOPBACK):
    """``allowed_hosts``: host names the Host header may carry (None = any). A page on another site can point its
    own name at 127.0.0.1 (DNS rebinding); its requests then carry that name, and are refused."""
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            if allowed_hosts is not None and _host_name(self.headers.get("Host")) not in allowed_hosts:
                return self._json({"ok": False, "error": {"code": "HOST_NOT_ALLOWED", "category": "policy",
                                                          "message": "The viewer answers only on localhost"}}, 403)
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            path, v = q.get("path", ""), q.get("v")
            # a pinned version never changes; "current" does
            pinned = bool(v and v != "current")
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/api/ping":
                    return self._json({"ok": True, "root": str(ws.policy.root)})
                if u.path == "/api/drawings":
                    return self._json({"ok": True, "root": str(ws.policy.root), "drawings": [
                        {"path": r, "kind": "part" if _is_part(r) else "drawing"} for r in ws.list_drawings()],
                        "last_event": feed.last_id})
                if u.path == "/api/events":
                    return self._events(int(self.headers.get("Last-Event-ID") or q.get("since") or feed.last_id))
                if u.path not in ROUTES:
                    return self._json({"ok": False, "error": {"code": "NOT_FOUND", "category": "input",
                                                              "message": u.path}}, 404)
                if not path:
                    raise input_error("MISSING_PATH", "path= is required")
                if u.path == "/api/timeline":
                    return self._json({"ok": True, **ws.timeline(path)})
                if u.path == "/api/layers":
                    return self._json({"ok": True, **ws.layers(path, v)})
                if u.path == "/api/diff":
                    return self._json({"ok": True, **ws.diff(path, v)})
                if u.path == "/api/svg":
                    hide = tuple(x for x in q.get("hide", "").split(",") if x)
                    body = ws.svg(path, v, diff=q.get("diff") == "1", hide=hide).encode("utf-8")
                    return self._send(200, body, "image/svg+xml", cache=pinned)
                if u.path == "/api/mesh":
                    return self._send(200, ws.mesh(path, v).read_bytes(), "application/json", cache=pinned)
                return self._send(200, ws.png(path, v).read_bytes(), "image/png", cache=pinned)  # /api/png
            except AgentCADError as exc:
                code = 404 if exc.code in ("FILE_NOT_FOUND", "VERSION_NOT_FOUND") else \
                    503 if exc.category == "dependency" else 403 if exc.category == "policy" else 400
                self._json({"ok": False, "error": exc.to_dict()}, code)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": {"code": "INTERNAL_ERROR", "category": "internal",
                                                   "message": f"{type(exc).__name__}: {exc}"}}, 500)

        def _events(self, last: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(b"retry: 1000\n\n")
                self.wfile.flush()
                while not feed._stop.is_set():
                    evs = feed.wait(last, 15)
                    if not evs:
                        self.wfile.write(b": keep-alive\n\n")
                    for ev in evs:
                        last = ev["id"]
                        self.wfile.write(f"id: {last}\ndata: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        def log_message(self, fmt, *args):  # keep stdout clean
            pass

    return Handler


def _server(host: str):
    """ThreadingHTTPServer for ``host`` (IPv6 when it is an IPv6 address such as ::1) that does not print a
    traceback when a client drops the connection (a closed tab, an SSE reconnect)."""
    import socket as _socket
    from http.server import ThreadingHTTPServer

    class Server(ThreadingHTTPServer):
        address_family = _socket.AF_INET6 if ":" in host else _socket.AF_INET

        def handle_error(self, request, client_address):
            import sys
            if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
                return
            super().handle_error(request, client_address)

    return Server


class Viewer:
    """The server and its change feed; ``start`` runs it in the background (tests), ``serve`` blocks."""

    def __init__(self, policy: Policy, host: str = "127.0.0.1", port: int = 8770, interval: float = 0.4,
                 allow_remote: bool = False,
                 cache_dir: Path | None = None) -> None:
        policy.read_only = True  # the viewer never writes a drawing
        self.ws = Workspace(policy, cache_dir)
        self.feed = ChangeFeed(self.ws, interval)
        if host not in LOOPBACK and not allow_remote:
            raise AgentCADError("REMOTE_NOT_ALLOWED", f"--host {host} would expose the workspace to the network",
                                category="policy", hint="The page has no authentication. Pass --allow-remote if "
                                                        "you mean it")
        self.httpd = _server(host)((host, port), make_handler(self.ws, self.feed,
                                                              None if allow_remote else LOOPBACK))
        self.httpd.daemon_threads = True
        h, p = self.httpd.server_address[:2]
        h = "127.0.0.1" if h in ("0.0.0.0", "") else "::1" if h == "::" else h
        self.url = f"http://{f'[{h}]' if ':' in h else h}:{p}/"
        self.info_path = policy.state_dir() / INFO_FILE

    def _write_info(self) -> None:
        try:
            self.info_path.parent.mkdir(parents=True, exist_ok=True)
            self.info_path.write_text(json.dumps({"url": self.url, "pid": os.getpid()}), "utf-8")
        except OSError:
            pass

    def start(self) -> "Viewer":
        self.feed.start()
        threading.Thread(target=self.httpd.serve_forever, name="agentcad-viewer", daemon=True).start()
        self._write_info()
        return self

    def serve(self) -> None:
        self.feed.start()
        self._write_info()
        print(json.dumps({"ok": True, "viewer": self.url, "root": str(self.ws.policy.root)}), flush=True)
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self.feed.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        try:
            if json.loads(self.info_path.read_text("utf-8")).get("pid") == os.getpid():
                self.info_path.unlink()
        except (OSError, ValueError):
            pass


def viewer_url(policy: Policy, drawing: str) -> str | None:
    """The page showing ``drawing`` if a viewer is serving this root (its port answers), else None."""
    try:
        url = json.loads((policy.state_dir() / INFO_FILE).read_text("utf-8"))["url"]
        u = urlparse(url)
        if u.scheme != "http" or u.hostname not in LOOPBACK or not u.port:
            return None  # an edited or foreign file must not make the runtime connect elsewhere
        with socket.create_connection((u.hostname, u.port), timeout=0.2) as c:
            c.settimeout(1.0)
            host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
            c.sendall(f"GET /api/ping HTTP/1.0\r\nHost: {host}:{u.port}\r\n\r\n".encode())
            raw = b""
            while chunk := c.recv(4096):
                raw += chunk
                if len(raw) > 65536:
                    return None
        body = json.loads(raw.split(b"\r\n\r\n", 1)[1])
        if Path(body["root"]).resolve() != policy.root:
            return None  # a viewer of another root left its file here, or the port was reused
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    return f"{url}#{drawing}"
