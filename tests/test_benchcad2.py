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
PROTOCOL = {"benchcad_sha": "A", "mesh_guard": "0", "threads": runner.THREAD_ENV}


def pinned_protocol(root):
    runner.dump(root / "metadata.json", {"benchcad_sha": "A", "scoring_protocol": PROTOCOL})
    for key in runner.CASE_IDS:
        runner.dump(root / key / "oracle.json", {"score": 1., "scoring_protocol": PROTOCOL})


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
    sealed = tmp_path / json.loads((tmp_path / "answer.json").read_text())["path"]
    assert (sealed / "parts/part_01.step").read_bytes() == step.read_bytes()


def test_first_answer_is_immutable_even_if_working_files_or_submit_change(tmp_path):
    answer = tmp_path / "part.step"
    answer.write_bytes(b"first solid")
    files = tools.TaskFiles(tmp_path, "part")
    first = files.submit(path="part.step")
    sealed = tmp_path / first["path"]
    answer.write_bytes(b"second solid")
    assert files.submit(path="part.step")["path"] == first["path"]
    assert sealed.read_bytes() == b"first solid"
    with pytest.raises(Exception):
        files.path(first["path"])
    graph = tools.TaskFiles(tmp_path / "pcb", "ecad")
    graph.root.mkdir()
    first = graph.submit(graph={"components": [{"id": "first"}]})
    graph.submit(graph={"components": [{"id": "second"}]})
    assert json.loads((graph.root / first["path"]).read_text())["components"][0]["id"] == "first"


