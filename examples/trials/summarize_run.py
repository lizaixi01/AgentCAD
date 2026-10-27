"""Summarize a Codex --json event stream: MCP tool calls (ok / error code), shell commands, tokens, final message."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def summarize(path: Path) -> dict:
    calls, final, usage = [], None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        it = e.get("item") or {}
        if e.get("type") == "item.completed":
            if it.get("type") == "mcp_tool_call":
                txt = "".join(c.get("text", "") for c in ((it.get("result") or {}).get("content") or []))
                try:
                    body = json.loads(txt)
                except ValueError:
                    body = {"ok": False, "error": {"code": "NON_JSON", "message": txt[:200] or str(it.get("error"))}}
                err = body.get("error") or {}
                calls.append({"tool": it.get("tool"), "ok": bool(body.get("ok")),
                              "error": err.get("code"), "message": (err.get("message") or "")[:160]})
            elif it.get("type") == "command_execution":
                calls.append({"tool": "SHELL", "ok": None, "command": (it.get("command") or "")[:120]})
            elif it.get("type") == "agent_message":
                final = it.get("text")
        if e.get("type") == "turn.completed":
            usage = e.get("usage")
    return {"calls": calls, "n_calls": len(calls), "n_errors": sum(1 for c in calls if c["ok"] is False),
            "usage": usage, "final": final}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in sys.argv[1:]:
        s = summarize(Path(p))
        print("=====", p)
        for c in s["calls"]:
            print(" ", c)
        print("usage:", s["usage"])
        print(s["final"])
