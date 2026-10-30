"""Integrity of the native-tool control, without model calls or Docker."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "examples" / "benchcad2"
sys.path.insert(0, str(HERE))
import native_run as runner  # noqa: E402
import native_tools as tools  # noqa: E402


class FakeExecutor:
    def __init__(self, action):
        self.action, self.programs = action, []

    def run(self, code, number, timeout):
        self.programs.append(code)
        return self.action(code, number, timeout)


def session(tmp_path, action, deadline=float("inf"), calls=100):
    work = tmp_path / "work"
    work.mkdir()
    fake = FakeExecutor(action)
    return tools.NativeSession(work, tmp_path / "private", fake, deadline, calls), fake


def test_native_final_answer_is_sealed_outside_the_model_mount(tmp_path):
    def build(code, number, timeout):
        native.workspace.joinpath("final.step").write_text("first geometry")
        return tools.Execution(0, "done", "", [])
    native, fake = session(tmp_path, build)
    data, _ = native.execute("import cadquery as cq\nresult = cq.Workplane().box(1,2,3)", True)
    marker = json.loads(native.marker.read_text())
    sealed = native.private / marker["path"]
    assert data["submitted"] and data["finished"]
    assert not sealed.is_relative_to(native.workspace)
    native.workspace.joinpath("final.step").write_text("changed later")
    later, _ = native.execute("replace the answer", True)
    assert later["submitted"] and len(fake.programs) == 1
    assert sealed.read_text() == "first geometry"
    assert fake.programs[0].endswith(tools.FINALISE)


def test_failed_final_program_cannot_promote_an_earlier_step(tmp_path):
    native, fake = session(tmp_path, lambda *args: tools.Execution(1, "", "final crash", []))
    native.workspace.joinpath("final.step").write_text("earlier intermediate")
    data, _ = native.execute("raise RuntimeError('bad final')", True)
    marker = json.loads(native.marker.read_text())
    assert data["finished"] and not data["submitted"]
    assert marker["status"] == "submit_failed" and "path" not in marker
    native.execute("try again", True)
    assert len(fake.programs) == 1
    assert not (native.private / "sealed").exists()


def test_an_ordinary_failure_allows_later_work_within_the_same_budget(tmp_path):
    native, fake = session(tmp_path, lambda *args: tools.Execution(1, "", "failed", []))
    data, _ = native.execute("bad intermediate")
    assert not data["ok"] and not native.marker.exists()
    native.execute("another intermediate")
    assert len(fake.programs) == 2 and all(tools.FINALISE not in p for p in fake.programs)


def test_expired_and_exhausted_budgets_never_start_an_extra_program(tmp_path, monkeypatch):
    native, fake = session(tmp_path, lambda *args: tools.Execution(0, "", "", []), calls=1)
    native.execute("one")
    result, _ = native.execute("two", True)
    assert result["error"]["code"] == "BUDGET_EXHAUSTED" and len(fake.programs) == 1
    monkeypatch.setattr(tools.time, "time", lambda: 20)
    native.deadline = 10
    native.execute("late", True)
    assert len(fake.programs) == 1 and not native.marker.exists()


def test_sealing_must_finish_before_the_wall_deadline(tmp_path, monkeypatch):
    clock = [0]
    monkeypatch.setattr(tools.time, "time", lambda: clock[0])
    def build(*args):
        native.workspace.joinpath("final.step").write_text("answer")
        return tools.Execution(0, "", "", [])
    native, _ = session(tmp_path, build, deadline=10)
    original = tools.shutil.copy2
    def slow_copy(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 11
        return result
    monkeypatch.setattr(tools.shutil, "copy2", slow_copy)
    data, _ = native.execute("final program", True)
    marker = json.loads(native.marker.read_text())
    assert not data["submitted"] and marker["status"] == "timeout" and "path" not in marker


def test_private_state_cannot_be_mounted_in_the_workbench(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        tools.NativeSession(tmp_path, tmp_path / "private", FakeExecutor(None), float("inf"))


def make_link(link, target):
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this host")


def test_program_path_cannot_overwrite_a_host_file_through_a_link(tmp_path):
    work, private = tmp_path / "work", tmp_path / "private"
    work.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    make_link(work / "_run.py", outside)
    executor = tools.DockerExecutor(work, private, "sha256:image", "desktop-linux", "test")
    with pytest.raises(ValueError, match="workbench"):
        executor.run("overwrite", 1, 1)
    assert outside.read_text() == "untouched"


def test_submitted_links_are_rejected_before_the_host_reads_them(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside.step"
    outside.write_text("outside")
    make_link(work / "final.step", outside)
    with pytest.raises(ValueError, match="workbench"):
        tools.checked_artifact(work / "final.step", work)


def test_native_artifact_precedence_requires_a_part_file(tmp_path):
    parts = tmp_path / "submission/parts"
    parts.mkdir(parents=True)
    instances = tmp_path / "submission/assembly/instances.json"
    instances.parent.mkdir()
    instances.write_text("[]")
    tmp_path.joinpath("pred_graph.json").write_text("{}")
    assert tools.artifact(tmp_path).name == "pred_graph.json"
    tmp_path.joinpath("final.step").write_text("step")
    assert tools.artifact(tmp_path).name == "final.step"
    parts.joinpath("a.STP").write_text("part")
    assert tools.artifact(tmp_path).name == "submission"


def test_docker_mount_excludes_private_state_and_reference_sources(tmp_path):
    work = tmp_path / "work"
    command = tools.DockerExecutor(work, tmp_path / "private", "sha256:fixed",
                                   "desktop-linux", "test").command(1)
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "2g"
    assert command[command.index("--cpus") + 1] == "1"
    assert command[command.index("-v") + 1] == f"{work}:/work"
    assert command.count("-v") == 1 and "--read-only" in command
    assert "sha256:fixed" in command and not any("private" in c for c in command)


def test_host_transport_ignores_python_modules_written_in_the_model_directory(tmp_path):
    command = runner.command(tmp_path / "work", tmp_path / "private/session.json", [], tmp_path / "final.txt")
    setting = next(v for v in command if v.startswith("mcp_servers.benchcad.args="))
    arguments = json.loads(setting.split("=", 1)[1])
    assert arguments[0] == "-I"
    assert not any(v.startswith("mcp_servers.agentcad.") for v in command)


def test_partial_events_and_duplicate_ids_do_not_reset_call_budget(tmp_path):
    path = tmp_path / "events.jsonl"
    progress = runner.CallProgress()
    event = lambda i: json.dumps({"type": "item.started", "item": {"type": "mcp_tool_call", "id": str(i)}})
    path.write_text(event(1) + "\n" + event(2)[:15])
    assert progress.poll(path) == 1
    with path.open("a") as stream:
        stream.write(event(2)[15:] + "\n" + event(1) + "\n")
        for i in range(3, 102):
            stream.write(event(i) + "\n")
    assert progress.poll(path) == 101
    assert progress.poll(path) == 101


def test_model_logs_identify_external_tools_and_failed_programs(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [{"type": "item.completed", "item": {"id": "1", "type": "mcp_tool_call",
                "server": "benchcad", "tool": "execute_python", "status": "completed",
                "result": {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": {"code": "PYTHON_EXECUTION_FAILED"}})}]}}},
              {"type": "item.completed", "item": {"id": "2", "type": "command_execution"}}]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    stats = runner.log_stats(path)
    assert stats["tool_calls_started"] == stats["tool_errors"] == 1
    assert stats["unexpected_tools"] == ["command_execution"]


def setup_scoring(tmp_path, submitted):
    protocol = {"benchcad_sha": runner.BENCH_SHA, "mesh_guard": "0", "threads": runner.shared.THREAD_ENV}
    tools.dump(tmp_path / "metadata.json", {"benchcad_sha": runner.BENCH_SHA, "scoring_protocol": protocol})
    for key in runner.CASE_IDS:
        tools.dump(tmp_path / key / "oracle.json", {"score": 1, "scoring_protocol": protocol})
    logs = tmp_path / "task1_case1/attempt-1"
    tools.dump(logs.parent / "run.json", {"status": "completed", "attempt": 1, "submitted": submitted, "logs": str(logs)})
    if submitted:
        logs.joinpath("sealed").mkdir(parents=True)
        logs.joinpath("sealed/final.step").write_text("sealed")
        tools.dump(logs / "answer.json", {"submitted": True, "path": "sealed/final.step"})
    return SimpleNamespace(out=tmp_path, resume=True, bench_source=tmp_path,
                           bench_python=Path(sys.executable), timeout=3600), protocol


def test_missing_answer_is_zero_and_does_not_invoke_the_evaluator(tmp_path, monkeypatch):
    args, _ = setup_scoring(tmp_path, False)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("No submission must not be graded"))
    result = runner.score_one("task1_case1", args)
    assert result["score"] == 0 and result["status"] == "no_submission"


def test_evaluator_failure_is_null_and_can_be_retried_offline(tmp_path, monkeypatch):
    args, protocol = setup_scoring(tmp_path, True)
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("scorer", 3600)
    monkeypatch.setattr(runner.subprocess, "run", timeout)
    failed = runner.score_one("task1_case1", args)
    assert failed["score"] is None and failed["status"] == "evaluator_error"
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"score":0.7}', stderr=""))
    recovered = runner.score_one("task1_case1", args)
    assert recovered["score"] == 0.7 and recovered["scoring_protocol"] == protocol


def test_mixed_scoring_protocols_cannot_produce_a_complete_aggregate(tmp_path):
    args, protocol = setup_scoring(tmp_path, False)
    for key in runner.CASE_IDS:
        tools.dump(tmp_path / key / "run.json", {"attempt": 1})
        tools.dump(tmp_path / key / "score.json", {"attempt": 1, "score": 1, "scoring_protocol": protocol})
    assert runner.summarize(tmp_path)["mean_of_task_means"] == 1
    changed = {**protocol, "mesh_guard": "1"}
    tools.dump(tmp_path / "task1_case1/score.json", {"attempt": 1, "score": 1, "scoring_protocol": changed})
    summary = runner.summarize(tmp_path)
    assert not summary["complete"] and summary["mean_of_task_means"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_nonfinite_or_out_of_range_scores_never_form_an_aggregate(tmp_path, value):
    args, protocol = setup_scoring(tmp_path, False)
    for key in runner.CASE_IDS:
        tools.dump(tmp_path / key / "run.json", {"attempt": 1})
        tools.dump(tmp_path / key / "score.json", {"attempt": 1, "score": 1, "scoring_protocol": protocol})
    (tmp_path / "task1_case1/score.json").write_text(json.dumps({"attempt": 1, "score": value, "scoring_protocol": protocol}))
    result = runner.summarize(tmp_path)
    assert not result["complete"] and result["mean_of_task_means"] is None
