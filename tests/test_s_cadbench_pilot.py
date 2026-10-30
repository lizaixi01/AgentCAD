"""Submission boundaries and honest failure accounting for the external V3 pilot."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("tomllib", reason="The optional CAD Bench harness requires Python 3.11+")
from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.service import Runtime


def load_example(name):
    path = Path(__file__).parents[1] / "examples" / "parametric_cad_bench" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"cadbench_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = load_example("pilot")
stages = load_example("stage_server")


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
    (task / "environment" / "drawing.png").write_bytes(b"public image")
    (task / "tests/grader" / "reference.FCStd").write_bytes(b"hidden reference")
    (task / "solution" / "answer.py").write_text("hidden solution", "utf-8")
    (task / "environment" / "Dockerfile").write_text("not an input", "utf-8")
    item = {"kind": "drawing", "instruction_sha256": pilot.digest(task / "instruction.md")}
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
    assert "run_script" not in server["enabled_tools"]
    assert "save_benchmark_stage" in server["enabled_tools"]


@pytest.mark.parametrize("foreign", ["shell", "other_mcp"])
def test_audit_detects_out_of_protocol_tools(tmp_path, foreign):
    log = tmp_path / "trajectory.jsonl"
    item = ({"type": "mcp_tool_call", "server": "other", "tool": "read"} if foreign == "other_mcp"
            else {"type": "command_execution", "command": "read reference"})
    log.write_text(json.dumps({"type": "item.completed", "item": item}) + "\n", "utf-8")
    assert len(pilot.audit_log(log)["unexpected_tools"]) == 1


@pytest.mark.parametrize("has_output", [False, True])
def test_missing_submission_is_zero_but_scorer_crash_is_infrastructure_error(tmp_path, monkeypatch, has_output):
    item = {"id": "sample", "kind": "create"}
    args = argparse.Namespace(dataset=tmp_path / "dataset", workspaces=tmp_path / "workspaces",
                              output=tmp_path / "logs", freecad=tmp_path / "FreeCAD",
                              scorer_python=tmp_path / "scorer-python")
    workspace = args.workspaces / "sample"
    workspace.mkdir(parents=True)
    pilot.write_json(args.output / "sample" / "run.json", {"unexpected_tools": []})
    if has_output:
        (workspace / "answer.FCStd").write_bytes(b"candidate")
    def crash(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1)
    monkeypatch.setattr(pilot.subprocess, "run", crash)
    result = pilot.score_one(item, args)["evaluation"]
    assert result["status"] == ("scorer_error" if has_output else "missing_output")
    assert result["score"] == (None if has_output else 0)
