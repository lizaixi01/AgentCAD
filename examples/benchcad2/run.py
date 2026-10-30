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
THREAD_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def scorer_env() -> dict[str, str]:
    env = {**os.environ, **THREAD_ENV, "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt":
        env.setdefault("BENCHCAD_MESH_GUARD", "0")
    return env


def score_protocol(source: Path) -> dict:
    return {"benchcad_sha": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                                     text=True).strip(),
            "mesh_guard": scorer_env().get("BENCHCAD_MESH_GUARD", "1"), "threads": THREAD_ENV}


def validate_case_files(case: Path) -> None:
    manifest = json.loads((case / "case.json").read_text(encoding="utf-8"))
    for record in manifest["input"] + manifest["gt"]:
        p = (case / record["path"]).resolve()
        if not p.is_relative_to(case.resolve()) or p.is_symlink():
            raise ValueError(f"Invalid case path: {record['path']}")
        if hashlib.sha256(p.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Case hash mismatch: {p}. Check out BenchCAD with core.autocrlf=false")


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
           "AGENTCAD_ALLOW_SCRIPTS": "1", "PYTHONIOENCODING": "utf-8", **THREAD_ENV}
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
Time limit: {timeout} seconds. At most {calls} MCP calls. Finish by calling
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
    codes, by_name, started = {}, {}, set()
    submitted_after_calls = None
    if not path.exists():
        return {"tool_calls": 0, "tool_errors": 0, "unexpected_tools": [], "usage": None}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call":
            started.add(item.get("id"))
        if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
            calls += 1
            name = item.get("tool", "unknown")
            by_name[name] = by_name.get(name, 0) + 1
            result = item.get("result") or {}
            failed = item.get("status") == "failed" or item.get("error") is not None or result.get("isError", False)
            for content in result.get("content", []):
                if content.get("type") != "text":
                    continue
                try:
                    data = json.loads(content.get("text", ""))
                except ValueError:
                    continue
                if isinstance(data, dict) and data.get("ok") is False:
                    failed = True
                    code = (data.get("error") or {}).get("code", "unknown")
                    codes[code] = codes.get(code, 0) + 1
                if (isinstance(data, dict) and data.get("submitted") is True
                        and name == "submit_answer" and submitted_after_calls is None):
                    submitted_after_calls = len(started)
            errors += int(failed)
            if item.get("server") != "agentcad":
                unexpected.append(item.get("server"))
        elif event.get("type") == "item.completed" and item.get("type") in ("command_execution", "web_search"):
            unexpected.append(item["type"])
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
    return {"tool_calls": calls, "tool_errors": errors, "tool_error_codes": codes,
            "tool_calls_started": len(started), "tool_calls_by_name": by_name,
            "submitted_after_calls": submitted_after_calls,
            "unexpected_tools": unexpected, "usage": usage}


def episode_outcome(termination: str, exit_code: int, elapsed: float, submitted_at: float | None,
                    calls_started: int, timeout: int, call_limit: int) -> tuple[str, bool]:
    """Submission ends an episode, but never rescues an exceeded budget."""
    if calls_started > call_limit:
        return "tool_limit", False
    if submitted_at is not None:
        if submitted_at > timeout:
            return "timeout", False
        return "completed", True
    if termination != "completed":
        return termination, False
    if elapsed > timeout:
        return "timeout", False
    return ("agent_error" if exit_code else "completed"), False


def resume_record(previous: dict, retry_infra: bool) -> bool:
    """Return whether to skip this episode. Budgets exhausted are final results."""
    status = previous["status"]
    if status == "running":
        raise RuntimeError("An episode is still marked running; inspect it before resuming")
    return not (retry_infra and status in ("agent_error", "infrastructure_error"))


def run_one(case: Path, args) -> dict:
    key = f"{case.parents[1].name}_{case.name}"
    out = args.out / key
    record = out / "run.json"
    if args.resume and record.exists():
        previous = json.loads(record.read_text(encoding="utf-8"))
        if resume_record(previous, args.retry_infra):
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
                            capture_output=True, text=True, encoding="utf-8", timeout=300, env=scorer_env())
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
    dump(logs / "run.json", row)
    print(json.dumps({"case": key, "status": "started", "attempt": attempt}), flush=True)
    t0, wall_start = time.monotonic(), time.time()
    env = {**os.environ, **THREAD_ENV, "AGENTCAD_VIEWER": "0", "PYTHONIOENCODING": "utf-8"}
    with (logs / "events.jsonl").open("wb") as stdout, (logs / "stderr.log").open("wb") as stderr:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                cwd=workspace, env=env, start_new_session=os.name != "nt")
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        status = "completed"
        last_check = 0.
        while proc.poll() is None:
            elapsed = time.monotonic() - t0
            marker = workspace / "answer.json"
            # Give Codex a short grace period to finish its final message/usage
            # after explicit submission, then end the episode ourselves.
            if marker.exists() and time.time() - marker.stat().st_mtime > 30:
                stop_tree(proc)
                break
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
    marker = workspace / "answer.json"
    elapsed = time.monotonic() - t0
    submitted_at = marker.stat().st_mtime - wall_start if marker.is_file() else None
    used_calls = stats.get("submitted_after_calls") or stats.get("tool_calls_started", stats["tool_calls"])
    status, submitted = episode_outcome(status, proc.returncode, elapsed, submitted_at, used_calls,
                                        args.timeout, args.calls)
    row.update(status=status, exit_code=proc.returncode, seconds=round(time.monotonic() - t0, 1),
               submitted=submitted, **stats)
    dump(record, row)
    dump(logs / "run.json", row)
    print(json.dumps(row), flush=True)
    return row


