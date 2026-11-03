"""Finding a running live viewer of a workspace, without loading the viewer itself.

The desktop icon runs ``agentcad viewer --open``; when AgentCAD is already running in the background that only
has to open the browser. Importing agentcad.viewer loads ezdxf (about a second), so the check lives here and needs
only the standard library: the icon's window closes a second sooner.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from urllib.parse import urlparse

from .policy import Policy

INFO_FILE = "viewer.json"  # <root>/.agentcad/viewer.json: where a running viewer listens (see viewer_url)
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def serves_root(url: str, policy: Policy) -> bool:
    """True if ``url`` is a loopback viewer whose /api/ping answers with this policy's root."""
    try:
        u = urlparse(url)
        if u.scheme != "http" or u.hostname not in LOOPBACK or not u.port:
            return False  # an edited or foreign file must not make the runtime connect elsewhere
        with socket.create_connection((u.hostname, u.port), timeout=0.2) as c:
            c.settimeout(1.0)
            host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
            c.sendall(f"GET /api/ping HTTP/1.0\r\nHost: {host}:{u.port}\r\n\r\n".encode())
            raw = b""
            while chunk := c.recv(4096):
                raw += chunk
                if len(raw) > 65536:
                    return False
        body = json.loads(raw.split(b"\r\n\r\n", 1)[1])
        # a viewer of another root left its file here, or another viewer answers on this port
        return Path(body["root"]).resolve() == policy.root
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def running_url(policy: Policy) -> str | None:
    """The address of the viewer serving this root, if one runs (its port answers for this root), else None."""
    try:
        url = json.loads((policy.state_dir() / INFO_FILE).read_text("utf-8"))["url"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return url if isinstance(url, str) and serves_root(url, policy) else None


def viewer_url(policy: Policy, drawing: str) -> str | None:
    """The page showing ``drawing`` if a viewer is serving this root (its port answers), else None."""
    url = running_url(policy)
    return f"{url}#{drawing}" if url else None


def open_running(policy: Policy) -> bool:
    """The desktop icon, AgentCAD already running: open its page in the browser and print the link the icon's
    window waits for. False if no viewer of this root runs (the caller starts one)."""
    url = running_url(policy)
    if not url:
        return False
    import webbrowser
    webbrowser.open(url)
    print(json.dumps({"ok": True, "viewer": url, "root": str(policy.root), "reused": True}), flush=True)
    return True
