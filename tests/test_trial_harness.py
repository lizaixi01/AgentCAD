"""The trial harness reruns a session whose agent never reached the AgentCAD server: in the 2026-11-02 rerun three
Codex sessions started at once, the server missed Codex's 10 s startup window, and the agents gave up untouched."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "trials"))
from agents import codex_cmd, reached_agentcad, run_session  # noqa: E402

CODEX_NO_TOOLS = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "agentcad",
                                                     "tool": "list_mcp_resources", "status": "completed"}}
CODEX_CALL = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "agentcad",
                                                 "tool": "list_operations", "status": "completed"}}
CLAUDE_CALL = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "mcp__agentcad__apply_operations", "input": {}}]}}


def test_a_log_shows_whether_the_agent_reached_agentcad(tmp_path):
    log = tmp_path / "a.jsonl"
    for events, reached in (([CODEX_NO_TOOLS], False), ([CODEX_NO_TOOLS, CODEX_CALL], True), ([CLAUDE_CALL], True)):
        log.write_text("not json\n" + "\n".join(json.dumps(e) for e in events), encoding="utf-8")
        assert reached_agentcad(log) is reached


def test_codex_waits_for_the_server_to_start():
    assert any(a.startswith("mcp_servers.agentcad.startup_timeout_sec=") for a in codex_cmd("mcp", "ws", "high"))


def test_a_session_without_the_server_runs_again(tmp_path):
    """The fake agent reaches the server on its second start; the first log is kept aside."""
    count = tmp_path / "count"
    script = ("import json,pathlib;p=pathlib.Path(%r);n=int(p.read_text()) if p.exists() else 0;"
              "p.write_text(str(n+1));print(json.dumps(%r if n else %r))") % (str(count), CODEX_CALL, CODEX_NO_TOOLS)
    log = tmp_path / "T1.jsonl"
    r = run_session([sys.executable, "-c", script], "", log, tmp_path, 60, mcp=True)
    assert r["retries"] == 1 and r["exit"] == 0
    assert reached_agentcad(log)
    assert not reached_agentcad(tmp_path / "T1.noserver1.jsonl")
    assert (tmp_path / "T1.noserver1.stderr.log").exists()

    count.unlink()  # the code arm never touches the server: no retry
    assert run_session([sys.executable, "-c", script], "", tmp_path / "T2.jsonl", tmp_path, 60, mcp=False)[
        "retries"] == 0