def score_one(case: Path, args, *, oracle: bool = False) -> dict:
    key = f"{case.parents[1].name}_{case.name}"
    out = args.out / key
    protocol = score_protocol(args.bench_source)
    if not oracle and (out / "score.json").exists() and args.resume:
        previous = json.loads((out / "score.json").read_text(encoding="utf-8"))
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        if (previous.get("attempt") == run["attempt"] and previous.get("score") is not None
                and previous.get("scoring_protocol") == protocol):
            return previous
    cmd = [str(args.bench_python), str(HERE / "run.py"), "_score", "--bench-source",
           str(args.bench_source), "--case", str(case)]
    if oracle:
        cmd += ["--oracle"]
    else:
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        if not run["submitted"]:
            row = {"case": key, "attempt": run["attempt"], "score": 0., "status": "no_submission",
                   "scoring_protocol": protocol}
            dump(out / "score.json", row)
            return row
        workspace = Path(run["workspace"])
        marker = json.loads((workspace / "answer.json").read_text(encoding="utf-8"))
        submission = (workspace / marker["path"]).resolve()
        if not submission.is_relative_to(workspace.resolve()):
            raise ValueError("Submission marker escaped the workspace")
        cmd += ["--submission", str(submission)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=args.score_timeout, env=scorer_env())
        if p.returncode:
            raise RuntimeError(p.stderr[-5000:] or p.stdout[-5000:])
        row = {"case": key, **json.loads(p.stdout)}
    except (subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        row = {"case": key, "score": None, "status": "evaluator_error", "error": str(exc)}
    if not oracle:
        row["attempt"] = run["attempt"]
    row["scoring_protocol"] = protocol
    dump(out / ("oracle.json" if oracle else "score.json"), row)
    print(json.dumps({k: row.get(k) for k in ("case", "score", "status", "error")}), flush=True)
    return row


def summarize(root: Path) -> dict:
    by_task, records, protocols = {}, [], {}
    for p in sorted(root.glob("task*_case*/score.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        run_path = p.parent / "run.json"
        r = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
        if r.get("attempt") != s.get("attempt"):
            continue
        protocol = s.get("scoring_protocol")
        protocols[json.dumps(protocol, sort_keys=True)] = protocol
        records.append({"case": s["case"], "score": s.get("score"), "status": s.get("status"),
                        "seconds": r.get("seconds"), "tool_calls": r.get("tool_calls"),
                        "submitted": r.get("submitted"), "kind": r.get("kind"),
                        "scoring_protocol": protocol,
                        "attempts": [json.loads(a.read_text(encoding="utf-8")) for a in
                                     sorted(p.parent.glob("attempt-*/run.json"))]})
        by_task.setdefault(s["case"].split("_")[0], []).append(s.get("score"))
    tasks = {task: {"scored": sum(v is not None for v in values), "total": len(values),
                    "mean": sum(v for v in values if v is not None) / sum(v is not None for v in values)
                    if any(v is not None for v in values) else None} for task, values in by_task.items()}
    consistent = len(protocols) == 1 and None not in protocols.values()
    complete = (consistent and len(tasks) == 6 and len(records) == 9
                and all(t["scored"] == t["total"] for t in tasks.values()))
    result = {"model": MODEL, "effort": EFFORT, "dataset": "BenchCAD 2 nine development samples",
              "harness": "AgentCAD custom Codex MCP harness; not leaderboard-comparable",
              "complete": complete, "tasks": tasks, "records": records,
              "scoring_protocols": list(protocols.values()),
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
    ap.add_argument("--out", type=Path, default=Path(r"D:\Projects\AgentCAD-output\benchcad2-sol-max-20261030-dev9"))
    ap.add_argument("--cases", nargs="*", help="e.g. task3_case1 task6_case2")
    ap.add_argument("--jobs", type=int, help="default: 2 model episodes, 1 offline scorer")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--calls", type=int, default=100)
    ap.add_argument("--score-timeout", type=int, default=3600)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--retry-infra", action="store_true", help="explicitly retry infrastructure errors on resume")
    ap.add_argument("--case", type=Path)
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--submission", type=Path)
    ap.add_argument("--oracle", action="store_true")
    args = ap.parse_args()
    if args.mode.startswith("_"):
        internal(args)
        return
    args.out = args.out.resolve()
    args.jobs = args.jobs or (2 if args.mode == "run" else 1)
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
    for case in selected:
        validate_case_files(case)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.mode == "run":
        # A failed reference check is an evaluator failure, not a model score.
        protocol = score_protocol(args.bench_source)
        for case in [p.parent for p in cases]:
            oracle = args.out / f"{case.parents[1].name}_{case.name}" / "oracle.json"
            checked = json.loads(oracle.read_text(encoding="utf-8")) if oracle.exists() else {}
            if checked.get("score") != 1.0 or checked.get("scoring_protocol") != protocol:
                raise SystemExit("All nine standard answers must pass with the current scoring protocol first: run oracle")
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
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        jobs = {pool.submit(run_one if args.mode == "run" else score_one, case, args,
                            **({"oracle": True} if args.mode == "oracle" else {})): case for case in selected}
        for future in as_completed(jobs):
            results.append(future.result())
    if args.mode == "oracle":
        passed = all(r.get("score") == 1.0 for r in results)
        dump(args.out / "oracle_summary.json", {"passed": passed, "cases": results})
        if not passed:
            raise SystemExit("Standard-answer validation failed; do not interpret model scores")
    if args.mode == "score":
        print(json.dumps(summarize(args.out), indent=2))


if __name__ == "__main__":
    main()
