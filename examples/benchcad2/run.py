"""Run BenchCAD 2 development samples with Codex + AgentCAD, then score offline.

Uses the existing Codex ChatGPT login, no API keys. This is a custom agent
experiment, not BenchCAD's provider harness or a reportable Core run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MODEL = "gpt-6.1-sol"
EFFORT = "max"


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def staged_case(case: Path, workspace: Path, bench_source: Path) -> dict:
    """Use official input preprocessing, without constructing/executing a sandbox."""
    sys.path.insert(0, str(bench_source))
    from envs.common.sandbox import _rasterize_pdf, _point_bom_at_pngs, _add_bom_items
    from envs.common.episode import _seed_images, _task_brief, _listing

    if workspace.exists():
        raise FileExistsError(f"Refusing to replace an existing workspace: {workspace}")
    manifest = json.loads((case / "case.json").read_text(encoding="utf-8"))
    source = case / "input"
    if not source.is_dir() or any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Case must have a real input directory without symlinks")
    shutil.copytree(source, workspace)
    for pdf in sorted(workspace.rglob("*.pdf")):
        _rasterize_pdf(pdf)
        pdf.unlink()
    _point_bom_at_pngs(workspace / "bom.json")
    _add_bom_items(workspace / "bom.json", case / "case.json")
    return {"kind": manifest["kind"], "brief": _task_brief(case),
            "files": _listing(workspace),
            "images": [p.relative_to(workspace).as_posix() for p in _seed_images(workspace)]}


def command(workspace: Path, kind: str, images: list[str], output: Path) -> list[str]:
    env = {"AGENTCAD_ROOT": workspace.as_posix(), "AGENTCAD_VIEWER": "0",
           "AGENTCAD_ALLOW_SCRIPTS": "1", "PYTHONIOENCODING": "utf-8"}
    for key in ("AGENTCAD_FREECAD", "FREECAD_LIB"):
        if os.environ.get(key):
            env[key] = os.environ[key].replace("\\", "/")
    # A TOML inline table, using JSON string escaping for scalar string values.
    inline = "{" + ", ".join(f"{k}={json.dumps(v)}" for k, v in env.items()) + "}"
    cfg = {"model_reasoning_effort": json.dumps(EFFORT), "approval_policy": '"never"',
           "features.shell_tool": "false", "features.multi_agent": "false",
           "features.plugins": "false", "web_search": '"disabled"', "project_doc_max_bytes": "0",
           "mcp_servers.agentcad.command": json.dumps(sys.executable.replace("\\", "/")),
           "mcp_servers.agentcad.args": json.dumps([str(HERE / "task_tools.py").replace("\\", "/"),
                                                    workspace.as_posix(), kind]),
           "mcp_servers.agentcad.env": inline,
           "mcp_servers.agentcad.default_tools_approval_mode": '"approve"',
           "mcp_servers.agentcad.tool_timeout_sec": "300",
           "mcp_servers.agentcad.startup_timeout_sec": "60"}
    cmd = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
           "-s", "read-only", "--json", "--color", "never", "-C", str(workspace),
           "--model", MODEL, "--output-last-message", str(output)]
    for key, value in cfg.items():
        cmd += ["-c", f"{key}={value}"]
    for name in images:
        cmd += ["-i", str(workspace / name)]
    return cmd + ["-"]


def prompt(meta: dict, timeout: int, calls: int) -> str:
    return f"""Solve this BenchCAD development case using AgentCAD's MCP tools.
Time limit: {timeout} seconds. At most {calls} completed MCP calls. Finish by calling
submit_answer. A case without submit_answer has no answer and scores zero.

Official task brief (its Python/export interface is replaced below by MCP):
{meta['brief']}

Your workspace input files:
{chr(10).join(meta['files'])}

Interface:
- Use read_workspace to inspect text/JSON, view input PNGs or crop images.
- All NEW geometry must be built through AgentCAD: run_script('part.FCStd', code)
  runs CadQuery (cq imported; set result to a single solid), or use apply_operations.
  Each part file is one connected solid. Check the returned validation.
