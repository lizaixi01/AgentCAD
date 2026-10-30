"""Archive every frozen attempt, including failures; never repair or rescore it.

Raw trajectories (which contain input-image pixels) stay in the external run
directory. This ledger keeps their hashes and structured non-image evidence.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

from agentcad.policy import Policy
from agentcad.service import Runtime


def bodies(result):
    for block in (result or {}).get("content", []):
        if block.get("type") != "text":
            continue
        try:
            value = json.loads(block["text"])
        except (ValueError, KeyError):
            continue
        if not isinstance(value, dict):
            continue
        if "ok" in value:
            yield value
        if "content" in value:
            yield from bodies(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    artifact = Path(__file__).resolve().parent
    example = artifact.parents[1]
    spec = importlib.util.spec_from_file_location("pilot", example / "pilot.py")
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    ledger_path = example / "unseen-drawings-2026-10-30.json"
    if ledger_path.exists():
        raise FileExistsError("Do not overwrite a collected experiment")
    manifest = json.loads((args.run / "manifest.json").read_text("utf-8"))
    selection = json.loads((args.run / "selection.json").read_text("utf-8"))
    assert pilot.digest(args.run / "selection.json") == manifest["selection_sha256"]
    assert [t["id"] for t in manifest["tasks"]] == selection["selected_ids"]
    assert not set(selection["selected_ids"]) & set(selection["all_seen_ids"])
    assert all((args.run / t["id"] / "result.json").is_file() for t in manifest["tasks"])
    cases = []
    for item in manifest["tasks"]:
        folder = args.run / item["id"]
        result = json.loads((folder / "result.json").read_text("utf-8"))
        workspace = Path(result["workspace"])
        assert all(pilot.digest(workspace / name) == sha for name, sha in item["public_input_sha256"].items())
        events, unparsable = [], 0
        for line in (folder / "trajectory.jsonl").read_text("utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                unparsable += 1  # retain truncated timeout output in the raw trace
        calls = [e["item"] for e in events if e.get("type") == "item.completed"
                 and e.get("item", {}).get("type") == "mcp_tool_call"]
        destination = artifact / item["id"]
        destination.mkdir(exist_ok=False)
        archived = []

        def preserve(source, category):
            relative = source.relative_to(workspace) if source.is_relative_to(workspace) else Path(source.name)
            target = destination / relative
            if target.exists():
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            archived.append({"kind": category, "path": target.relative_to(example).as_posix(),
                             "sha256": pilot.digest(source), "bytes": source.stat().st_size})

        # Immutable submissions and any different unfinished working file are distinct.
        native_files = list(sorted(workspace.glob("*.FCStd")))
        for native in native_files:
            preserve(native, "submitted_native" if native.name == "answer.FCStd" else "working_native")
        previews = []
        successful_edits = [i for i, c in enumerate(calls) if c["tool"] in ("apply_operations", "rollback")
                            and any(b.get("ok") for b in bodies(c.get("result")))]
        for i, call in enumerate(calls):
            if call["tool"] != "export_drawing" or not any(b.get("ok") for b in bodies(call.get("result"))):
                continue
            output = call["arguments"].get("output", "")
            source = (workspace / output).resolve()
            if not source.is_relative_to(workspace.resolve()) or not source.is_file():
                continue
            if source.suffix.lower() != ".png":
                continue
            previews.append({"tool_call_id": call["id"], "output": output,
                             "after_last_successful_model_edit": not successful_edits or i > max(successful_edits)})
        # Files can have been overwritten by a later export in the same attempt.
        for output in dict.fromkeys(p["output"] for p in previews):
            preserve(workspace / output, "agent_preview_final_bytes")
        for name in ("run.json", "result.json"):
            preserve(folder / name, "run_record")
        if (workspace / "stages.jsonl").is_file():
            preserve(workspace / "stages.jsonl", "stage_record")
        validation, object_types = None, None
        candidate = workspace / "answer.FCStd"
        if candidate.is_file():
            before = pilot.digest(candidate)
            validation = Runtime(Policy(root=workspace, read_only=True)).validate_drawing(candidate.name, detail=True)
            assert pilot.digest(candidate) == before
            try:
                with zipfile.ZipFile(candidate) as archive:
                    document = ET.fromstring(archive.read("Document.xml"))
                object_types = dict(collections.Counter(o.attrib["type"] for o in document.findall("./Objects/Object")))
            except (zipfile.BadZipFile, KeyError, ET.ParseError):
                object_types = {"unreadable_native_document": True}
        if result["evaluation"]["status"] == "scored":
            assert pilot.read_score(folder / "score") == result["evaluation"]
        first_build = next((i for i, c in enumerate(calls) if c["tool"] == "apply_operations"), len(calls))
        anchor_calls = []
        image_calls = []
        for i, call in enumerate(calls):
            if call["tool"] != "inspect_image":
                continue
            metadata = [{key: b[key] for key in ("ok", "source_sha256", "source_size", "region", "rotate",
                                                 "dimension_evidence", "panels", "error") if key in b}
                        for b in bodies(call.get("result"))]
            image_calls.append({"tool_call_id": call["id"], "arguments": call["arguments"], "metadata": metadata})
            if call["arguments"].get("dimensions") and any(b.get("ok") for b in metadata):
                anchor_calls.append({"tool_call_id": call["id"], "before_first_build": i < first_build})
        cases.append({**result, "artifact_files": archived, "preview_calls": previews,
                      "stage_audit_errors": pilot.stage_errors(workspace, item["kind"], result["outputs"]),
                      "unparsable_trajectory_lines": unparsable, "posthoc_validation": validation,
                      "native_object_types": object_types, "anchor_calls": anchor_calls, "image_calls": image_calls,
                      "geometry_check_calls": [{"tool": c["tool"], "arguments": c["arguments"],
                                                "result": list(bodies(c.get("result")))} for c in calls
                                               if c["tool"] in ("measure_entities", "validate_drawing")],
                      "agent_messages": [e["item"]["text"] for e in events if e.get("type") == "item.completed"
                                         and e.get("item", {}).get("type") == "agent_message"],
                      "raw_files_sha256": {p.relative_to(folder).as_posix(): pilot.digest(p)
                                           for p in sorted(folder.rglob("*")) if p.is_file()},
                      "scorer_sha256": pilot.digest(args.dataset / item["id"] / "tests/run_scorer.py")})
    scores = [case["evaluation"]["score"] for case in cases]
    ledger = {"date": "2026-10-30", "benchmark": manifest["benchmark"], "official_submission": False,
              "manifest": manifest, "manifest_sha256": pilot.digest(args.run / "manifest.json"),
              "selection_path": (artifact / "selection.json").relative_to(example).as_posix(),
              "selection_sha256": pilot.digest(args.run / "selection.json"), "raw_directory": str(args.run.resolve()),
              "conditions": {"freecad": "1.1.4", "occt": "7.8.1", "python": "3.11.16",
                             "validator": "0.6.0", "scorer": "v2", "attempts_per_task": 1,
                             "manual_repairs": False, "hidden_reference_given_to_agents": False,
                             "source_images_redistributed": False, "scripts_enabled": False},
              "tasks": len(cases), "mean_reward": sum(scores)/len(scores) if None not in scores else None,
              "infrastructure_errors": sum(score is None for score in scores), "cases": cases}
    pilot.write_json(ledger_path, ledger)
    print(json.dumps({"mean_reward": ledger["mean_reward"], "cases": [
        {"id": c["id"], "status": c["status"], "evaluation": c["evaluation"],
         "anchors": c["anchor_calls"], "errors": c["tool_errors"]} for c in cases]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
