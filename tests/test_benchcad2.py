"""Boundary and result-accounting tests for the optional BenchCAD 2 runner."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "examples" / "benchcad2"


def load(name):
    spec = importlib.util.spec_from_file_location(f"benchcad2_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("run")
tools = load("task_tools")
IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def test_explicit_model_effort_and_no_unrelated_tools(tmp_path):
    cmd = runner.command(tmp_path, "part", ["views.png"], tmp_path / "final.txt")
    assert cmd[cmd.index("--model") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="max"' in cmd
    assert "--ignore-user-config" in cmd
    assert "features.shell_tool=false" in cmd
    assert "features.multi_agent=false" in cmd
    assert "features.plugins=false" in cmd
    assert 'web_search="disabled"' in cmd


@pytest.mark.parametrize("matrix", [
    [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    [[1, 0, 0, float("nan")], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    [[1, 0], [0, 1]],
])
def test_invalid_placement_rejected(matrix):
    with pytest.raises(ValueError):
        tools.rigid_instances([{"part_id": "part_01", "transform": matrix}])


def test_rounded_non_rotation_is_rejected_before_submission():
    t = [[.7071, -.7071, 0, 0], [.7071, .7071, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    with pytest.raises(ValueError):
        tools.rigid_instances([{"part_id": "part_01", "transform": t}])


def test_directory_browser_accepts_root_and_input_subdirectory(tmp_path):
    (tmp_path / "parts").mkdir()
    files = tools.TaskFiles(tmp_path, "part")
    assert files.path(".") == tmp_path.resolve()
    assert files.path("parts").is_dir()
    with pytest.raises(FileNotFoundError):
        files.path("absent")


def test_tool_errors_inside_successful_mcp_envelope_are_counted(tmp_path):
    log = tmp_path / "events.jsonl"
    runner.dump(log, {})
    event = {"type": "item.completed", "item": {
        "type": "mcp_tool_call", "id": "tool-1", "server": "agentcad", "tool": "run_script", "status": "completed",
        "result": {"content": [{"type": "text", "text": json.dumps({
            "ok": False, "error": {"code": "SCRIPT_FAILED"}})}]}}}
    log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    stats = runner.log_stats(log)
    assert stats["tool_errors"] == 1
    assert stats["tool_error_codes"] == {"SCRIPT_FAILED": 1}


def test_over_budget_submission_cannot_bypass_the_monitor():
    # Both submission and process exit can happen between the polling checks.
    assert runner.episode_outcome("completed", 0, 5, 4, 101, 3600, 100) == ("tool_limit", False)
    assert runner.episode_outcome("completed", 0, 5, 4, 100, 3600, 100) == ("completed", True)
    assert runner.episode_outcome("completed", 0, 3602, 3601, 10, 3600, 100) == ("timeout", False)
    # A final summary taking extra time does not invalidate an on-time submit.
    assert runner.episode_outcome("timeout", 1, 3602, 3599, 10, 3600, 100) == ("completed", True)
    assert runner.episode_outcome("timeout", 1, 3602, None, 10, 3600, 100) == ("timeout", False)


def test_resume_does_not_grant_failed_model_episodes_fresh_budgets():
    for status in ("completed", "timeout", "tool_limit"):
        assert runner.resume_record({"status": status}, retry_infra=True)
    assert runner.resume_record({"status": "agent_error"}, retry_infra=False)
    assert not runner.resume_record({"status": "agent_error"}, retry_infra=True)
    with pytest.raises(RuntimeError):
        runner.resume_record({"status": "running"}, retry_infra=True)


def test_input_only_assembly_copies_supplied_parts_and_records_placements(tmp_path):
    step = tmp_path / "step_files" / "part_01.step"
    step.parent.mkdir()
    step.write_bytes(b"supplied geometry")
    (tmp_path / "bom.json").write_text(json.dumps({"items": [
        {"part_id": "part_01", "source": "step", "file": "step_files/part_01.step", "quantity": 2}]}))
    files = tools.TaskFiles(tmp_path, "assembly")
    result = files.submit(instances=[{"part_id": "part_01", "transform": IDENTITY},
                                     {"part_id": "part_01", "transform": IDENTITY}])
    assert result["submitted"]
    assert (tmp_path / "submission/parts/part_01.step").read_bytes() == step.read_bytes()
    rows = json.loads((tmp_path / "submission/assembly/instances.json").read_text())
    assert [r["instance_id"] for r in rows] == ["part_01_i1", "part_01_i2"]
    assert json.loads((tmp_path / "answer.json").read_text())["path"] == "submission"


def test_submission_requires_real_output_inside_workspace(tmp_path):
    files = tools.TaskFiles(tmp_path, "part")
    with pytest.raises(Exception):
        files.submit(path="../outside.step")
    with pytest.raises(Exception):
        files.submit(path="missing.step")
    assert not (tmp_path / "answer.json").exists()


def test_summary_weights_tasks_equally_and_does_not_hide_evaluator_failure(tmp_path):
    counts = [1, 2, 2, 1, 1, 2]
    for t, count in enumerate(counts, 1):
        for c in range(1, count + 1):
            out = tmp_path / f"task{t}_case{c}"
            runner.dump(out / "run.json", {"attempt": 1, "seconds": 1., "submitted": True})
            runner.dump(out / "score.json", {"case": out.name, "attempt": 1, "score": t / 10})
    summary = runner.summarize(tmp_path)
    assert summary["complete"]
    assert summary["mean_of_task_means"] == pytest.approx(.35)
    bad = tmp_path / "task3_case1/score.json"
    runner.dump(bad, {"case": "task3_case1", "attempt": 1, "score": None, "status": "evaluator_error"})
    summary = runner.summarize(tmp_path)
    assert not summary["complete"]
    assert summary["mean_of_task_means"] is None
    assert summary["tasks"]["task3"]["scored"] == 1


def test_failed_episode_is_zero_even_when_partial_geometry_exists(tmp_path, monkeypatch):
    from argparse import Namespace

    case = tmp_path / "bank/task1/cases/case1"
    case.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "partial.step").write_bytes(b"partial")
    args = Namespace(out=tmp_path / "out", resume=False, bench_python=Path("unused"), bench_source=tmp_path)
    # No external scorer is invoked for a failed episode.
    monkeypatch.setattr(runner, "score_protocol", lambda source: {"test": True})
    runner.dump(args.out / "task1_case1/run.json", {
        "submitted": False, "status": "timeout", "attempt": 1, "workspace": str(workspace)})
    result = runner.score_one(case, args)
    assert result["score"] == 0
    assert result["status"] == "no_submission"
