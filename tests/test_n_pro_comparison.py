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
    assert len(rows) == 1 and rows[0]["run_status"] == "completed"
    assert not rows[0]["ok"]
    assert rows[0]["grade"]["fails"]


def test_h4_center_lines_must_stay_at_their_original_positions(tmp_path):
    import ezdxf

    fixture, drawing = tmp_path / "fixture.dxf", tmp_path / "drawing.dxf"
    benchmark.make_h4_base(fixture)
    doc = ezdxf.readfile(fixture)
    msp = doc.modelspace()
    for line in list(msp.query("LINE")):
        if line.dxf.get("color", 256) == 1 and (line.dxf.end - line.dxf.start).magnitude > 1e-6:
            line.dxf.layer = "CENTER"
        else:
            msp.delete_entity(line)
    doc.saveas(drawing)
    assert benchmark.h4_center_lines_preserved(fixture, drawing)
    line = list(msp.query("LINE"))[0]
    line.dxf.start += (1000, 0, 0)
    line.dxf.end += (1000, 0, 0)
    doc.saveas(drawing)
    assert not benchmark.h4_center_lines_preserved(fixture, drawing)


@pytest.mark.parametrize("message,status", [
    ("Selected model is at capacity. Please try a different model.", "model_service_interrupted"),
    ("Reconnecting... waiting for network (Connection failed)", "model_service_interrupted"),
    ("MCP server failed to start", "unclassified_failure"),
    ("", "unclassified_failure"),
])
def test_unfinished_rounds_need_evidence_for_model_service_classification(tmp_path, message, status):
    log = tmp_path / "events.jsonl"
    log.write_text(json.dumps({"type": "error", "message": message}), encoding="utf-8")
    summary = benchmark.summarize(log)
    assert benchmark.round_status({"exit": 1, "timeout": False, **summary}) == status
    assert benchmark.unit_status([], 1) == "unclassified_failure"


def test_other_tool_use_invalidates_completed_unit_and_deduplicates_events(tmp_path):
    log = tmp_path / "events.jsonl"
    item = {"id": "one", "type": "command_execution", "command": "pwd"}
    events = [{"type": "item.started", "item": item}, {"type": "item.completed", "item": item},
              {"type": "turn.completed", "usage": {}}]
    log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    summary = benchmark.summarize(log)
    assert summary["other_tool_calls"] == 1
    assert benchmark.unit_status([{"exit": 0, "timeout": False, **summary}], 1) == "tool_policy_violation"


def test_old_network_message_does_not_explain_later_mcp_timeout(tmp_path):
    log = tmp_path / "events.jsonl"
    events = [{"type": "error", "message": "Reconnecting... waiting for network (Connection failed)"},
              {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "cad"}},
              {"type": "item.started", "item": {"type": "mcp_tool_call", "server": "cad"}}]
    log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    summary = benchmark.summarize(log)
    assert summary["event_errors"]
    assert benchmark.round_status({"exit": None, "timeout": True, **summary}) == "unclassified_failure"


def test_truncated_terminal_event_does_not_prove_network_interruption(tmp_path):
    log = tmp_path / "events.jsonl"
    event = {"type": "error", "message": "Reconnecting... waiting for network (Connection failed)"}
    log.write_text(json.dumps(event) + '\n{"type":"item.started",', encoding="utf-8")
    summary = benchmark.summarize(log)
    assert benchmark.round_status({"exit": None, "timeout": True, **summary}) == "unclassified_failure"


def test_interrupted_pair_excludes_completed_side_and_cannot_duplicate_retry():
    pair = [{"task": "H4", "rep": 1, "arm": "A", "run_status": "completed",
             "eligible_for_rate": True, "counted_success": True},
            {"task": "H4", "rep": 1, "arm": "B", "run_status": "model_service_interrupted",
             "eligible_for_rate": False, "counted_success": False}]
    assert benchmark.pair_can_retry(pair)
    benchmark.mark_pair_eligibility(pair)
    assert all(not row["eligible_for_rate"] and not row["counted_success"] for row in pair)
    assert all(row["exclusion_reason"] == "pair_model_service_interrupted" for row in pair)


def test_unclassified_failure_prevents_excluding_a_pair_as_model_interruption():
    pair = [{"task": "H4", "rep": 1, "arm": "A", "run_status": "unclassified_failure",
             "eligible_for_rate": True, "counted_success": False},
            {"task": "H4", "rep": 1, "arm": "B", "run_status": "model_service_interrupted",
             "eligible_for_rate": False, "counted_success": False}]
    assert not benchmark.pair_can_retry(pair)
    benchmark.mark_pair_eligibility(pair)
    assert pair[0]["eligible_for_rate"] and not pair[0]["counted_success"]


def test_rejected_retry_does_not_change_source_evidence(tmp_path, monkeypatch):
    import sys

    source, target = tmp_path / "source", tmp_path / "retry"
    fixture = source / "fixtures" / "H4.dxf"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"fixture")
    manifest = {"agentcad_commit": "same", "pro_commit": "same", "fixtures": {"H4": benchmark.sha(fixture)}}
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "grades.json").write_bytes(b"original evidence")
    for arm, exit_code in (("A", 0), ("B", 1)):
        unit = source / "runs" / "H4" / "r1" / arm
        unit.mkdir(parents=True)
        result = {"task": "H4", "rep": 1, "arm": arm,
                  "rounds": [{"exit": exit_code, "turn_completed": exit_code == 0}]}
        (unit / "result.json").write_text(json.dumps(result), encoding="utf-8")
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    path = SOURCE.with_name("retry_pair.py")
    spec = importlib.util.spec_from_file_location("pro_comparison_retry", path)
    retry = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(retry)
    monkeypatch.setattr(retry.bench, "version", lambda path: "same")
    monkeypatch.setattr(sys, "argv", ["retry_pair.py", "--source", str(source), "--out", str(target),
                                      "--pro", str(tmp_path), "--task", "H4", "--rep", "1"])
    with pytest.raises(RuntimeError, match="confirmed model-service interruption"):
        retry.main()
    after = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert after == before
    assert not target.exists()


def test_failed_pair_records_each_arm_and_exits_unsuccessfully(tmp_path, monkeypatch):
    import sys
    import tempfile

    out = tmp_path / "failed-run"

    def prepare(out, pro, reps, tasks):
        (out / "fixtures").mkdir(parents=True)
        benchmark.make_h4_base(out / "fixtures" / "H4.dxf")

    def fail(*args):
        raise OSError("could not start")

    monkeypatch.setattr(benchmark, "prepare", prepare)
    monkeypatch.setattr(benchmark, "run_unit", fail)
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    monkeypatch.setattr(sys, "argv", ["run.py", "--out", str(out), "--pro", str(tmp_path),
                                      "--tasks", "H4", "--reps", "1"])
    with pytest.raises(SystemExit) as exc:
        benchmark.main()
    assert exc.value.code == 1
    events = [json.loads(line) for line in (out / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {event["arm"] for event in events if event["event"] == "unit_error"} == {"A", "B"}
    assert events[-2]["event"] == "pair_incomplete"
    assert events[-1]["event"] == "all_incomplete"
    rows = json.loads((out / "grades.json").read_text(encoding="utf-8"))
    assert len(rows) == 2
    assert all(r["run_status"] == "unclassified_failure" and r["eligible_for_rate"]
               and not r["counted_success"] for r in rows)
