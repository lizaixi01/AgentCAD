"""Controlled BenchCAD-native Python workflow using the existing Codex login.

Uses the same case staging, evaluator and hard episode budgets as the recorded
AgentCAD runs. The changed treatment is the Python workbench/tool workflow.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as shared  # noqa: E402
from native_tools import DockerExecutor, NativeSession, dump  # noqa: E402

MODEL, EFFORT = "gpt-6-astra", "max"
REFERENCE_SHA = "25835161de291daa4035e81a7e8ba501e1474a63"
BENCH_SHA = "70b7aaeb3a031851d058252e4ebe4ed30ca41f77"
CASE_IDS = shared.CASE_IDS
CONTROL_FIELDS = ("model", "effort", "benchcad_sha", "scoring_protocol", "codex_version",
                  "timeout_s", "tool_call_limit", "jobs")
SCORER_PROBE = r'''
import hashlib, importlib.metadata as m, json, os, pathlib, platform, sys
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576), b''): h.update(block)
    return h.hexdigest()
exe=pathlib.Path(sys.executable).resolve()
base=pathlib.Path(getattr(sys,'_base_executable',sys.executable)).resolve()
packages={}
for d in m.distributions():
    manifests={str(p):sha(pathlib.Path(d.locate_file(p))) for p in (d.files or [])
               if p.name in ('METADATA','RECORD') and p.parent.name.endswith('.dist-info')}
    packages[d.metadata['Name'].lower()]={'version':d.version,'manifests':manifests}
print(json.dumps({'executable':str(exe),'executable_sha256':sha(exe),
    'base_executable':str(base),'base_executable_sha256':sha(base),
    'prefix':str(pathlib.Path(sys.prefix).resolve()),'python':sys.version,
    'isolated':sys.flags.isolated,'utf8_mode':sys.flags.utf8_mode,
    'os':platform.system(),'machine':platform.machine(),'packages':packages,
    'environment':{k:v for k,v in os.environ.items() if
       (k.startswith('BENCHCAD_') or k in ('ECAD_PURE_PYTHON','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','PYTHONHASHSEED','PYTHONPATH'))
       and not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD','CREDENTIAL','AUTH'))}},sort_keys=True))
'''


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def source_sha(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def scorer_environment(python: Path) -> dict:
    return json.loads(subprocess.check_output([str(python), "-I", "-X", "utf8", "-c", SCORER_PROBE],
                                              text=True, encoding="utf-8", timeout=120,
                                              env=shared.scorer_env()))


def environment_digest(environment: dict) -> str:
    return hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_scorer(args, metadata: dict) -> str:
    expected = metadata["scorer_environment"]
    if Path(args.bench_python).resolve() != Path(expected["executable"]).resolve():
        raise ValueError("Scoring interpreter differs from the frozen environment")
    actual = scorer_environment(args.bench_python)
    digest = environment_digest(actual)
    if actual != expected or digest != metadata["scorer_environment_sha256"]:
        raise ValueError("Scoring interpreter or dependencies changed after preflight")
    return digest


def grading_errors(root: Path, metadata: dict) -> list[str]:
    errors = shared.protocol_errors(root, metadata["scoring_protocol"])
    digest = metadata["scorer_environment_sha256"]
    if environment_digest(metadata["scorer_environment"]) != digest:
        errors.append("Frozen scoring-environment fingerprint is invalid")
    for key in CASE_IDS:
        path = root / key / "oracle.json"
        oracle = read(path) if path.exists() else {}
        if oracle.get("grading_environment_sha256") != digest or not oracle.get("fresh_environment_check"):
            errors.append(f"{key}: oracle was not checked in this frozen grading environment")
    return errors


def reference_check(key: str, args, original: dict, protocol: dict, scoring: dict,
                    expected_seal: dict) -> dict:
    task, name = key.split("_")
    case = args.bench_source / "examples" / task / "cases" / name
    digest = verify_scorer(args, scoring)
    fresh = evaluate(case, args, oracle=True, log_prefix=args.out / key / "oracle-fresh")
    fresh.update(case=key, scoring_protocol=protocol, grading_environment_sha256=digest,
                 fresh_environment_check=True)
    dump(args.out / key / "oracle.json", fresh)
    if fresh["score"] != 1.0:
        raise ValueError(f"{key}: standard answer failed in the frozen scorer environment")
    folder = args.out / "reference-rescore" / key
    episode = original["episode"]
    sealed_hashes = {}
    if episode["submitted"]:
        workspace = Path(episode["workspace"])
        marker = read(workspace / "answer.json")
        answer = (workspace / marker["path"]).resolve()
        if answer.is_symlink() or not answer.is_relative_to((workspace / ".agentcad").resolve()):
            raise ValueError("Reference answer escaped its sealed runtime state")
        files = sorted(answer.rglob("*")) if answer.is_dir() else [answer]
        if any(p.is_symlink() for p in files):
            raise ValueError("Reference answer contains a link")
        sealed_hashes = {p.relative_to(workspace).as_posix(): sha(p) for p in files if p.is_file()}
        if sealed_hashes != expected_seal:
            raise ValueError(f"{key}: sealed reference differs from its published hash archive")
        verify_scorer(args, scoring)
        result = evaluate(case, args, submission=answer, log_prefix=folder / "evaluation")
        if any(sha(workspace / p) != h for p, h in sealed_hashes.items()):
            raise ValueError("Reference artifact changed during grading")
    else:
        result = {"score": 0.0, "status": "no_submission"}
    result.update(case=key, attempt=1, scoring_protocol=protocol,
                  grading_environment_sha256=digest,
                  historical_score=original["scoring"]["score"],
                  delta_from_historical=result["score"] - original["scoring"]["score"],
                  sealed_artifact_sha256=sealed_hashes)
    dump(folder / "score.json", result)
    print(json.dumps({"case": key, "fresh_oracle": fresh["score"],
                      "reference_rescore": result["score"], "historical_score": result["historical_score"]}), flush=True)
    return result


def evaluate(case: Path, args, *, submission: Path | None = None, oracle: bool = False,
             log_prefix: Path) -> dict:
    command = [str(args.bench_python), "-I", "-X", "utf8", str(HERE / "run.py"), "_score",
               "--bench-source", str(args.bench_source), "--case", str(case)]
    command += ["--oracle"] if oracle else ["--submission", str(submission)]
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    dump(log_prefix.with_suffix(".command.json"), {"command": command})
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                             timeout=args.timeout, env=shared.scorer_env())
    log_prefix.with_suffix(".stdout.log").write_text(process.stdout, encoding="utf-8")
    log_prefix.with_suffix(".stderr.log").write_text(process.stderr, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(process.stderr[-3000:] or process.stdout[-3000:])
    result = json.loads(process.stdout)
    value = result.get("score")
    if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Evaluator did not return a finite score in [0, 1]")
    return result


def canonical_source(args) -> None:
    if source_sha(args.bench_source) != BENCH_SHA:
        raise ValueError("Expected the same pinned BenchCAD v2.1 checkout")
    dirty = subprocess.check_output(["git", "-C", str(args.bench_source), "status", "--porcelain",
                                     "--untracked-files=no"], text=True).strip()
    if dirty:
        raise ValueError("BenchCAD source has tracked modifications")


def stage_worker(args) -> None:
    """Runs in the original scoring/staging interpreter, never in model code."""
    canonical_source(args)
    shared.validate_case_files(args.case)
    meta = shared.staged_case(args.case, args.workspace, args.bench_source)
    sys.path.insert(0, str(args.bench_source))
    from envs.common.sandbox import TOOLS_PY, SITECUSTOMIZE_PY
    from envs.common.episode import tools_help, _submit_what
    for name, value in (("tools.py", TOOLS_PY), ("sitecustomize.py", SITECUSTOMIZE_PY)):
        (args.workspace / name).write_bytes(value.encode("utf-8"))
    meta.update(tools_help=tools_help(args.case), submit_what=_submit_what(args.case),
                native_helpers_sha256={name: sha(args.workspace / name)
                                       for name in ("tools.py", "sitecustomize.py")})
    print(json.dumps(meta, ensure_ascii=False))


def stage(args, key: str, workspace: Path) -> dict:
    task, case = key.split("_")
    case_dir = args.bench_source / "examples" / task / "cases" / case
    process = subprocess.run([str(args.bench_python), "-I", "-X", "utf8", str(HERE / "native_run.py"), "_stage",
                              "--bench-source", str(args.bench_source), "--case", str(case_dir),
                              "--workspace", str(workspace)], capture_output=True, text=True,
                             encoding="utf-8", timeout=300, env=shared.scorer_env())
    if process.returncode:
        raise RuntimeError(f"Input staging failed for {key}: {process.stderr[-3000:]}")
    return json.loads(process.stdout)


def prompt(meta: dict, timeout: int, calls: int) -> str:
    return f"""Solve this BenchCAD development case using its native Python tools.
