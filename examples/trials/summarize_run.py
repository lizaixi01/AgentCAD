"""Summarize an agent event stream: MCP tool calls (ok / error code), shell commands, tokens, final message.

Reads Codex `--json` streams and Claude Code `--output-format stream-json` streams. Usage is reported in the Codex
shape: input_tokens (all prompt tokens, cached included), cached_input_tokens, output_tokens.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CC_SHELL = {"Bash", "PowerShell"}
CC_FILES = {"Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit"}


def _envelope(txt: str, fallback: str = "") -> dict:
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "error": {"code": "NON_JSON", "message": txt[:200] or fallback}}


def _codex(lines: list[dict]) -> dict:
    calls, final, usage = [], None, None
    for e in lines:
        it = e.get("item") or {}
        if e.get("type") == "item.completed":
            if it.get("type") == "mcp_tool_call":
                txt = "".join(c.get("text", "") for c in ((it.get("result") or {}).get("content") or []))
                body = _envelope(txt, str(it.get("error")))
                err = body.get("error") or {}
                calls.append({"tool": it.get("tool"), "ok": bool(body.get("ok")),
                              "error": err.get("code"), "message": (err.get("message") or "")[:160]})
            elif it.get("type") == "command_execution":
                calls.append({"tool": "SHELL", "ok": None, "command": (it.get("command") or "")[:120]})
            elif it.get("type") == "agent_message":
                final = it.get("text")
        if e.get("type") == "turn.completed":
            usage = e.get("usage")
    return {"calls": calls, "usage": usage, "final": final, "agent": "codex"}


def _claude(lines: list[dict]) -> dict:
    uses: dict[str, dict] = {}
    order: list[str] = []
    calls, final, usage, extra = [], None, None, {}
    for e in lines:
        t = e.get("type")
        if t == "system" and e.get("subtype") == "init":
            extra["model"] = e.get("model")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content")
        for c in content if isinstance(content, list) else []:
            if t == "assistant" and c.get("type") == "tool_use":
                uses[c["id"]] = c
                order.append(c["id"])
            elif t == "user" and c.get("type") == "tool_result":
                u = uses.get(c.get("tool_use_id"), {})
                name = u.get("name", "?")
                content = c.get("content")
                txt = content if isinstance(content, str) else "".join(
                    x.get("text", "") for x in content or [] if isinstance(x, dict))
                if name.startswith("mcp__"):
                    body = _envelope(txt)
                    if c.get("is_error") and body.get("ok") is None:
                        body = {"ok": False, "error": {"code": "TOOL_ERROR", "message": txt[:200]}}
                    err = body.get("error") or {}
                    calls.append({"tool": name.split("__")[-1], "ok": bool(body.get("ok")),
                                  "error": err.get("code"), "message": (err.get("message") or "")[:160]})
                elif name in CC_SHELL:
                    # like the Codex streams, a failing command is not a tool error; permission denials are
                    # counted separately ("denials")
                    calls.append({"tool": "SHELL", "ok": None,
                                  "error": "DENIED" if c.get("is_error") and "permission" in txt.lower() else None,
                                  "command": str((u.get("input") or {}).get("command", ""))[:120]})
                elif name in CC_FILES:
                    calls.append({"tool": "FILE:" + name, "ok": None if not c.get("is_error") else False,
                                  "error": "TOOL_ERROR" if c.get("is_error") else None})
                else:
                    calls.append({"tool": name, "ok": not c.get("is_error"), "error": None})
        if t == "result":
            u = e.get("usage") or {}
            cached = u.get("cache_read_input_tokens", 0)
            usage = {"input_tokens": u.get("input_tokens", 0) + cached + u.get("cache_creation_input_tokens", 0),
                     "cached_input_tokens": cached, "output_tokens": u.get("output_tokens", 0)}
            final = e.get("result")
            extra.update(cost_usd=e.get("total_cost_usd"), turns=e.get("num_turns"), is_error=e.get("is_error"),
                         denials=len(e.get("permission_denials") or []))
    return {"calls": calls, "usage": usage, "final": final, "agent": "claude", **extra}


def summarize(path: Path) -> dict:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            continue
    s = _claude(lines) if lines and lines[0].get("type") == "system" else _codex(lines)
    calls = s["calls"]
    s.update(n_calls=len(calls), n_errors=sum(1 for c in calls if c["ok"] is False))
    return s


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        s = summarize(Path(p))
        print("=====", p)
        for c in s["calls"]:
            print(" ", c)
        print("usage:", s["usage"], {k: s[k] for k in ("model", "cost_usd", "turns", "denials") if k in s})
        print(s["final"])
