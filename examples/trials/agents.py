"""Command lines for the external agents used in the trials: Codex CLI or Claude Code, for both arms.

Arm "mcp" (A): the agent can only call the AgentCAD MCP server; it cannot run commands or touch files itself.
Arm "code" (B): the agent writes and runs Python with plain ezdxf in its own workspace, no AgentCAD.

Claude Code runs headless (`claude -p`) with the same limits as the Codex runs:
  A: all built-in tools off (--tools ""), only mcp__agentcad allowed;
  B: file tools plus Bash restricted to the given Python interpreter; edits inside the workspace are accepted,
     anything else that would ask for permission is denied (--permission-prompts none).
The Claude Code binary comes from $AGENTCAD_CLAUDE, `claude` on PATH, or the newest copy bundled with the Claude
desktop app.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLAUDE_MODEL = os.environ.get("AGENTCAD_CLAUDE_MODEL", "opus")


def claude_exe() -> str:
    if os.environ.get("AGENTCAD_CLAUDE"):
        return os.environ["AGENTCAD_CLAUDE"]
    if shutil.which("claude"):
        return shutil.which("claude")
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Claude-Data"
    found = sorted(root.glob("*/claude-code/*/*/claude.exe"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise SystemExit("Claude Code not found: set AGENTCAD_CLAUDE to claude.exe")
    return str(found[-1])


def codex_cmd(arm: str, root: str, effort: str, scripts: bool = False) -> list[str]:
    if arm == "code":
        return ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "--json", "-C", root,
                "-c", f'model_reasoning_effort="{effort}"', "-"]
    env = f'AGENTCAD_ROOT="{root}"' + (', AGENTCAD_ALLOW_SCRIPTS="1"' if scripts else "")
    return ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "--json", "-C", root,
            "-c", f'model_reasoning_effort="{effort}"',
            "-c", f'mcp_servers.agentcad.command="{PY.as_posix()}"',
            "-c", 'mcp_servers.agentcad.args=["-m","agentcad.mcp_server"]',
            "-c", f"mcp_servers.agentcad.env={{{env}}}",
            "-c", 'mcp_servers.agentcad.default_tools_approval_mode="approve"',
            "-c", "mcp_servers.agentcad.tool_timeout_sec=300", "-"]


def claude_cmd(arm: str, root: str, effort: str, conf_dir: Path, python: str = "", scripts: bool = False) -> list[str]:
    base = [claude_exe(), "-p", "--output-format", "stream-json", "--verbose", "--model", CLAUDE_MODEL,
            "--effort", effort, "--no-session-persistence", "--permission-prompts", "none",
            "--setting-sources", "project"]
    if arm == "code":
        py = Path(python).as_posix()
        return base + ["--tools", "Bash,Read,Write,Edit,Glob,Grep", "--permission-mode", "acceptEdits",
                       "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep", f"Bash({py} *)",
                       f'Bash("{py}" *)', "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    env = {"AGENTCAD_ROOT": root, "PYTHONIOENCODING": "utf-8"}
    if os.environ.get("AGENTCAD_SRC"):  # run the MCP server from another source tree (a pinned snapshot)
        env["PYTHONPATH"] = os.environ["AGENTCAD_SRC"]
    if scripts:
        env["AGENTCAD_ALLOW_SCRIPTS"] = "1"
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = conf_dir / f"mcp_{hashlib.sha1(root.encode()).hexdigest()[:12]}.json"
    conf.write_text(json.dumps({"mcpServers": {"agentcad": {
        "command": str(PY), "args": ["-m", "agentcad.mcp_server"], "env": env}}}), encoding="utf-8")
    return base + ["--tools", "", "--permission-mode", "dontAsk", "--allowedTools", "mcp__agentcad",
                   "--strict-mcp-config", "--mcp-config", str(conf)]


def command(agent: str, arm: str, root: str, effort: str, conf_dir: Path, python: str = "",
            scripts: bool = False) -> list[str]:
    if agent == "claude":
        return claude_cmd(arm, root, effort, conf_dir, python, scripts)
    return codex_cmd(arm, root, effort, scripts)
