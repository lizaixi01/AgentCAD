"""Generate MCP client configs for this machine. Paths in an MCP config are
per-checkout and per-OS (``.venv/Scripts/python.exe`` vs ``.venv/bin/python``),
so the config is generated from the running interpreter instead of committed."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .errors import input_error
from .policy import Policy


def server_entry(policy: Policy) -> dict[str, Any]:
    """stdio server entry: this interpreter, this workspace, this policy."""
    env = {"AGENTCAD_ROOT": policy.root.as_posix(), "PYTHONIOENCODING": "utf-8"}
    if policy.read_only:
        env["AGENTCAD_READ_ONLY"] = "1"
    if policy.allow_scripts:
        env["AGENTCAD_ALLOW_SCRIPTS"] = "1"
    return {"command": Path(sys.executable).absolute().as_posix(), "args": ["-m", "agentcad.mcp_server"], "env": env}


def codex_toml(name: str, entry: dict[str, Any]) -> str:
    # JSON strings are valid TOML basic strings
    s = lambda v: json.dumps(v, ensure_ascii=False)
    env = ", ".join(f"{k} = {s(v)}" for k, v in entry["env"].items())
    return "\n".join([f"[mcp_servers.{name}]", f"command = {s(entry['command'])}",
                      f"args = [{', '.join(s(a) for a in entry['args'])}]", f"env = {{ {env} }}",
                      # without this, Codex under approval_policy="never" rejects every tool call
                      'default_tools_approval_mode = "approve"', ""])


def mcp_config(policy: Policy, client: str = "claude", name: str = "agentcad", write: str | None = None) -> dict[str, Any]:
    if not policy.root.is_dir():
        raise input_error("ROOT_NOT_FOUND", f"workspace root {policy.root} is not a directory",
                          hint="Create it first, or pass --root")
    entry = server_entry(policy)
    if client == "codex":
        toml = codex_toml(name, entry)
        r = {"ok": True, "client": "codex", "name": name, "toml": toml}
        if write is not None:
            target = Path(write or Path.home() / ".codex" / "config.toml")
            text = target.read_text("utf-8") if target.is_file() else ""
            if f"[mcp_servers.{name}]" in text:
                raise input_error("SERVER_EXISTS", f"{target} already has [mcp_servers.{name}]",
                                  hint="Delete that table first, or use --name")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + ("\n" if text and not text.endswith("\n\n") else "") + toml, "utf-8")
            r["written"] = str(target.resolve())
        return r
    config: dict[str, Any] = {"mcpServers": {name: entry}}
    r = {"ok": True, "client": "claude", "name": name, "config": config}
    if write is not None:
        target = Path(write or ".mcp.json")
        existing: dict[str, Any] = {}
        if target.is_file():
            try:
                existing = json.loads(target.read_text("utf-8"))
            except ValueError as exc:
                raise input_error("BAD_CONFIG", f"{target} is not valid JSON: {exc}")
        # keep the other servers in the file
        existing.setdefault("mcpServers", {})[name] = entry
        target.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", "utf-8")
        r["written"] = str(target.resolve())
    return r
