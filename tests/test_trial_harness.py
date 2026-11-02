"""The trial harness reruns a session whose agent never reached the AgentCAD server: in the 2026-11-02 rerun three
Codex sessions started at once, the server missed Codex's 10 s startup window, and the agents gave up untouched."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "trials"))
from agents import agent_env, codex_cmd, reached_agentcad, run_session  # noqa: E402

CODEX_NO_TOOLS = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "agentcad",
                                                     "tool": "list_mcp_resources", "status": "completed"}}
CODEX_TEMPLATES = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "agentcad",
                                                      "tool": "list_mcp_resource_templates", "status": "completed"}}
CODEX_CALL = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "agentcad",
                                                 "tool": "list_operations", "status": "completed"}}
CLAUDE_CALL = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "mcp__agentcad__apply_operations", "input": {}}]}}


def test_a_log_shows_whether_the_agent_reached_agentcad(tmp_path):
    log = tmp_path / "a.jsonl"
    for events, reached in (([CODEX_NO_TOOLS, CODEX_TEMPLATES], False), ([CODEX_NO_TOOLS, CODEX_CALL], True),
                            ([CLAUDE_CALL], True)):
        log.write_text("not json\n" + "\n".join(json.dumps(e) for e in events), encoding="utf-8")
        assert reached_agentcad(log) is reached


def test_both_agents_wait_for_the_server_to_start():
    assert any(a.startswith("mcp_servers.agentcad.startup_timeout_sec=") for a in codex_cmd("mcp", "ws", "high"))
    assert int(agent_env()["MCP_TIMEOUT"]) >= 60000  # Claude Code, in ms


def fake_agent(count: Path, reach_on: int) -> list[str]:
    """An agent whose n-th start (from 1) reaches the server when n >= reach_on."""
    return [sys.executable, "-c", ("import json,pathlib;p=pathlib.Path(%r);n=int(p.read_text()) if p.exists() else 0;"
            "p.write_text(str(n+1));print(json.dumps(%r if n + 1 >= %d else %r))")
            % (str(count), CODEX_CALL, reach_on, CODEX_NO_TOOLS)]


def test_a_session_without_the_server_runs_again(tmp_path):
    """The failed try's logs move to noserver/, out of the graders' glob (hard/grade_hard.py, compare_cc_runs.py)."""
    stale = tmp_path / "noserver" / "T1.try2.jsonl"
    stale.parent.mkdir()
    stale.write_text("from an earlier batch")
    log = tmp_path / "T1.jsonl"
    r = run_session(fake_agent(tmp_path / "c1", 2), "", log, tmp_path, 60, mcp=True)
    assert r["retries"] == 1 and r["exit"] == 0 and r["reached"] and reached_agentcad(log)
    assert sorted(f.name for f in (tmp_path / "noserver").iterdir()) == ["T1.try1.jsonl", "T1.try1.stderr.log"]
    assert sorted(f.name for f in tmp_path.glob("T1*.jsonl")) == ["T1.jsonl"]


def test_every_try_without_the_server_is_reported(tmp_path):
    r = run_session(fake_agent(tmp_path / "c", 99), "", tmp_path / "H1_r1.jsonl", tmp_path, 60, mcp=True)
    assert r["retries"] == 2 and not r["reached"]
    assert len(list((tmp_path / "noserver").glob("*.jsonl"))) == 2 and (tmp_path / "H1_r1.jsonl").exists()


def test_the_code_arm_never_retries(tmp_path):
    r = run_session(fake_agent(tmp_path / "c", 99), "", tmp_path / "T2.jsonl", tmp_path, 60, mcp=False)
    assert r["retries"] == 0 and r["reached"]
