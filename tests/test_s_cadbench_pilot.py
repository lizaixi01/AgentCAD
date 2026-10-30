"""Submission boundaries and honest failure accounting for the external V3 pilot."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11),
                              reason="The optional CAD Bench harness requires Python 3.11+")
from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.service import Runtime


def load_example(name):
    path = Path(__file__).parents[1] / "examples" / "parametric_cad_bench" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"cadbench_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = load_example("pilot") if sys.version_info >= (3, 11) else None
stages = load_example("stage_server") if sys.version_info >= (3, 11) else None


def test_selection_is_repeatable_stratified_and_detects_incomplete_cohort(tmp_path):
    for kind, tag in pilot.GROUPS.items():
        for index in range({"create": 30, "edit": 30, "drawing": 40}[kind]):
            task = tmp_path / f"{kind}-{index:02}"
            task.mkdir()
            (task / "task.toml").write_text(
                f'[task]\ndescription="sample"\n[metadata]\ngnucleus_source_date="{tag}"\n', "utf-8")
            (task / "instruction.md").write_text(f"{kind} {index}", "utf-8")
    selected = pilot.select_tasks(tmp_path, 2, 42)
    assert selected == pilot.select_tasks(tmp_path, 2, 42)
    assert [row["kind"] for row in selected] == ["create"] * 2 + ["edit"] * 2 + ["drawing"] * 2
    assert len({row["id"] for row in selected}) == 6
    (tmp_path / "create-00" / "task.toml").unlink()
    with pytest.raises(ValueError, match="expected V3 cohort"):
        pilot.select_tasks(tmp_path, 2, 42)


def test_staging_excludes_grader_solution_and_checks_instruction_hash(tmp_path):
    task, workspace = tmp_path / "task", tmp_path / "workspace"
    for name in ("environment", "tests/grader", "solution"):
        (task / name).mkdir(parents=True)
    (task / "instruction.md").write_text("Public instruction", "utf-8")
    (task / "task.toml").write_text("Public metadata", "utf-8")
    (task / "environment" / "drawing.png").write_bytes(b"public image")
    (task / "tests/grader" / "reference.FCStd").write_bytes(b"hidden reference")
    (task / "solution" / "answer.py").write_text("hidden solution", "utf-8")
    (task / "environment" / "Dockerfile").write_text("not an input", "utf-8")
    item = {"kind": "drawing", "instruction_sha256": pilot.digest(task / "instruction.md"),
            "task_toml_sha256": pilot.digest(task / "task.toml")}
    assert pilot.stage_inputs(task, workspace, item) == [workspace / "drawing.png"]
    assert {p.name for p in workspace.iterdir()} == {"instruction.md", "drawing.png"}
    (task / "instruction.md").write_text("Changed", "utf-8")
    with pytest.raises(ValueError, match="changed since selection"):
        pilot.stage_inputs(task, tmp_path / "second", item)


def test_failed_validation_cannot_freeze_submission(tmp_path):
    class Invalid:
        def validate_drawing(self, *args, **kwargs):
            return {"ok": True, "validation": {"passed": False}}
    (tmp_path / "part.FCStd").write_bytes(b"invalid")
    result = stages.save_stage(tmp_path, "create", "final", Invalid())
    assert result["error"]["code"] == "INVALID_PART"
    assert not (tmp_path / "answer.FCStd").exists()


@pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed")
def test_real_native_edit_stages_preserve_base_and_are_immutable(tmp_path):
    runtime = Runtime(Policy(root=tmp_path))
    first = runtime.apply_operations("part.FCStd", [
        {"op": "primitive", "kind": "box", "dims": {"length": 20, "width": 10, "height": 5}}
    ], create={"units": "mm"})
    assert first["ok"], first
    assert stages.save_stage(tmp_path, "edit", "final", runtime)["error"]["code"] == "BASE_REQUIRED"
    base = stages.save_stage(tmp_path, "edit", "base", runtime)
    assert base["ok"], base
    original = (tmp_path / "answer_base.FCStd").read_bytes()
    # A second valid working model must not change the frozen base.
    replacement = runtime.apply_operations("second.FCStd", [
        {"op": "primitive", "kind": "box", "dims": {"length": 30, "width": 10, "height": 5}}
    ], create={"units": "mm"})
    assert replacement["ok"], replacement
    (tmp_path / "part.FCStd").write_bytes((tmp_path / "second.FCStd").read_bytes())
    final = stages.save_stage(tmp_path, "edit", "final", runtime)
    assert final["ok"], final
    assert (tmp_path / "answer_base.FCStd").read_bytes() == original
    assert final["sha256"] != base["sha256"]
    assert stages.save_stage(tmp_path, "edit", "base", runtime)["error"]["code"] == "STAGE_ALREADY_SAVED"
    assert len((tmp_path / "stages.jsonl").read_text("utf-8").splitlines()) == 2


def test_command_limits_tools_and_does_not_load_personal_configuration(tmp_path):
    args = argparse.Namespace(freecad=tmp_path / "FreeCAD", model="model", effort="xhigh")
    cmd = pilot.command(tmp_path / "workspace", {"kind": "edit"}, args, [])
    assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd
    assert "features.shell_tool=false" in cmd and 'web_search="disabled"' in cmd
    import tomllib
    settings = tomllib.loads("\n".join(cmd[index + 1] for index, value in enumerate(cmd[:-1]) if value == "-c"))
    server = settings["mcp_servers"]["agentcad"]
    assert server["required"] is True
    assert server["env"]["AGENTCAD_ALLOW_SCRIPTS"] == "0"
    assert server["env"]["AGENTCAD_TOOL_PROFILE"] == "full"
    assert "measure_entities" in server["enabled_tools"]
    assert "run_script" not in server["enabled_tools"]
    assert "save_benchmark_stage" in server["enabled_tools"]


@pytest.mark.parametrize("foreign", ["shell", "other_mcp"])
def test_audit_detects_out_of_protocol_tools(tmp_path, foreign):
    log = tmp_path / "trajectory.jsonl"
    item = ({"type": "mcp_tool_call", "server": "other", "tool": "read"} if foreign == "other_mcp"
            else {"type": "command_execution", "command": "read reference"})
    log.write_text(json.dumps({"type": "item.completed", "item": item}) + "\n", "utf-8")
    assert len(pilot.audit_log(log)["unexpected_tools"]) == 1


@pytest.mark.parametrize("body,expected", [
    ("Error executing tool: max_size must be <= 2048", "MCP_TOOL_ERROR"),
    (json.dumps({"ok": False, "error": {"code": "BAD_IMAGE_REGION", "message": "Outside image"}}),
     "BAD_IMAGE_REGION"),
])
def test_audit_counts_mcp_failures_without_double_counting_runtime_errors(tmp_path, body, expected):
    log = tmp_path / "trajectory.jsonl"
    log.write_text(json.dumps({"type": "item.completed", "item": {
        "type": "mcp_tool_call", "server": "agentcad", "tool": "inspect_image", "status": "failed",
        "result": {"content": [{"type": "text", "text": body}]}}}) + "\n", "utf-8")
    errors = pilot.audit_log(log)["tool_errors"]
    assert len(errors) == 1 and errors[0]["code"] == expected


@pytest.mark.parametrize("has_output", [False, True])
def test_missing_submission_is_zero_but_scorer_crash_is_infrastructure_error(tmp_path, monkeypatch, has_output):
    item = {"id": "sample", "kind": "create"}
    args = argparse.Namespace(dataset=tmp_path / "dataset", workspaces=tmp_path / "workspaces",
                              output=tmp_path / "logs", freecad=tmp_path / "FreeCAD",
                              scorer_python=tmp_path / "scorer-python")
    workspace = args.workspaces / "sample"
    workspace.mkdir(parents=True)
    if has_output:
        (workspace / "answer.FCStd").write_bytes(b"candidate")
        (workspace / "stages.jsonl").write_text(json.dumps({
            "stage": "final", "output": "answer.FCStd", "sha256": pilot.digest(workspace / "answer.FCStd")
        }) + "\n", "utf-8")
    pilot.write_json(args.output / "sample" / "run.json", {
        "status": "done", "unexpected_tools": [],
        "outputs": {"answer.FCStd": pilot.digest(workspace / "answer.FCStd")} if has_output else {}})
    def crash(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1)
    monkeypatch.setattr(pilot.subprocess, "run", crash)
    result = pilot.score_one(item, args)["evaluation"]
    assert result["status"] == ("scorer_error" if has_output else "missing_output")
    assert result["score"] == (None if has_output else 0)


def test_stage_audit_detects_base_modified_after_freeze(tmp_path):
    outputs = {}
    records = []
    for stage, name in [("base", "answer_base.FCStd"), ("final", "answer_edit.FCStd")]:
        (tmp_path / name).write_bytes(stage.encode())
        outputs[name] = pilot.digest(tmp_path / name)
        records.append({"stage": stage, "output": name, "sha256": outputs[name]})
    (tmp_path / "stages.jsonl").write_text("\n".join(json.dumps(record) for record in records), "utf-8")
    assert pilot.stage_errors(tmp_path, "edit", outputs) == []
    (tmp_path / "answer_base.FCStd").write_bytes(b"changed by a tool after saving")
    assert pilot.stage_errors(tmp_path, "edit", outputs) == ["Stage changed after submission: answer_base.FCStd"]


def test_timeout_with_saved_file_is_still_zero(tmp_path):
    args = argparse.Namespace(dataset=tmp_path / "dataset", workspaces=tmp_path / "workspaces",
                              output=tmp_path / "logs")
    workspace = args.workspaces / "sample"
    workspace.mkdir(parents=True)
    (workspace / "answer.FCStd").write_bytes(b"saved before timeout")
    pilot.write_json(args.output / "sample" / "run.json", {"status": "timeout", "unexpected_tools": []})
    result = pilot.score_one({"id": "sample", "kind": "create"}, args)["evaluation"]
    assert result == {"score": 0, "status": "agent_failed", "agent_status": "timeout"}


def test_summary_combines_incremental_results_and_preserves_infrastructure_errors(tmp_path):
    rows = [{"id": "first", "kind": "create", "evaluation": {"score": 1}},
            {"id": "second", "kind": "create", "evaluation": {"score": 0}},
            {"id": "third", "kind": "edit", "evaluation": {"score": None}}]
    pilot.summarize({"tasks": []}, rows, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert summary["groups"]["create"] == {"tasks": 2, "mean": 0.5}
    assert summary["tasks"] == 3 and summary["mean"] is None
    assert summary["infrastructure_errors"] == 1


@pytest.mark.parametrize("sidecar_key", ["score", "reward"])
def test_score_reader_uses_harbor_contract_for_both_task_schemas(tmp_path, sidecar_key):
    pilot.write_json(tmp_path / "reward.json", {"reward": 0.525481})
    pilot.write_json(tmp_path / "reward_details.json", {sidecar_key: 0.5254809867, "combined": 0.5254809867})
    result = pilot.read_score(tmp_path)
    assert result["score"] == 0.525481
    assert result["combined"] == 0.5254809867


@pytest.mark.parametrize("reward", [True, None, float("nan"), 1.1])
def test_score_reader_rejects_invalid_rewards(tmp_path, reward):
    pilot.write_json(tmp_path / "reward.json", {"reward": reward})
    with pytest.raises(ValueError):
        pilot.read_score(tmp_path)


def test_regression_selection_uses_baseline_and_detects_input_or_config_changes(tmp_path):
    task = tmp_path / "dataset" / "plate"
    (task / "environment").mkdir(parents=True)
    (task / "instruction.md").write_text("public instruction", "utf-8")
    (task / "task.toml").write_text("metadata", "utf-8")
    (task / "environment" / "input.png").write_bytes(b"original drawing")
    item = {"id": "plate", "kind": "drawing", "instruction_sha256": pilot.digest(task / "instruction.md"),
            "task_toml_sha256": pilot.digest(task / "task.toml"),
            "public_input_sha256": {"input.png": pilot.digest(task / "environment" / "input.png")}}
    baseline = tmp_path / "baseline.json"
    pilot.write_json(baseline, {"benchmark": "gnucleus-ai/cad-bench@v3", "model": "test", "tasks": [item]})
    selected, reference = pilot.repeat_selection(baseline, task.parent, ["plate"], {"model": "test"})
    assert selected == [item] and reference["sha256"] == pilot.digest(baseline)
    with pytest.raises(ValueError, match="differs from the baseline"):
        pilot.repeat_selection(baseline, task.parent, ["plate"], {"model": "different"})
    with pytest.raises(ValueError, match="outside the baseline"):
        pilot.repeat_selection(baseline, task.parent, ["unseen"], {"model": "test"})
    (task / "environment" / "input.png").write_bytes(b"changed drawing")
    with pytest.raises(ValueError, match="drawing input changed"):
        pilot.repeat_selection(baseline, task.parent, ["plate"], {"model": "test"})