Time limit: {timeout} seconds. At most {calls} MCP calls. Each execute_python call
counts once, including inspections, crops, failed programs and the final submission.
A case without a successful explicit final submission has no answer and scores zero.

Official task brief:
{meta['brief']}

Your workspace input files:
{chr(10).join(meta['files'])}

Native tools.py interface (import tools inside your program):
{meta['tools_help']}

Execution interface:
- execute_python(code, submit=False) runs a fresh Python process in the directory.
  It runs on Linux at /work; use workspace-relative paths, not the Codex host's
  Windows paths. Files persist between calls, memory does not. Use Python to inspect files and
  supplied STEP geometry, crop images or construct geometry. This is the native
  Python workbench; AgentCAD is not installed or available in it.
- Python 3.11.16, CadQuery 2.8.0 / OCP 7.9.3.1.1, numpy, scipy, PIL, matplotlib,
  vtk, trimesh and ezdxf are available. No network. Each program has at most
  300 seconds, 2 GiB and one CPU. The whole case retains the limit above.
- Stdout and stderr are each limited to 10,000 bytes (first and last halves).
  Every new or modified top-level PNG is shown automatically with its filename,
  at most 2000 pixels per side. Subdirectory PNGs are not automatically shown.
- For the final answer call execute_python(code, submit=True) with
  {meta['submit_what'].strip()}
  The native harness appends tools.finish(globals()), executes the program once,
  seals a successful answer, and ends the episode even if that final program fails.
  An earlier intermediate STEP is never promoted after a failed final program.
