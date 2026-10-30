"""Adversarial checks on the evaluator: server claims cannot replace file evidence."""
import asyncio
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "examples" / "autocad_benchmark" / "run.py"
SPEC = importlib.util.spec_from_file_location("upstream_benchmark", SOURCE)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def roundtrip_reports():
    before = {"failed": [], "constraints": [{"id": key, "actual": value} for key, value in
              [("R1", 20), ("R2", 90), ("R3", math.hypot(45, 25))]],
              "count": [{"id": "R4", "status": "pass", "actual": 4}]}
    after = deepcopy(before)
    after["failed"] = ["R3"]
    after["constraints"][2]["actual"] = math.hypot(48, 25)
    return before, after, deepcopy(after)


def test_roundtrip_gates_all_measurements_and_fresh_read():
    reports = roundtrip_reports()
    assert benchmark.grade_roundtrip(*reports, parity_unchanged=True, bores_moved=1)
    # Counts/extents alone cannot see the moved interior bore.
    assert not benchmark.grade_roundtrip(reports[0], reports[0], reports[0], parity_unchanged=True, bores_moved=1)
    assert not benchmark.grade_roundtrip(*reports, parity_unchanged=False, bores_moved=1)
    assert not benchmark.grade_roundtrip(*reports, parity_unchanged=True, bores_moved=2)


@pytest.mark.parametrize("defect", ["missing_row", "wrong_count", "wrong_diameter", "stale_fresh_reader"])
def test_roundtrip_rejects_incomplete_or_inaccurate_evidence(defect):
    before, after, fresh = roundtrip_reports()
    if defect == "missing_row":
        before["constraints"].pop(1)
    elif defect == "wrong_count":
        before["count"][0]["actual"] = 5
    elif defect == "wrong_diameter":
        after["constraints"][0]["actual"] = 21
    else:
        fresh["constraints"][2]["actual"] = math.hypot(45, 25)
    assert not benchmark.grade_roundtrip(before, after, fresh, parity_unchanged=True, bores_moved=1)


def test_move_claim_cannot_pass_with_an_unchanged_saved_file(tmp_path, monkeypatch):
    adapter = object.__new__(benchmark.AgentCADAdapter)
    adapter.workspace, adapter.path = tmp_path, "drawing.dxf"
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.saveas(tmp_path / adapter.path)

    async def no_op(*args, **kwargs):
        return {"ok": True}

    async def claimed_inspection(**kwargs):
        return {"entities": [{"start": [5, 2], "end": [15, 2]}]}

    monkeypatch.setattr(adapter, "apply", no_op)
    monkeypatch.setattr(adapter, "inspect", claimed_inspection)
    monkeypatch.setattr(benchmark, "strict_result", lambda task, passed, *args, **kw: passed)
    assert not asyncio.run(adapter.task_modify_query())


def test_geometry_claim_cannot_pass_with_a_wrong_saved_line(tmp_path, monkeypatch):
    adapter = object.__new__(benchmark.AgentCADAdapter)
    adapter.workspace, adapter.path = tmp_path, "drawing.dxf"
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (300, 400))
    doc.modelspace().add_circle((10, 10), 2)
    doc.saveas(tmp_path / adapter.path)

    async def no_op(*args, **kwargs):
        return {"ok": True}

    async def claimed_inspection(**kwargs):
        return {"entities": [{"length": 5}]}

    monkeypatch.setattr(adapter, "apply", no_op)
    monkeypatch.setattr(adapter, "inspect", claimed_inspection)
    monkeypatch.setattr(benchmark, "strict_result", lambda task, passed, *args, **kw: passed)
    assert not asyncio.run(adapter.task_core_geometry())


@pytest.mark.parametrize("as_dict", [False, True])
def test_reference_artifacts_survive_later_task_overwrites(tmp_path, as_dict):
    spec = importlib.util.spec_from_file_location("capture_reference", SOURCE.with_name("capture_reference.py"))
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    original = tmp_path / "shared.dxf"
    original.write_bytes(b"task A original bytes")
    artifact = {"path": str(original), "filename": original.name} if as_dict else str(original)
    result = SimpleNamespace(task_id="A", status="pass", score=100, metrics={"count": 1}, artifacts=[artifact])
    capture.preserve_artifacts(result, tmp_path / "retained")
    original.write_bytes(b"task B overwrites the same path")
    kept = result.artifacts[0]
    target = Path(kept["path"] if as_dict else kept)
    assert target.read_bytes() == b"task A original bytes"
    assert result.status == "pass" and result.score == 100 and result.metrics == {"count": 1}