def test_concurrent_submissions_keep_the_first_answer(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    (tmp_path / "first.step").write_bytes(b"first")
    (tmp_path / "second.step").write_bytes(b"second")
    files = tools.TaskFiles(tmp_path, "part")
    copying, release, second_started = threading.Event(), threading.Event(), threading.Event()
    copy2 = tools.shutil.copy2

    def held_copy(src, dst):
        if Path(src).name == "first.step":
            copying.set()
            assert release.wait(5)
        return copy2(src, dst)

    def second_submit():
        second_started.set()
        return files.submit("second.step")

    monkeypatch.setattr(tools.shutil, "copy2", held_copy)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(files.submit, "first.step")
        assert copying.wait(5)
        second = pool.submit(second_submit)
        try:
            assert second_started.wait(5)
            assert not second.done()
        finally:
            release.set()
        a, b = first.result(), second.result()
    assert a["path"] == b["path"]
    assert (tmp_path / a["path"]).read_bytes() == b"first"


def test_submission_requires_real_output_inside_workspace(tmp_path):
    files = tools.TaskFiles(tmp_path, "part")
    with pytest.raises(Exception):
        files.submit(path="../outside.step")
    with pytest.raises(Exception):
        files.submit(path="missing.step")
    assert not (tmp_path / "answer.json").exists()


def test_summary_weights_tasks_equally_and_does_not_hide_evaluator_failure(tmp_path):
    pinned_protocol(tmp_path)
    counts = [1, 2, 2, 1, 1, 2]
    for t, count in enumerate(counts, 1):
        for c in range(1, count + 1):
            out = tmp_path / f"task{t}_case{c}"
            runner.dump(out / "run.json", {"attempt": 1, "seconds": 1., "submitted": True})
            runner.dump(out / "score.json", {"case": out.name, "attempt": 1, "score": t / 10,
                                              "scoring_protocol": PROTOCOL})
    summary = runner.summarize(tmp_path)
    assert summary["complete"]
    assert summary["mean_of_task_means"] == pytest.approx(.35)
    bad = tmp_path / "task3_case1/score.json"
    runner.dump(bad, {"case": "task3_case1", "attempt": 1, "score": None, "status": "evaluator_error"})
    summary = runner.summarize(tmp_path)
    assert not summary["complete"]
    assert summary["mean_of_task_means"] is None
    assert summary["tasks"]["task3"]["scored"] == 1


def test_summary_refuses_mixed_scoring_revisions(tmp_path):
    pinned_protocol(tmp_path)
    for t, count in enumerate([1, 2, 2, 1, 1, 2], 1):
        for c in range(1, count + 1):
            out = tmp_path / f"task{t}_case{c}"
            runner.dump(out / "run.json", {"attempt": 1})
            runner.dump(out / "score.json", {"case": out.name, "attempt": 1, "score": 1.,
                                              "scoring_protocol": {**PROTOCOL, "benchcad_sha": "A" if t < 6 else "B"}})
    summary = runner.summarize(tmp_path)
    assert not summary["complete"]
    assert summary["mean_of_task_means"] is None
    assert len(summary["scoring_protocols"]) == 2


@pytest.mark.parametrize("changed", ["scores", "oracles", "metadata"])
def test_summary_binds_uniform_scores_to_recorded_run_and_oracles(tmp_path, changed):
    pinned_protocol(tmp_path)
    other = {**PROTOCOL, "benchcad_sha": "B"}
    for key in runner.CASE_IDS:
        out = tmp_path / key
        runner.dump(out / "run.json", {"attempt": 1})
        runner.dump(out / "score.json", {"case": key, "attempt": 1, "score": 1.,
                                          "scoring_protocol": other if changed == "scores" else PROTOCOL})
        if changed == "oracles":
            runner.dump(out / "oracle.json", {"score": 1., "scoring_protocol": other})
    if changed == "metadata":
        runner.dump(tmp_path / "metadata.json", {"benchcad_sha": "B", "scoring_protocol": other})
    summary = runner.summarize(tmp_path)
    assert not summary["complete"]
    assert summary["mean_of_task_means"] is None
    assert summary["provenance_errors"]


def test_offline_score_refuses_revision_drift_even_on_resume(tmp_path, monkeypatch):
    from argparse import Namespace

    pinned_protocol(tmp_path)
    case = tmp_path / "bank/task1/cases/case1"
    case.mkdir(parents=True)
    args = Namespace(out=tmp_path, resume=True, bench_source=tmp_path)
    other = {**PROTOCOL, "benchcad_sha": "B"}
    monkeypatch.setattr(runner, "score_protocol", lambda source: other)
    runner.dump(tmp_path / "task1_case1/run.json", {"attempt": 1})
    runner.dump(tmp_path / "task1_case1/score.json", {"attempt": 1, "score": 1., "scoring_protocol": other})
    with pytest.raises(ValueError, match="recorded run metadata"):
        runner.score_one(case, args)


def test_manifest_rejects_windows_line_ending_conversion(tmp_path):
    import hashlib

    (tmp_path / "input").mkdir()
    p = tmp_path / "input/part.step"
    p.write_bytes(b"canonical\n")
    runner.dump(tmp_path / "case.json", {"input": [{"path": "input/part.step",
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}], "gt": []})
    runner.validate_case_files(tmp_path)
    p.write_bytes(b"canonical\r\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        runner.validate_case_files(tmp_path)


def test_failed_episode_is_zero_even_when_partial_geometry_exists(tmp_path, monkeypatch):
    from argparse import Namespace

    case = tmp_path / "bank/task1/cases/case1"
    case.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "partial.step").write_bytes(b"partial")
    args = Namespace(out=tmp_path / "out", resume=False, bench_python=Path("unused"), bench_source=tmp_path)
    # No external scorer is invoked for a failed episode.
    pinned_protocol(args.out)
    monkeypatch.setattr(runner, "score_protocol", lambda source: PROTOCOL)
    runner.dump(args.out / "task1_case1/run.json", {
        "submitted": False, "status": "timeout", "attempt": 1, "workspace": str(workspace)})
    result = runner.score_one(case, args)
    assert result["score"] == 0
    assert result["status"] == "no_submission"
