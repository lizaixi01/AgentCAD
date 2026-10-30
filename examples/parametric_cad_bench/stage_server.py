"""AgentCAD plus a file-only submission adapter for the local CAD Bench pilot.

The adapter freezes the same working part before/after an edit. It never supplies
modeling operations, reference geometry, or grader feedback to the agent.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Literal

from agentcad.mcp_server import build_server
from agentcad.policy import Policy
from agentcad.service import Runtime


def save_stage(root: Path, kind: str, stage: str, runtime: Runtime) -> dict:
    expected = {"create": {"final": "answer.FCStd"},
                "drawing": {"final": "answer.FCStd"},
                "edit": {"base": "answer_base.FCStd", "final": "answer_edit.FCStd"}}
    if stage not in expected.get(kind, {}):
        return {"ok": False, "error": {"code": "BAD_STAGE"}}
    if kind == "edit" and stage == "final" and not (root / "answer_base.FCStd").is_file():
        return {"ok": False, "error": {"code": "BASE_REQUIRED", "message": "Save the base before editing."}}
    destination = root / expected[kind][stage]
    if destination.exists():
        return {"ok": False, "error": {"code": "STAGE_ALREADY_SAVED",
                                       "message": "Submission stages are immutable in a single attempt."}}
    source = root / "part.FCStd"
    if source.is_symlink() or destination.is_symlink():
        return {"ok": False, "error": {"code": "SYMLINK_REJECTED"}}
    report = runtime.validate_drawing("part.FCStd", detail=True)
    if not report.get("ok") or not report.get("validation", {}).get("passed"):
        return {"ok": False, "error": {"code": "INVALID_PART"}, "validation": report}
    temporary = destination.with_suffix(".stage-tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    record = {"stage": stage, "output": destination.name,
              "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    with (root / "stages.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    return {"ok": True, **record}


def main() -> None:
    policy = Policy(allow_scripts=False)
    server = build_server(policy)
    runtime = Runtime(policy)
    kind = os.environ["CADBENCH_KIND"]

    @server.tool()
    def save_benchmark_stage(stage: Literal["base", "final"]) -> dict:
        """Freeze part.FCStd as a submission. Edit tasks: base FIRST, then edit the SAME
        part.FCStd and save final. Other tasks: final only. Each stage can be saved once.
        This copies your own file; it does not grade it against the hidden answer."""
        return save_stage(policy.root, kind, stage, runtime)

    server.run("stdio")


if __name__ == "__main__":
    main()
