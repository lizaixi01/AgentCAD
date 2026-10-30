"""Freeze a new drawing cohort before inspecting inputs or running any model.

This preparation-only script never opens graders, solutions or reference CAD.
It uses the existing pilot runner and scorer without altering their behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tomllib


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--history", type=Path, nargs="+", required=True)
    parser.add_argument("--previous-workspaces", type=Path, nargs="+", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError("Use a new output directory outside the dataset")
    baseline = json.loads(args.baseline.read_text("utf-8"))
    if baseline["benchmark"] != "gnucleus-ai/cad-bench@v3":
        raise ValueError("Unexpected baseline benchmark")
    seen, histories, workspace_inventory = set(), [], []
    for path in sorted(set(p.resolve() for p in args.history)):
        history = json.loads(path.read_text("utf-8"))
        if history["benchmark"] != baseline["benchmark"]:
            raise ValueError(f"Unexpected history benchmark: {path}")
        seen.update(item["id"] for item in history["tasks"])
        histories.append({"path": str(path), "sha256": digest(path), "manifest": history})
    for path in sorted(set(p.resolve() for p in args.previous_workspaces)):
        ids = sorted(p.name for p in path.iterdir() if p.is_dir() and p.name.startswith("freecad-"))
        seen.update(ids)
        workspace_inventory.append({"path": str(path), "task_directories": ids})
    cohort = []
    for path in sorted(dataset.glob("*/task.toml")):
        metadata = tomllib.loads(path.read_text("utf-8"))
        if metadata["metadata"]["gnucleus_source_date"] == "v3-bench":
            cohort.append((path.parent, metadata))
    if len(cohort) != 40:
        raise ValueError("Expected exactly 40 V3 drawing tasks")
    candidates = [(p, m) for p, m in cohort if p.name not in seen]
    if not 1 <= args.count <= len(candidates):
        raise ValueError("Requested count exceeds the unseen drawing cohort")
    selected = random.Random(baseline["seed"]).sample(candidates, args.count)
    items = []
    for path, metadata in selected:
        images = sorted((path / "environment").glob("*.png"))
        if not images or any(p.is_symlink() for p in images):
            raise ValueError(f"Missing or symlinked drawing input: {path.name}")
        items.append({"id": path.name, "kind": "drawing", "description": metadata["task"]["description"],
                      "instruction_sha256": digest(path / "instruction.md"),
                      "task_toml_sha256": digest(path / "task.toml"),
                      "public_input_sha256": {p.name: digest(p) for p in images}})
    example = Path(__file__).resolve().parents[2]
    repo = example.parents[1]
    selection = {"algorithm": "random.Random(seed).sample(sorted eligible drawing task IDs, count)",
                 "seed": baseline["seed"], "count": args.count,
                 "cohort_ids": [p.name for p, _ in cohort], "eligible_ids": [p.name for p, _ in candidates],
                 "excluded_drawing_ids": [p.name for p, _ in cohort if p.name in seen],
                 "all_seen_ids": sorted(seen), "history": histories,
                 "previous_workspace_inventory": workspace_inventory,
                 "selected_ids": [item["id"] for item in items], "selector_sha256": digest(Path(__file__))}
    manifest = {key: baseline[key] for key in ("benchmark", "expected_dataset_digest", "seed", "model",
                                              "effort", "timeout_sec", "jobs")}
    manifest.update(digest_verified=False, official_submission=False,
                    purpose="new drawing holdout after dimension-reading optimization; one attempt per task",
                    selection="seeded sample of previously unrun drawing tasks, frozen before viewing",
                    agentcad_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                    codex_version=subprocess.check_output(["codex", "--version"], text=True).strip(), tasks=items,
                    baseline={"path": str(args.baseline.resolve()), "sha256": digest(args.baseline)},
                    harness_sha256={name: digest(example / name) for name in ("pilot.py", "stage_server.py")})
    output.mkdir(parents=True, exist_ok=False)
    selection_path = output / "selection.json"
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", "utf-8")
    manifest["selection_sha256"] = digest(selection_path)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"selected": selection["selected_ids"], "eligible": len(candidates),
                      "excluded": selection["excluded_drawing_ids"], "manifest": str(output / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