- Export new geometry with export_drawing(path, output, 'step'). For assemblies,
  export each modelled part to submission/parts/<part_id>.step. AgentCAD does not
  have a native assembly model: benchmark adapters handle supplied STEP inspection,
  previews and JSON placements. inspect_step describes and previews supplied STEPs.
- export_drawing can show previews of your parts. Reference comparison is available
  but only compares silhouettes, and the three approximate cameras are perturbed.
- preview_assembly takes proposed instances and shows an independent four-view image.
- When finished, submit_answer(path='submission.step') for a single part,
  submit_answer(instances=[...]) for an assembly, or submit_answer(graph={{...}})
  for a PCB. Assembly submission copies supplied parts unchanged from step_files/;
  every modelled part must already exist in submission/parts/. T6 is visual graph
  reasoning through a JSON adapter; AgentCAD has no schematic engine.
- The official instruction to leave Python result/export_part/use_part/submit_assembly
  is satisfied through these MCP calls. You have no Python shell or filesystem editor.
- Work only with staged inputs and your own generated files. Reference answers,
  scorer code and the benchmark source are unavailable and must not be sought.
- No score feedback is provided during this task. After submit_answer, stop.
"""


def stop_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                        "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
    else:
        import signal
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def log_stats(path: Path) -> dict:
    calls, errors, unexpected, usage = 0, 0, [], None
    if not path.exists():
        return {"tool_calls": 0, "tool_errors": 0, "unexpected_tools": [], "usage": None}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
            calls += 1
            errors += int(item.get("status") == "failed" or item.get("error") is not None
                          or (item.get("result") or {}).get("isError", False))
            if item.get("server") != "agentcad":
                unexpected.append(item.get("server"))
        elif event.get("type") == "item.completed" and item.get("type") in ("command_execution", "web_search"):
            unexpected.append(item["type"])
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
    return {"tool_calls": calls, "tool_errors": errors, "unexpected_tools": unexpected, "usage": usage}


def run_one(case: Path, args) -> dict:
    key = f"{case.parents[1].name}_{case.name}"
    out = args.out / key
    record = out / "run.json"
    if args.resume and record.exists():
        previous = json.loads(record.read_text(encoding="utf-8"))
        # Resume only completed model episodes. Failed workspaces are retained,
        # and a fresh attempt gets its own directory rather than erasing evidence.
        if previous["status"] == "completed":
            return previous
    out.mkdir(parents=True, exist_ok=True)
    attempt = 1
    while (out / f"attempt-{attempt}").exists():
        attempt += 1
    logs = out / f"attempt-{attempt}"
    logs.mkdir()
    workspace = args.out / "workspaces" / key / f"attempt-{attempt}"
    staged = subprocess.run([str(args.bench_python), str(HERE / "run.py"), "_stage", "--bench-source",
                             str(args.bench_source), "--case", str(case), "--workspace", str(workspace)],
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    if staged.returncode:
        raise RuntimeError(f"{key}: staging failed: {staged.stderr[-4000:]}")
    meta = json.loads(staged.stdout)
    text = prompt(meta, args.timeout, args.calls)
    (logs / "prompt.txt").write_text(text, encoding="utf-8")
    cmd = command(workspace, meta["kind"], meta["images"], logs / "final.txt")
    dump(logs / "command.json", cmd)
    row = {"case": key, "kind": meta["kind"], "model": MODEL, "effort": EFFORT,
           "attempt": attempt, "status": "running", "workspace": str(workspace),
           "logs": str(logs), "timeout_s": args.timeout, "tool_call_limit": args.calls}
    dump(record, row)
    print(json.dumps({"case": key, "status": "started", "attempt": attempt}), flush=True)
    t0 = time.monotonic()
    env = {**os.environ, "AGENTCAD_VIEWER": "0", "PYTHONIOENCODING": "utf-8"}
    with (logs / "events.jsonl").open("wb") as stdout, (logs / "stderr.log").open("wb") as stderr:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                cwd=workspace, env=env, start_new_session=os.name != "nt")
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        status = "completed"
        last_check = 0.
        while proc.poll() is None:
            elapsed = time.monotonic() - t0
            if elapsed > args.timeout:
                status = "timeout"
                stop_tree(proc)
                break
            if elapsed - last_check > 3:
                last_check = elapsed
                stats = log_stats(logs / "events.jsonl")
                if stats["tool_calls"] >= args.calls and not (workspace / "answer.json").exists():
                    status = "tool_limit"
                    stop_tree(proc)
                    break
            time.sleep(.2)
    stats = log_stats(logs / "events.jsonl")
    if status == "completed" and proc.returncode != 0:
        status = "agent_error"
    marker = workspace / "answer.json"
    # A failed/interrupted episode's files are not promoted to a submission.
    submitted = status == "completed" and marker.is_file()
    row.update(status=status, exit_code=proc.returncode, seconds=round(time.monotonic() - t0, 1),
               submitted=submitted, **stats)
    dump(record, row)
    print(json.dumps(row), flush=True)
    return row


def score_one(case: Path, args, *, oracle: bool = False) -> dict:
    key = f"{case.parents[1].name}_{case.name}"
    out = args.out / key
    if not oracle and (out / "score.json").exists() and args.resume:
        previous = json.loads((out / "score.json").read_text(encoding="utf-8"))
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        if previous.get("attempt") == run["attempt"] and previous.get("score") is not None:
            return previous
    cmd = [str(args.bench_python), str(HERE / "run.py"), "_score", "--bench-source",
           str(args.bench_source), "--case", str(case)]
    if oracle:
        cmd += ["--oracle"]
    else:
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        if not run["submitted"]:
            row = {"case": key, "attempt": run["attempt"], "score": 0., "status": "no_submission"}
            dump(out / "score.json", row)
            return row
        workspace = Path(run["workspace"])
        marker = json.loads((workspace / "answer.json").read_text(encoding="utf-8"))
        submission = (workspace / marker["path"]).resolve()
        if not submission.is_relative_to(workspace.resolve()):
            raise ValueError("Submission marker escaped the workspace")
        cmd += ["--submission", str(submission)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=args.score_timeout)
        if p.returncode:
            raise RuntimeError(p.stderr[-5000:] or p.stdout[-5000:])
        row = {"case": key, **json.loads(p.stdout)}
    except (subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        row = {"case": key, "score": None, "status": "evaluator_error", "error": str(exc)}
    if not oracle:
        row["attempt"] = run["attempt"]
    dump(out / ("oracle.json" if oracle else "score.json"), row)
    print(json.dumps({k: row.get(k) for k in ("case", "score", "status", "error")}), flush=True)
    return row


def summarize(root: Path) -> dict:
    by_task, records = {}, []
    for p in sorted(root.glob("task*_case*/score.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        run_path = p.parent / "run.json"
        r = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
        if r.get("attempt") != s.get("attempt"):
            continue
        records.append({"case": s["case"], "score": s.get("score"), "status": s.get("status"),
                        "seconds": r.get("seconds"), "tool_calls": r.get("tool_calls"),
                        "submitted": r.get("submitted"), "kind": r.get("kind")})
        by_task.setdefault(s["case"].split("_")[0], []).append(s.get("score"))
    tasks = {task: {"scored": sum(v is not None for v in values), "total": len(values),
                    "mean": sum(v for v in values if v is not None) / sum(v is not None for v in values)
                    if any(v is not None for v in values) else None} for task, values in by_task.items()}
    complete = len(tasks) == 6 and len(records) == 9 and all(t["scored"] == t["total"] for t in tasks.values())
    result = {"model": MODEL, "effort": EFFORT, "dataset": "BenchCAD 2 nine development samples",
              "harness": "AgentCAD custom Codex MCP harness; not leaderboard-comparable",
              "complete": complete, "tasks": tasks, "records": records,
              "mean_of_task_means": sum(t["mean"] for t in tasks.values()) / 6 if complete else None}
    dump(root / "summary.json", result)
    return result


def internal(args) -> None:
    sys.path.insert(0, str(args.bench_source))
    if args.mode == "_stage":
        print(json.dumps(staged_case(args.case, args.workspace, args.bench_source)))
        return
    from envs.common.score_case import score_case

    if args.oracle:
        meta = json.loads((args.case / "case.json").read_text(encoding="utf-8"))
        if meta["kind"] == "part":
            submission = args.case / "gt/gt.step"
        elif meta["kind"] == "assembly":
            # Official oracle builds the fixed submission layout; copy references
            # only here, in the scorer process, outside every model workspace.
            import tempfile
            from envs.common.caseformat import resolve_part

            with tempfile.TemporaryDirectory(prefix="benchcad2-oracle-") as temp:
                submission = Path(temp) / "submission"
                (submission / "parts").mkdir(parents=True)
                (submission / "assembly").mkdir()
                for part in meta["parts"]:
                    pid = part["part_id"]
                    shutil.copy2(resolve_part(args.case, pid), submission / "parts" / f"{pid}.step")
                shutil.copy2(args.case / "gt/instances.json", submission / "assembly/instances.json")
                print(json.dumps(score_case(args.case, submission)))
            return
        else:
            from envs.verifiers.ecad import position_mode, position_reference
            if position_mode(args.case):
                import tempfile
                with tempfile.TemporaryDirectory(prefix="benchcad2-oracle-") as temp:
                    submission = Path(temp) / "graph.json"
                    dump(submission, position_reference(args.case))
                    print(json.dumps(score_case(args.case, submission)))
                return
            submission = args.case / "gt/gt_graph.json"
    else:
        submission = args.submission
    print(json.dumps(score_case(args.case, submission)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["run", "score", "oracle", "summary", "_stage", "_score"])
    ap.add_argument("--bench-source", type=Path, default=Path(r"D:\Projects\bench-src\benchcad-2-main"))
    ap.add_argument("--bench-python", type=Path)
    ap.add_argument("--out", type=Path, default=Path(r"D:\Projects\AgentCAD-output\benchcad2-sol-max-20261030"))
    ap.add_argument("--cases", nargs="*", help="e.g. task3_case1 task6_case2")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--calls", type=int, default=100)
    ap.add_argument("--score-timeout", type=int, default=3600)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--case", type=Path)
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--submission", type=Path)
    ap.add_argument("--oracle", action="store_true")
    args = ap.parse_args()
    if args.mode.startswith("_"):
        internal(args)
        return
    args.out = args.out.resolve()
    args.bench_source = args.bench_source.resolve()
    args.bench_python = args.bench_python or args.bench_source / ".venv/Scripts/python.exe"
    if args.mode == "summary":
        print(json.dumps(summarize(args.out), indent=2))
        return
    cases = sorted((args.bench_source / "examples").glob("task*/cases/*/case.json"))
    selected = [p.parent for p in cases if not args.cases
                or f"{p.parents[2].name}_{p.parent.name}" in args.cases]
    if not selected or (args.cases and len(selected) != len(set(args.cases))):
        raise SystemExit("Requested case ids do not match the development samples")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.mode == "run":
        source_sha = subprocess.check_output(["git", "-C", str(args.bench_source), "rev-parse", "HEAD"], text=True).strip()
        metadata = {"model": MODEL, "effort": EFFORT, "benchcad_sha": source_sha,
                    "agentcad_sha": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
                    "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
                    "tool_adapter_sha256": hashlib.sha256((HERE / "task_tools.py").read_bytes()).hexdigest(),
                    "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "timeout_s": args.timeout, "tool_call_limit": args.calls, "jobs": args.jobs,
                    "official_round_or_token_budget": False, "set": "nine development samples",
                    "no_reference_files_staged": True, "cost": "not reported by Codex CLI"}
        old = args.out / "metadata.json"
        if old.exists():
            previous = json.loads(old.read_text(encoding="utf-8"))
            if previous != metadata:
                raise SystemExit("Run metadata changed; choose another --out to preserve this experiment")
        else:
            dump(old, metadata)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        jobs = {pool.submit(run_one if args.mode == "run" else score_one, case, args,
                            **({"oracle": True} if args.mode == "oracle" else {})): case for case in selected}
        for future in as_completed(jobs):
            future.result()
    if args.mode == "score":
        print(json.dumps(summarize(args.out), indent=2))


if __name__ == "__main__":
    main()
