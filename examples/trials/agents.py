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


def server_env(root: str, scripts: bool = False) -> dict[str, str]:
    """Environment of the AgentCAD MCP server: the workspace root, plus where 3D parts find FreeCAD."""
    env = {"AGENTCAD_ROOT": root, "PYTHONIOENCODING": "utf-8"}
    for key in ("AGENTCAD_FREECAD", "FREECAD_LIB"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if os.environ.get("AGENTCAD_SRC"):  # run the MCP server from another source tree (a pinned snapshot)
        env["PYTHONPATH"] = os.environ["AGENTCAD_SRC"]
    if scripts:
        env["AGENTCAD_ALLOW_SCRIPTS"] = "1"
    return env


def codex_cmd(arm: str, root: str, effort: str, scripts: bool = False, images: list[str] = ()) -> list[str]:
    """``images``: files attached to the prompt (Codex cannot open images itself in the mcp arm)."""
    attach = [a for img in images for a in ("-i", img)]
    if arm == "code":
        return ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "--json", "-C", root,
                "-c", f'model_reasoning_effort="{effort}"', *attach, "-"]
    env = ", ".join(f'{k}="{Path(v).as_posix() if k != "PYTHONIOENCODING" else v}"'
                    for k, v in server_env(root, scripts).items())
    return ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "--json", "-C", root,
            "-c", f'model_reasoning_effort="{effort}"',
            "-c", f'mcp_servers.agentcad.command="{PY.as_posix()}"',
            "-c", 'mcp_servers.agentcad.args=["-m","agentcad.mcp_server"]',
            "-c", f"mcp_servers.agentcad.env={{{env}}}",
            "-c", 'mcp_servers.agentcad.default_tools_approval_mode="approve"',
            "-c", "mcp_servers.agentcad.tool_timeout_sec=300", *attach, "-"]


def claude_cmd(arm: str, root: str, effort: str, conf_dir: Path, python: str = "", scripts: bool = False,
               images: list[str] = ()) -> list[str]:
    """``images``: the mcp arm also gets the Read tool, so the agent can look at these input images. Run the
    process with the workspace as its working directory: reads outside it would ask, and asking is denied."""
    base = [claude_exe(), "-p", "--output-format", "stream-json", "--verbose", "--model", CLAUDE_MODEL,
            "--effort", effort, "--no-session-persistence", "--permission-prompts", "none",
            "--setting-sources", "project"]
    if arm == "code":
        py = Path(python).as_posix()
        return base + ["--tools", "Bash,Read,Write,Edit,Glob,Grep", "--permission-mode", "acceptEdits",
                       "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep", f"Bash({py} *)",
                       f'Bash("{py}" *)', "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = conf_dir / f"mcp_{hashlib.sha1(root.encode()).hexdigest()[:12]}.json"
    conf.write_text(json.dumps({"mcpServers": {"agentcad": {
        "command": str(PY), "args": ["-m", "agentcad.mcp_server"], "env": server_env(root, scripts)}}}),
        encoding="utf-8")
    tools = ["--tools", "Read", "--allowedTools", "mcp__agentcad", "Read"] if images else \
        ["--tools", "", "--allowedTools", "mcp__agentcad"]
    return base + tools + ["--permission-mode", "dontAsk", "--strict-mcp-config", "--mcp-config", str(conf)]


def command(agent: str, arm: str, root: str, effort: str, conf_dir: Path, python: str = "",
            scripts: bool = False, images: list[str] = ()) -> list[str]:
    if agent == "claude":
        return claude_cmd(arm, root, effort, conf_dir, python, scripts, images)
    return codex_cmd(arm, root, effort, scripts, images)


# Variables a Claude Code (desktop) session sets for the processes it starts. A trial launched from inside such a
# session inherited them, and the agent then ran as a desktop child (entrypoint claude-desktop, the desktop's skills
# and subagents, a scratchpad): ~300 more tokens of context on every turn. Kept: login (ANTHROPIC_*, account / OAuth),
# provider choice (Bedrock / Vertex) and the Windows bash path, which a user sets on purpose.
SESSION_ENV_PREFIXES = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK_", "CLAUDE_PID", "CLAUDE_EFFORT",
                        "CLAUDE_PREVIEW_", "AI_AGENT", "MCP_CONNECTION_", "MCP_SERVER_CONNECTION_")
SESSION_ENV_KEEP = {"CLAUDE_CODE_ACCOUNT_UUID", "CLAUDE_CODE_ORGANIZATION_UUID", "CLAUDE_CODE_OAUTH_SCOPES",
                    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USER_EMAIL", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
                    "CLAUDE_CODE_SKIP_VERTEX_AUTH", "CLAUDE_CODE_GIT_BASH_PATH"}


def agent_env() -> dict[str, str]:
    """The environment for an agent process: this one, minus what a surrounding Claude Code session injected, and
    without Claude Code's git context. The workspaces sit inside this repository and Claude Code puts the
    repository's `git status` into every turn's context: a dirty checkout cost ~1.7K tokens per turn in the v3
    rerun (docs/comparison-claude-code.md), so batches run at different times were not comparable."""
    env = {k: v for k, v in os.environ.items()
           if k in SESSION_ENV_KEEP or not k.upper().startswith(SESSION_ENV_PREFIXES)}
    env["CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"] = "1"
    return env
