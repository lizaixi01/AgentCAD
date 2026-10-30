"""Stratified local smoke test on the frozen Parametric CAD Bench V3 tasks.

Download separately with Harbor 0.23.0; only instruction.md and environment
images enter each agent workspace. Scoring runs AFTER agents finish, outside
those workspaces, with the task's own run_scorer.py and validator 0.6.0.
This is a local MCP pilot, not a Harbor leaderboard submission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PYTHON = Path(sys.executable).resolve()
GROUPS = {"create": "v3-bench-create", "edit": "v3-bench-create-edit", "drawing": "v3-bench"}
EXPECTED_DIGEST = "sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a"
TOOLS = ["list_operations", "create_drawing", "read_drawing", "inspect_entities", "apply_operations",
         "validate_drawing", "export_drawing", "rollback", "history", "get_diff", "list_checkpoints",
         "save_benchmark_stage"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def select_tasks(dataset: Path, count: int, seed: int) -> list[dict]:
    randomizer = random.Random(seed)
    tasks = [(p.parent, tomllib.loads(p.read_text("utf-8"))) for p in sorted(dataset.glob("*/task.toml"))]
    selected = []
    for kind, tag in GROUPS.items():
        candidates = [(p, meta) for p, meta in tasks if meta["metadata"]["gnucleus_source_date"] == tag]
        if len(candidates) != {"create": 30, "edit": 30, "drawing": 40}[kind]:
            raise ValueError(f"Not the expected V3 cohort: {kind} has {len(candidates)} tasks")
        for path, meta in randomizer.sample(candidates, count):
            selected.append({"id": path.name, "kind": kind, "description": meta["task"]["description"],
                             "instruction_sha256": digest(path / "instruction.md"),
                             "task_toml_sha256": digest(path / "task.toml")})
    return selected


def stage_inputs(task: Path, workspace: Path, item: dict) -> list[Path]:
    if digest(task / "instruction.md") != item["instruction_sha256"]:
        raise ValueError("Task instruction changed since selection")
    workspace.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(task / "instruction.md", workspace / "instruction.md")
    images = []
    for source in sorted((task / "environment").glob("*.png")):
        if source.is_symlink():
            raise ValueError("Task input image is a symlink")
        destination = workspace / source.name
        shutil.copyfile(source, destination)
        images.append(destination)
    if item["kind"] == "drawing" and not images:
        raise ValueError("Engineering drawing input is missing")
    return images


def command(workspace: Path, item: dict, args: argparse.Namespace, images: list[Path]) -> list[str]:
    server_env = {"AGENTCAD_ROOT": workspace.as_posix(), "AGENTCAD_FREECAD": args.freecad.as_posix(),
                  "AGENTCAD_ALLOW_SCRIPTS": "0", "AGENTCAD_VIEWER": "0", "AGENTCAD_LIVE_SYNC": "0",
                  "CADBENCH_KIND": item["kind"], "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    env_toml = ",".join(f"{key}={json.dumps(value)}" for key, value in server_env.items())
    cmd = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
           "--json", "-s", "read-only", "-C", str(workspace), "-m", args.model,
           "-c", f'model_reasoning_effort="{args.effort}"', "-c", 'approval_policy="never"',
           "-c", 'web_search="disabled"', "-c", "features.shell_tool=false",
           "-c", "features.multi_agent=false", "-c", "features.apps=false", "-c", "features.js_repl=false",
           "-c", "project_doc_max_bytes=0", "-c", f'mcp_servers.agentcad.command={json.dumps(PYTHON.as_posix())}',
           "-c", "mcp_servers.agentcad.args=" + json.dumps([str(HERE / "stage_server.py").replace("\\", "/")]),
           "-c", "mcp_servers.agentcad.env={" + env_toml + "}",
           "-c", 'mcp_servers.agentcad.default_tools_approval_mode="approve"',
           "-c", "mcp_servers.agentcad.enabled_tools=" + json.dumps(TOOLS),
           "-c", "mcp_servers.agentcad.tool_timeout_sec=300", "-c", "mcp_servers.agentcad.required=true"]
    for image in images:
        cmd.extend(["-i", str(image)])
    return cmd + ["-"]


def audit_log(log: Path) -> dict:
    tools, errors, foreign, usage = [], [], [], None
    for line in log.read_text("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
        if event.get("type") != "item.completed":
            continue
        kind = item.get("type")
        if kind == "mcp_tool_call":
            tools.append(item.get("tool"))
            if item.get("server") != "agentcad":
                foreign.append(item)
            for block in (item.get("result") or {}).get("content", []):
                if block.get("type") != "text":
                    continue
                try:
                    body = json.loads(block["text"])
                except (ValueError, KeyError):
                    continue
                if body.get("ok") is False:
                    error = body.get("error", {})
                    errors.append({"tool": item.get("tool"), "code": error.get("code"),
                                   "message": error.get("message", "")[:300]})
        elif kind not in {"reasoning", "agent_message", "image_view"}:
            foreign.append({"type": kind, "id": item.get("id")})
    return {"tool_calls": len(tools), "tools": tools, "tool_errors": errors,
            "unexpected_tools": foreign, "usage": usage}


def run_one(item: dict, args: argparse.Namespace) -> dict:
    task = args.dataset / item["id"]
    workspace = args.workspaces / item["id"]
    output = args.output / item["id"]
    output.mkdir(parents=True, exist_ok=False)
    images = stage_inputs(task, workspace, item)
    prompt = (task / "instruction.md").read_text("utf-8") + """

