"""Checks that the comparison counts events consistently and preserves existing data."""
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "examples" / "trials" / "pro_comparison" / "run.py"
SPEC = importlib.util.spec_from_file_location("pro_comparison_run", SOURCE)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(benchmark)


def test_summarize_counts_cad_calls_and_tracks_usage(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "cad", "tool": "read_drawing",
                                            "status": "completed", "result": {"structured_content": {"ok": True}}}},
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "cad", "tool": "call_tool",
                                            "status": "completed", "result": {"structured_content": {"ok": False}}}},
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "another", "tool": "read"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "unused"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "finished"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 25}},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    result = benchmark.summarize(path)
    assert result["cad_calls"] == 2
    assert result["reported_tool_errors"] == 1
    assert result["other_tool_calls"] == 2
    assert result["usage"] == {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 25}
    assert result["turn_completed"] and result["final"] == "finished"


@pytest.mark.parametrize("task,round_no", [("H1", 1), ("H1", 4), ("H4", 1), ("H5", 1)])
def test_both_arms_receive_identical_task_text(task, round_no):
    a = benchmark.prompt(task, round_no, "A").split("\n\n任务：\n", 1)[1]
    b = benchmark.prompt(task, round_no, "B").split("\n\n任务：\n", 1)[1]
    assert a == b


def test_prepare_never_overwrites_previous_run(tmp_path):
    target = tmp_path / "results"
    target.mkdir()
    marker = target / "evidence.json"
    marker.write_text("keep me", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not empty"):
        benchmark.prepare(target, tmp_path, 1, ["H4"])
    assert marker.read_text(encoding="utf-8") == "keep me"

def test_grade_checks_drawing_instead_of_agent_claim(tmp_path, monkeypatch):
    import tempfile

    out = tmp_path / "run"
    unit = out / "runs" / "H4" / "r1" / "A"
    ws = unit / "workspace"
    ws.mkdir(parents=True)
    benchmark.make_h4_base(ws / "part.dxf")
    (unit / "result.json").write_text(json.dumps({
        "task": "H4", "rep": 1, "arm": "A", "seconds": 1,
        "rounds": [{"exit": 0, "turn_completed": True, "final": "Everything is correct."}],
    }), encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    rows = benchmark.grade(out)
    assert len(rows) == 1 and rows[0]["infrastructure_ok"]
    assert not rows[0]["ok"]
    assert rows[0]["grade"]["fails"]