- The native export, export_part, use_part, submit_assembly and crop functions
  are staged unchanged from BenchCAD. There is no supplied reference renderer.
- Work only with staged inputs and your own generated files. Reference answers,
  scorer code and benchmark source are unavailable and must not be sought.
- No score feedback is provided during the task. After final submission, stop.
"""


def command(workspace: Path, config: Path, images: list[str], final: Path) -> list[str]:
    env = {"PYTHONIOENCODING": "utf-8", **shared.THREAD_ENV}
    inline = "{" + ", ".join(f"{key}={json.dumps(value)}" for key, value in env.items()) + "}"
    settings = {"model_reasoning_effort": json.dumps(EFFORT), "approval_policy": '"never"',
                "features.shell_tool": "false", "features.multi_agent": "false",
                "features.plugins": "false", "web_search": '"disabled"', "project_doc_max_bytes": "0",
                "mcp_servers.benchcad.command": json.dumps(sys.executable.replace("\\", "/")),
                "mcp_servers.benchcad.args": json.dumps(["-I", str(HERE / "native_tools.py").replace("\\", "/"),
                                                         config.as_posix()]),
                "mcp_servers.benchcad.env": inline,
                "mcp_servers.benchcad.default_tools_approval_mode": '"approve"',
                "mcp_servers.benchcad.tool_timeout_sec": "300",
                "mcp_servers.benchcad.startup_timeout_sec": "60"}
    cmd = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
           "-s", "read-only", "--json", "--color", "never", "-C", str(workspace),
           "--model", MODEL, "--output-last-message", str(final)]
    for key, value in settings.items():
        cmd += ["-c", f"{key}={value}"]
    for name in images:
        cmd += ["-i", str(workspace / name)]
    return cmd + ["-"]


def log_stats(path: Path) -> dict:
    calls, errors, started, names, codes, unexpected = 0, 0, set(), {}, {}, []
    usage, submitted_after = None, None
    if path.exists():
        for line in path.open(encoding="utf-8", errors="replace"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item") or {}
            if item.get("type") == "mcp_tool_call":
                started.add(item.get("id"))
            if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                calls += 1
                name = item.get("tool", "unknown")
                names[name] = names.get(name, 0) + 1
                result = item.get("result") or {}
                failed = item.get("status") == "failed" or item.get("error") is not None or result.get("isError", False)
                for content in result.get("content", []):
                    if content.get("type") != "text":
                        continue
                    try:
                        value = json.loads(content.get("text", ""))
                    except ValueError:
                        continue
                    if isinstance(value, dict) and value.get("ok") is False:
                        failed = True
                        code = (value.get("error") or {}).get("code", "unknown")
                        codes[code] = codes.get(code, 0) + 1
                    if isinstance(value, dict) and value.get("submitted") is True and submitted_after is None:
                        submitted_after = len(started)
                errors += int(failed)
                if item.get("server") != "benchcad" or name != "execute_python":
                    unexpected.append(f"{item.get('server')}/{name}")
            elif event.get("type") == "item.completed" and item.get("type") in ("command_execution", "web_search", "file_change"):
                unexpected.append(item["type"])
            if event.get("type") == "turn.completed":
                usage = event.get("usage")
    return {"tool_calls": calls, "tool_errors": errors, "tool_error_codes": codes,
            "tool_calls_started": len(started), "tool_calls_by_name": names,
            "submitted_after_calls": submitted_after, "unexpected_tools": unexpected, "usage": usage}


class CallProgress:
    """Count unique tool starts once; never repeatedly decode old image payloads."""
    def __init__(self):
        self.position = 0
        self.started: set[str] = set()

    def poll(self, path: Path) -> int:
        if not path.exists():
            return len(self.started)
        with path.open("rb") as stream:
            stream.seek(self.position)
            while True:
                line = stream.readline()
                if not line or not line.endswith(b"\n"):
                    break
                self.position = stream.tell()
                try:
                    item = json.loads(line).get("item") or {}
                except (ValueError, UnicodeDecodeError):
                    continue
                if item.get("type") == "mcp_tool_call":
                    self.started.add(item.get("id"))
        return len(self.started)


def cleanup(workspace: Path, context: str) -> None:
    identifier = hashlib.sha256(str(workspace).encode()).hexdigest()[:16]
    process = subprocess.run(["docker", "--context", context, "ps", "-aq", "--filter",
                              f"label=benchcad.native.workspace={identifier}"],
                             capture_output=True, text=True, timeout=30)
    if process.returncode:
        return
    ids = process.stdout.split()
    if ids:
        subprocess.run(["docker", "--context", context, "rm", "-f", *ids], capture_output=True, timeout=30)


def run_one(key: str, args) -> dict:
    folder = args.out / key
    record = folder / "run.json"
    if record.exists():
        previous = read(record)
        if previous["status"] == "running":
            raise RuntimeError("Inspect the running episode before resuming")
        if args.resume:
            return previous
        raise FileExistsError("A first attempt already exists; never replace it")
    if subprocess.check_output(["codex", "--version"], text=True).strip() != read(args.out / "metadata.json")["codex_version"]:
        raise ValueError("Codex changed before this episode started")
    verify_scorer(args, read(args.out / "metadata.json"))
    logs = folder / "attempt-1"
    logs.mkdir(parents=True, exist_ok=False)
    workspace = args.out / "workspaces" / key / "attempt-1"
    meta = stage(args, key, workspace)
    expected = next(c for c in read(args.out / "protocol.json")["cases"] if c["case"] == key)
    for name, digest in expected["input_sha256"].items():
        if sha(workspace / name) != digest:
            raise ValueError(f"Formal staged input mismatch: {key}/{name}")
    for name, digest in expected["native_helpers_sha256"].items():
        if sha(workspace / name) != digest:
            raise ValueError("Native tools changed after preflight")
    text = prompt(meta, args.timeout, args.calls)
    if hashlib.sha256(text.encode()).hexdigest() != expected["prompt_sha256"]:
        raise ValueError("Native prompt changed after preflight")
    (logs / "prompt.txt").write_text(text, encoding="utf-8")
    cmd = command(workspace, logs / "session.json", meta["images"], logs / "final.txt")
    dump(logs / "command.json", {"command": cmd})
    wall_start, started = time.time(), time.monotonic()
    protocol = read(args.out / "protocol.json")
    dump(logs / "session.json", {"workspace": str(workspace), "deadline": wall_start + args.timeout,
                                "calls": args.calls, "exec_timeout": 300,
                                "image": protocol["image_id"], "docker_context": args.docker_context,
                                "experiment": args.out.name})
    row = {"case": key, "kind": meta["kind"], "model": MODEL, "effort": EFFORT,
           "attempt": 1, "status": "running", "workspace": str(workspace), "logs": str(logs),
           "timeout_s": args.timeout, "tool_call_limit": args.calls}
    dump(record, row)
    print(json.dumps({"case": key, "status": "started", "attempt": 1}), flush=True)
    termination = "completed"
    progress = CallProgress()
    with (logs / "events.jsonl").open("w", encoding="utf-8") as events, (logs / "stderr.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=events, stderr=errors,
                                   text=True, encoding="utf-8", env=shared.scorer_env())
        process.stdin.write(text)
        process.stdin.close()
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                calls_started = progress.poll(logs / "events.jsonl")
                marker = logs / "answer.json"
                if marker.exists() and time.time() - marker.stat().st_mtime > 30:
                    shared.stop_tree(process)
                    break
                if elapsed >= args.timeout:
                    termination = "timeout"
                    shared.stop_tree(process)
                    break
                if calls_started > args.calls:
                    termination = "tool_limit"
                    shared.stop_tree(process)
                    break
                time.sleep(0.5)
        finally:
            if process.poll() is None:
                shared.stop_tree(process)
            cleanup(workspace, args.docker_context)
    elapsed = time.monotonic() - started
    stats = log_stats(logs / "events.jsonl")
    marker = read(logs / "answer.json") if (logs / "answer.json").exists() else None
    used = stats["submitted_after_calls"] or stats["tool_calls_started"]
    submitted_at = marker["timestamp"] - wall_start if marker and marker.get("submitted") else None
    status, submitted = shared.episode_outcome(termination, process.returncode, elapsed,
                                                submitted_at, used, args.timeout, args.calls)
    if marker and not marker.get("submitted") and status not in ("timeout", "tool_limit"):
        status = marker["status"]
    row.update(status=status, exit_code=process.returncode, seconds=round(elapsed, 1),
               submitted=submitted, final_program_attempted=bool(marker), **stats)
    row["input_mutations"] = [name for name, digest in expected["input_sha256"].items()
                              if (workspace / name).is_symlink() or not (workspace / name).is_file()
                              or not (workspace / name).resolve().is_relative_to(workspace.resolve())
                              or sha(workspace / name) != digest]
    dump(logs / "run.json", row)
    dump(record, row)
    print(json.dumps(row), flush=True)
    return row


def score_one(key: str, args) -> dict:
    folder = args.out / key
    row = read(folder / "run.json")
    metadata = read(args.out / "metadata.json")
    digest = verify_scorer(args, metadata)
    protocol = metadata["scoring_protocol"]
    errors = grading_errors(args.out, metadata)
    if errors:
        raise ValueError("; ".join(errors))
    if row["status"] == "running":
        raise RuntimeError("Cannot score an active episode")
    if args.resume and (folder / "score.json").exists():
        previous = read(folder / "score.json")
        if (previous.get("score") is not None and previous.get("attempt") == row["attempt"]
                and previous.get("scoring_protocol") == protocol
                and previous.get("grading_environment_sha256") == digest):
            return previous
        backup = folder / f"score-previous-{sha(folder / 'score.json')[:12]}.json"
        if not backup.exists():
            shutil.copy2(folder / "score.json", backup)
    if not row["submitted"]:
        result = {"case": key, "attempt": 1, "score": 0.0, "status": "no_submission",
                  "episode_status": row["status"], "scoring_protocol": protocol}
    else:
        logs = Path(row["logs"])
        marker = read(logs / "answer.json")
        answer = (logs / marker["path"]).resolve()
        if not marker.get("submitted") or not answer.is_relative_to((logs / "sealed").resolve()):
            raise ValueError("Invalid sealed answer marker")
        task, name = key.split("_")
        case = args.bench_source / "examples" / task / "cases" / name
        try:
            result = evaluate(case, args, submission=answer, log_prefix=folder / "offline-score")
        except (subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
            result = {"case": key, "score": None, "status": "evaluator_error", "error": str(exc)}
        result.update(case=key, attempt=1, scoring_protocol=protocol)
    result["grading_environment_sha256"] = digest
    dump(folder / "score.json", result)
    print(json.dumps({"case": key, "score": result["score"], "status": result.get("status")}), flush=True)
    return result


def summarize(root: Path) -> dict:
    metadata = read(root / "metadata.json")
    records, means = [], {}
    errors = grading_errors(root, metadata)
    for key in CASE_IDS:
        folder = root / key
        row = read(folder / "run.json") if (folder / "run.json").exists() else {}
        score = read(folder / "score.json") if (folder / "score.json").exists() else {}
        if score and (score.get("scoring_protocol") != metadata["scoring_protocol"]
                      or score.get("attempt") != row.get("attempt")
                      or score.get("grading_environment_sha256") != metadata["scorer_environment_sha256"]):
            errors.append(f"{key}: score/run protocol mismatch")
        value = score.get("score")
        if value is not None and (not isinstance(value, (float, int))
                                  or not math.isfinite(value) or not 0 <= value <= 1):
            errors.append(f"{key}: invalid score {value!r}")
            score = {**score, "score": None, "invalid_score": repr(value)}
        records.append({"case": key, "run": row, "score": score.get("score"), "scoring": score})
    for task in range(1, 7):
        values = [r["score"] for r in records if r["case"].startswith(f"task{task}_")]
        numeric = [v for v in values if isinstance(v, (float, int)) and math.isfinite(v) and 0 <= v <= 1]
        means[f"task{task}"] = {"total": len(values), "scored": len(numeric),
                                 "mean": sum(numeric) / len(values) if len(numeric) == len(values) else None}
    complete = not errors and all(t["mean"] is not None for t in means.values())
    result = {"model": MODEL, "effort": EFFORT, "complete": complete,
              "tasks": means, "records": records, "provenance_errors": errors,
              "mean_of_task_means": sum(t["mean"] for t in means.values()) / 6 if complete else None}
    dump(root / "summary.json", result)
    return result


def prepare(args) -> dict:
    if (args.out / "protocol.json").exists():
        raise FileExistsError("Never overwrite a frozen experiment protocol")
    canonical_source(args)
    repository = HERE.parents[1]
    for name in ("native_run.py", "native_tools.py", "native_runtime/Dockerfile", "native_runtime/requirements.txt"):
        subprocess.run(["git", "-C", str(repository), "ls-files", "--error-unmatch",
                        str((HERE / name).relative_to(repository))], capture_output=True, check=True)
    if subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain"], text=True).strip():
        raise ValueError("Commit the verified harness before freezing a model experiment")
    baseline = read(args.reference / "metadata.json")
    archive = read(args.reference / "results-astra-first-attempts-2026-10-30.json")
    assert archive["protocol"] == baseline and baseline["agentcad_sha"] == REFERENCE_SHA
    assert baseline["model"] == MODEL and baseline["effort"] == EFFORT
    assert baseline["timeout_s"] == args.timeout == 3600
    assert baseline["tool_call_limit"] == args.calls == 100 and baseline["jobs"] == args.jobs == 2
    cli = subprocess.check_output(["codex", "--version"], text=True).strip()
    if cli != baseline["codex_version"]:
        raise ValueError("Codex version differs from the AgentCAD reference")
    protocol = shared.score_protocol(args.bench_source)
    if protocol != baseline["scoring_protocol"]:
        raise ValueError("Scoring protocol differs from the reference")
    scoring = {"scorer_environment": scorer_environment(args.bench_python)}
    scoring["scorer_environment_sha256"] = environment_digest(scoring["scorer_environment"])
    image = json.loads(subprocess.check_output(["docker", "--context", args.docker_context,
                                                "image", "inspect", args.image], text=True))[0]
    image_id = image["Id"]
    code = ("import importlib.metadata as m,importlib.util,json,platform; "
            "print(json.dumps({'python':platform.python_version(),'os':platform.system(),'machine':platform.machine(),'agentcad_available':"
            "importlib.util.find_spec('agentcad') is not None,'packages':"
            "{d.metadata['Name']:d.version for d in m.distributions()}}))")
    environment = json.loads(subprocess.check_output(["docker", "--context", args.docker_context,
                              "run", "--rm", "--network", "none", image_id, "python", "-c", code],
                             text=True, timeout=120))
    if environment["python"] != "3.11.16" or environment["agentcad_available"]:
        raise ValueError("Unexpected native image interpreter or AgentCAD installation")
    reference_environment = read(args.reference / "comparison_protocol.json")
    for package in ("cadquery", "cadquery-ocp", "numpy", "scipy", "pillow", "vtk", "matplotlib", "ezdxf"):
        if environment["packages"][package] != reference_environment["packages"][package]:
            raise ValueError(f"Native package differs from AgentCAD interpreter: {package}")
    cases, matched_reference = [], []
    published = read(args.reference / "comparison-astra-sol-2026-10-30.json")
    for key in CASE_IDS:
        workspace = args.out / "preflight" / key
        meta = stage(args, key, workspace)
        reference = next(r for r in archive["records"] if r["case"] == key)
        original = Path(reference["episode"]["workspace"])
        files = {p.relative_to(workspace).as_posix(): sha(p) for p in sorted(workspace.rglob("*"))
                 if p.is_file() and p.name not in ("tools.py", "sitecustomize.py")}
        for name, digest in files.items():
            if sha(original / name) != digest:
                raise ValueError(f"Native input differs: {key}/{name}")
        old_prompt = (Path(reference["episode"]["logs"]) / "prompt.txt").read_text(encoding="utf-8")
        if meta["brief"] not in old_prompt:
            raise ValueError("Official task brief differs from the AgentCAD prompt")
        frozen = next(c for c in reference_environment["cases"] if c["case"] == key)
        if files != frozen["staged_input_sha256"] or meta["images"] != frozen["seed_images"]:
            raise ValueError("Input set or initial image order differs")
        text = prompt(meta, args.timeout, args.calls)
        cases.append({"case": key, "kind": meta["kind"], "input_sha256": files,
                      "native_helpers_sha256": meta["native_helpers_sha256"], "seed_images": meta["images"],
                      "brief_sha256": hashlib.sha256(meta["brief"].encode()).hexdigest(),
                      "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "staged_inputs_identical": True, "official_brief_identical": True,
                      "initial_image_order_identical": True})
        destination = args.out / key / "oracle-reference.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        oracle = read(args.reference / key / "oracle.json")
        if oracle["score"] != 1.0 or oracle["scoring_protocol"] != protocol:
            raise ValueError("Reference oracle has not passed with this scoring protocol")
        shutil.copy2(args.reference / key / "oracle.json", destination)
        print(json.dumps({"case": key, "preflight": "pass", "input_files": len(files)}), flush=True)
        bank = next(r for r in published["paired_cases"] if r["case"] == key)["astra_latest_sealed_submission_sha256"]
        matched_reference.append(reference_check(key, args, reference, protocol, scoring, bank))
    verify_scorer(args, scoring)
    reference_tasks = {f"task{task}": sum(r["score"] for r in matched_reference if r["case"].startswith(f"task{task}_")) /
                        sum(r["case"].startswith(f"task{task}_") for r in matched_reference) for task in range(1, 7)}
    dump(args.out / "reference-rescored.json", {"records": matched_reference, "task_means": reference_tasks,
                                               "mean_of_task_means": sum(reference_tasks.values()) / 6,
                                               "grading_environment_sha256": scoring["scorer_environment_sha256"]})
    metadata = {"model": MODEL, "effort": EFFORT, "benchcad_sha": BENCH_SHA,
                "scoring_protocol": protocol, "codex_version": cli, "timeout_s": args.timeout,
                "tool_call_limit": args.calls, "jobs": args.jobs,
                "set": "nine development samples", "leaderboard_comparable": False,
                "workflow": "BenchCAD native Python tools through Codex MCP transport",
                "harness_repo_sha": source_sha(HERE.parents[1]), "native_tools_sha256": sha(HERE / "native_tools.py"),
                "native_runner_sha256": sha(Path(__file__)), "shared_runner_sha256": sha(HERE / "run.py"),
                "image_id": image_id, "docker_context": args.docker_context,
                **scoring,
                "reference_rescored_sha256": sha(args.out / "reference-rescored.json"),
                "native_environment": environment, "reference_metadata": baseline,
                "no_reference_files_staged": True, "cost": "not reported by Codex CLI"}
    for key in CONTROL_FIELDS:
        if metadata[key] != baseline[key]:
            raise ValueError(f"Experimental control changed: {key}")
    dump(args.out / "metadata.json", metadata)
    frozen = {"reference_directory": str(args.reference), "reference_archive_sha256": sha(args.reference / "results-astra-first-attempts-2026-10-30.json"),
              "control_fields": list(CONTROL_FIELDS), "cases": cases, "image_id": image_id,
              "grading_environment_sha256": scoring["scorer_environment_sha256"],
              "reference_comparison": "Original sealed first-attempt AgentCAD answers rescored with the frozen native-control grader; historical results preserved",
              "primary": "Mean of six task means, nine original first attempts per workflow; no-submission zero",
              "secondary": "Mean of T1-T5 task means; T6 is model-only and the reference had an unresolved connection failure",
              "difference_direction": "AgentCAD minus native; positive values favor AgentCAD",
              "descriptive_subgroups": {"part_geometry": ["task1", "task3"],
                                         "assembly_workflows": ["task2", "task4", "task5"]},
              "retries": "Internal Codex stream retries consume wall time; no extra whole-case attempts in the primary comparison",
              "changed_treatment": ["native Python workbench and tools instead of AgentCAD MCP tools",
                                    "tool-specific interface instructions and one Python program per tool call",
                                    "Linux Docker runtime, official 2 GiB/one-CPU isolation; aligned Python/CadQuery versions",
                                    "native first-final-program failure ends the episode; no fallback"],
              "interpretation": "Controlled comparison of complete tool workflows, not a causal estimate for one CAD-kernel component or a Core leaderboard score",
              "scoring_checks": "Nine fresh 1.0 oracle checks plus regrading of all original AgentCAD first-attempt submissions outside model workspaces"}
    dump(args.out / "protocol.json", frozen)
    return metadata


def validate_frozen(args) -> None:
    canonical_source(args)
    metadata = read(args.out / "metadata.json")
    verify_scorer(args, metadata)
    errors = grading_errors(args.out, metadata)
    if errors:
        raise ValueError("; ".join(errors))
    if sha(args.out / "reference-rescored.json") != metadata["reference_rescored_sha256"]:
        raise ValueError("Matched reference scores changed after preflight")
    for name, key in (("native_tools.py", "native_tools_sha256"), ("native_run.py", "native_runner_sha256"),
                      ("run.py", "shared_runner_sha256")):
        if sha(HERE / name) != metadata[key]:
            raise ValueError("Experiment source changed after preflight")
    if source_sha(HERE.parents[1]) != metadata["harness_repo_sha"]:
        raise ValueError("Experiment checkout changed after preflight")
    if (MODEL, EFFORT, args.timeout, args.calls, args.jobs) != (metadata["model"], metadata["effort"],
                                                            metadata["timeout_s"], metadata["tool_call_limit"], metadata["jobs"]):
        raise ValueError("Experiment settings changed after preflight")
    if shared.score_protocol(args.bench_source) != metadata["scoring_protocol"]:
        raise ValueError("Scorer changed after preflight")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "score", "summary", "_stage"))
    parser.add_argument("--bench-source", type=Path, required=True)
    parser.add_argument("--bench-python", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--image", default="agentcad-benchcad-native:20261031")
    parser.add_argument("--docker-context", default="desktop-linux")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--calls", type=int, default=100)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    for name in ("bench_source", "bench_python", "reference", "out", "case", "workspace"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if args.mode == "_stage":
        stage_worker(args)
        return
    if not args.out:
        parser.error("--out is required")
    if args.mode == "prepare":
        if not args.bench_python or not args.reference:
            parser.error("prepare requires --bench-python and --reference")
        prepare(args)
        return
    if args.bench_python is None:
        args.bench_python = Path(read(args.out / "metadata.json")["scorer_environment"]["executable"])
    validate_frozen(args)
    if args.mode == "summary":
        result = summarize(args.out)
        print(json.dumps({k: result[k] for k in ("complete", "mean_of_task_means", "tasks")}))
        return
    keys = args.cases or CASE_IDS
    if not set(keys).issubset(CASE_IDS):
        parser.error("Only the original nine example cases are allowed")
    worker = run_one if args.mode == "run" else score_one
    with ThreadPoolExecutor(max_workers=args.jobs if args.mode == "run" else 1) as pool:
        futures = [pool.submit(worker, key, args) for key in keys]
        for future in as_completed(futures):
            future.result()
    summarize(args.out)


if __name__ == "__main__":
    main()