LOCAL MCP PILOT ADAPTATION (not a formal leaderboard run):
Use only the AgentCAD MCP tools. Build a native, editable part in part.FCStd
using apply_operations; scripts are disabled. Fetch the relevant operation
schemas first. Check dimensions and render previews to inspect your work.
Instead of writing answer.py, save your completed native file with
save_benchmark_stage(stage="final"). For a create-and-edit task, first build
the BASE, call save_benchmark_stage(stage="base"), then edit the SAME
part.FCStd to make the target, and finally save stage="final". Each stage can
be saved only once. The original /app denotes this isolated workspace.
Use the attached original engineering drawing when provided. Do not guess
dimensions that can be read from it. No reference geometry or grader feedback
is available. Work only on the task. You have %TIMEOUT% seconds total.
""".replace("%TIMEOUT%", str(args.timeout))
    (output / "prompt.txt").write_text(prompt, "utf-8")
    cmd = command(workspace, item, args, images)
    write_json(output / "command.json", cmd)
    env = {key: value for key, value in os.environ.items() if key not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    started = time.monotonic()
    print(json.dumps({"event": "started", **item}), flush=True)
    with (output / "trajectory.jsonl").open("wb") as stdout, (output / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   cwd=workspace, env=env, shell=False, start_new_session=os.name != "nt")
        try:
            process.communicate(prompt.encode("utf-8"), timeout=args.timeout)
            status = "done" if process.returncode == 0 else "agent_error"
        except subprocess.TimeoutExpired:
            from agentcad.backends.freecad import _kill_tree
            _kill_tree(process)
            status = "timeout"
    expected = ["answer_base.FCStd", "answer_edit.FCStd"] if item["kind"] == "edit" else ["answer.FCStd"]
    row = {**item, "status": status, "exit_code": process.returncode,
           "seconds": round(time.monotonic() - started, 2), "workspace": str(workspace),
           "outputs": {name: digest(workspace / name) for name in expected if (workspace / name).is_file()},
           **audit_log(output / "trajectory.jsonl")}
    write_json(output / "run.json", row)
    print(json.dumps({"event": "finished", "id": item["id"], "status": status,
                      "seconds": row["seconds"], "submitted": len(row["outputs"]) == len(expected),
                      "tool_calls": row["tool_calls"]}), flush=True)
    return row


def score_one(item: dict, args: argparse.Namespace) -> dict:
    task, workspace = args.dataset / item["id"], args.workspaces / item["id"]
    output = args.output / item["id"] / "score"
    output.mkdir(parents=True, exist_ok=False)
    row = json.loads((args.output / item["id"] / "run.json").read_text("utf-8"))
    expected = ["answer_base.FCStd", "answer_edit.FCStd"] if item["kind"] == "edit" else ["answer.FCStd"]
    missing = [name for name in expected if not (workspace / name).is_file()]
    if missing or row["unexpected_tools"]:
        result = {"score": 0.0, "status": "missing_output" if missing else "invalid_tools", "missing": missing}
    else:
        cmd = [str(args.scorer_python), str(task / "tests" / "run_scorer.py"),
               "--spec", str(task / "tests" / "grader" / "spec.json"),
               "--reward-txt", str(output / "reward.txt"), "--reward-json", str(output / "reward.json")]
        if item["kind"] == "edit":
            cmd += ["--reference-base", str(task / "tests" / "grader" / "reference_base.FCStd"),
                    "--reference-target", str(task / "tests" / "grader" / "reference_target.FCStd"),
                    "--candidate-base", str(workspace / "answer_base.FCStd"),
                    "--candidate-target", str(workspace / "answer_edit.FCStd")]
        else:
            cmd += ["--reference", str(task / "tests" / "grader" / "reference.FCStd"),
                    "--candidate", str(workspace / "answer.FCStd")]
        env = {**os.environ, "FREECAD_LIB": str(args.freecad / "bin"), "PYTHONUTF8": "1"}
        with (output / "scorer.log").open("wb") as stream:
            try:
                completed = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT, env=env,
                                           timeout=600, shell=False)
                if completed.returncode != 0:
                    raise RuntimeError(f"Scorer exited {completed.returncode}; see scorer.log")
                result = {"status": "scored", **json.loads((output / "reward_details.json").read_text("utf-8"))}
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                result = {"status": "scorer_error", "score": None, "error": str(exc)}
    row["evaluation"] = result
    write_json(args.output / item["id"] / "result.json", row)
    print(json.dumps({"id": item["id"], "kind": item["kind"], "evaluation": result}), flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "score"])
    parser.add_argument("--dataset", type=Path, required=True, help="Directory containing the 100 task directories")
    parser.add_argument("--output", type=Path, required=True, help="New run directory outside the agent workspace")
    parser.add_argument("--workspaces", type=Path, required=True)
    parser.add_argument("--freecad", type=Path, required=True)
    parser.add_argument("--scorer-python", type=Path)
    parser.add_argument("--per-group", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--effort", default="xhigh")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    args.dataset, args.output, args.workspaces, args.freecad = [
        p.resolve() for p in (args.dataset, args.output, args.workspaces, args.freecad)]
    if args.dataset.is_relative_to(args.workspaces) or args.output.is_relative_to(args.workspaces):
        parser.error("Dataset and logs must stay outside the agent workspaces")
    if args.action == "prepare":
        args.output.mkdir(parents=True, exist_ok=False)
        items = select_tasks(args.dataset, args.per_group, args.seed)
        manifest = {"benchmark": "gnucleus-ai/cad-bench@v3", "expected_dataset_digest": EXPECTED_DIGEST,
                    "digest_verified": False, "seed": args.seed, "selection": "stratified random, before any run",
                    "agentcad_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                    "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
                    "model": args.model, "effort": args.effort, "timeout_sec": args.timeout,
                    "jobs": args.jobs, "official_submission": False, "tasks": items}
        write_json(args.output / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    manifest = json.loads((args.output / "manifest.json").read_text("utf-8"))
    for key, value in {"model": args.model, "effort": args.effort, "timeout_sec": args.timeout,
                       "jobs": args.jobs}.items():
        if value != manifest[key]:
            parser.error(f"{key} differs from the frozen manifest")
    items = [item for item in manifest["tasks"] if not args.ids or item["id"] in args.ids]
    if args.action == "run":
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(run_one, item, args) for item in items]
            for future in as_completed(futures):
                future.result()
    else:
        if not args.scorer_python:
            parser.error("--scorer-python is required for scoring")
        rows = [score_one(item, args) for item in items]
        groups = {}
        for kind in GROUPS:
            scores = [row["evaluation"]["score"] for row in rows if row["kind"] == kind]
            groups[kind] = {"tasks": len(scores), "mean": statistics.mean(scores) if scores and None not in scores else None}
        write_json(args.output / "summary.json", {"manifest": manifest, "groups": groups, "results": rows})


if __name__ == "__main__":
    main()
