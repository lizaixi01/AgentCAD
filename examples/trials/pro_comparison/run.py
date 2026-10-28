"""Paired Codex trials: AgentCAD versus AutoCAD MCP Pro on the same DXF tasks.

Only DXF tasks authored by this repository are used; no Autodesk sample drawings.
Workspaces and raw logs live in a caller-specified directory outside the checkout.
Every round is a new Codex process. Each pair runs concurrently, one pair at a time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TRIALS = REPO / "examples" / "trials"
HARD = TRIALS / "hard"
sys.path.insert(0, str(HARD))
sys.path.insert(0, str(TRIALS))
from bases2 import make_h4_base, make_h5_base  # noqa: E402
from run_hard import make_h1_base  # noqa: E402

TASK_FILES = {"H4": "H4_cleanup.md", "H5": "H5_dimension.md"}
MAKERS = {"H1": make_h1_base, "H4": make_h4_base, "H5": make_h5_base}
MODEL = "gpt-6.1-sol"
EFFORT = "high"
SESSION_TIMEOUT_SECONDS = 900
PRO_SHA = "58a05ddfc34a9832c626e82cd88ecdce8e16a62a"
LOCK = threading.Lock()
TASKS = HARD / "tasks"
ORIENT = {
    "A": "该服务提供 list_operations，可先用它发现可用的图纸操作及参数。",
    "B": ("该服务提供 search_tools、describe_tool 和 call_tool；"
          "用 search_tools 按英文或 AutoCAD 命令搜索，按需查参数，再通过 call_tool 调用。"),
}
COMMON = (
    "你是负责此图纸的 CAD 工作人员。仅通过当前连接的 cad MCP 服务操作图纸；"
    "不要运行命令，不要使用其他插件或调用全局资源列表。"
    "图纸位于当前工作区，单位为毫米。请按要求操作，并将成果保存回 part.dxf。"
    "用服务可用的方式检查结果。无法完成的内容请如实报告，不要猜测。"
    "最后简要说明完成情况、问题和最终检查结果。\n\n"
)


def toml(value: object) -> str:
    return json.dumps(str(value).replace("\\", "/"), ensure_ascii=False)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def event(out: Path, payload: dict) -> None:
    record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **payload}
    with LOCK:
        with (out / "progress.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
        print(json.dumps(record, ensure_ascii=True), flush=True)


def version(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def build_cmd(arm: str, ws: Path, pro: Path) -> list[str]:
    if arm == "A":
        exe = REPO / ".venv" / "Scripts" / "python.exe"
        argv = '["-m","agentcad.mcp_server"]'
        env = "{AGENTCAD_ROOT=" + toml(ws) + ',AGENTCAD_READ_ONLY="0",AGENTCAD_ALLOWED_OPS="",AGENTCAD_ALLOW_SCRIPTS="0",PYTHONIOENCODING="utf-8"}'
    else:
        exe = pro / ".venv" / "Scripts" / "autocad-mcp.exe"
        argv = "[]"
        env = ('{AUTOCAD_MCP_BACKEND="ezdxf",ALLOWED_PATHS=' + toml(ws)
               + ',DISCOVERY_MODE="search",EZDXF_UNDO_DEPTH="5",TOOL_PROFILE="full",TOOL_PACKS="all",ENABLE_3D="false",PYTHONIOENCODING="utf-8"}')
    return [
        "codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
        "-m", MODEL, "-s", "read-only", "-C", str(ws), "--json",
        "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="' + EFFORT + '"',
        "-c", "mcp_servers.cad.command=" + toml(exe), "-c", "mcp_servers.cad.args=" + argv,
        "-c", "mcp_servers.cad.env=" + env, "-c", 'mcp_servers.cad.default_tools_approval_mode="approve"',
        "-c", "mcp_servers.cad.startup_timeout_sec=60", "-c", "mcp_servers.cad.tool_timeout_sec=300",
        "-",
    ]


def summarize(path: Path) -> dict:
    tokens = None
    final = None
    calls = 0
    errors = 0
    other_tools: set[str] = set()
    event_errors = []
    terminal_error = None
    finished = False
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "turn.completed":
            finished, tokens = True, e.get("usage")
        if e.get("type") == "error" and e.get("message"):
            terminal_error = str(e["message"])
            event_errors.append(terminal_error)
        elif e.get("type") == "turn.failed" and isinstance(e.get("error"), dict):
            terminal_error = str(e["error"].get("message", ""))
            event_errors.append(terminal_error)
        else:
            # An old reconnect followed by more activity does not explain a later failure.
            terminal_error = None
        item = e.get("item") or {}
        kind = item.get("type")
        forbidden = (kind in {"command_execution", "web_search", "file_change", "dynamic_tool_call"}
                     or (isinstance(kind, str) and kind.endswith("_tool_call")
                         and (kind != "mcp_tool_call" or item.get("server") != "cad")))
        if e.get("type") in {"item.started", "item.completed"} and forbidden:
            other_tools.add(item.get("id") or "event-" + str(index))
        if e.get("type") != "item.completed":
            continue
        if kind == "agent_message":
            final = item.get("text")
        if kind != "mcp_tool_call":
            continue
        if item.get("server") != "cad":
            continue
        calls += 1
        result = item.get("result") or {}
        body = result.get("structured_content")
        if not isinstance(body, dict):
            body = {}
            for part in result.get("content") or []:
                if part.get("type") == "text":
                    try:
                        body = json.loads(part.get("text", ""))
                    except (ValueError, TypeError):
                        pass
                    break
        if item.get("error") or item.get("status") == "failed" or (
            isinstance(body, dict) and (body.get("ok") is False or body.get("isError") is True)
        ):
            errors += 1
    return {"turn_completed": finished, "usage": tokens, "cad_calls": calls,
            "reported_tool_errors": errors, "other_tool_calls": len(other_tools), "final": final,
            "event_errors": event_errors, "terminal_error": terminal_error}


def round_status(round_result: dict) -> str:
    """Only recognized model-service evidence permits an interruption classification."""
    if round_result.get("other_tool_calls", 0):
        return "tool_policy_violation"
    if round_result.get("exit") == 0 and round_result.get("turn_completed") and not round_result.get("timeout"):
        return "completed"
    terminal_error = (round_result.get("terminal_error") or "").lower()
    if "selected model is at capacity" in terminal_error or "reconnecting... waiting for network" in terminal_error:
        return "model_service_interrupted"
    return "unclassified_failure"


def unit_status(rounds: list[dict], expected: int) -> str:
    statuses = [round_status(r) for r in rounds]
    for status in ("tool_policy_violation", "unclassified_failure", "model_service_interrupted"):
        if status in statuses:
            return status
    return "completed" if len(statuses) == expected else "unclassified_failure"


def pair_can_retry(rows: list[dict]) -> bool:
    """Retry only a whole pair affected solely by a confirmed model interruption."""
    return (len(rows) == 2 and {r["arm"] for r in rows} == {"A", "B"}
            and any(r["run_status"] == "model_service_interrupted" for r in rows)
            and all(r["run_status"] in {"completed", "model_service_interrupted"} for r in rows))


def mark_pair_eligibility(rows: list[dict]) -> None:
    groups: dict[tuple[str, int], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["task"], row["rep"]), []).append(row)
    for pair in groups.values():
        reason = "pair_model_service_interrupted" if pair_can_retry(pair) else (
            "incomplete_pair" if len(pair) != 2 or {r["arm"] for r in pair} != {"A", "B"} else None)
        if reason:
            for row in pair:
                row["eligible_for_rate"] = False
                row["counted_success"] = False
                row["exclusion_reason"] = reason


def h4_center_lines_preserved(fixture: Path, drawing: Path) -> bool:
    """Compare center-line endpoints against the red, nonzero lines in the H4 fixture."""
    import ezdxf

    def endpoints(line):
        start = tuple(round(float(v), 3) for v in line.dxf.start)
        end = tuple(round(float(v), 3) for v in line.dxf.end)
        return tuple(sorted((start, end)))

    original = ezdxf.readfile(fixture).modelspace().query("LINE")
    expected = Counter(endpoints(e) for e in original
                       if e.dxf.get("color", 256) == 1 and (e.dxf.end - e.dxf.start).magnitude > 1e-6)
    actual = ezdxf.readfile(drawing).modelspace().query("LINE")
    observed = Counter(endpoints(e) for e in actual if e.dxf.layer.upper() == "CENTER")
    return len(expected) == 10 and expected == observed


def prompt(task: str, round_no: int, arm: str) -> str:
    if task == "H1":
        context = (TASKS / "H1_context.md").read_text(encoding="utf-8").replace("%ROUND%", str(round_no))
        task_text = context + (TASKS / ("H1_round" + str(round_no) + ".md")).read_text(encoding="utf-8")
    else:
        task_text = (TASKS / TASK_FILES[task]).read_text(encoding="utf-8")
    return COMMON + ORIENT[arm] + "\n\n任务：\n" + task_text


def one_round(out: Path, pro: Path, task: str, rep: int, arm: str, ws: Path, n: int) -> dict:
    unit = out / "runs" / task / ("r" + str(rep)) / arm
    log = unit / ("round" + str(n) + ".jsonl")
    stderr = unit / ("round" + str(n) + ".stderr.log")
    event(out, {"event": "round_started", "task": task, "rep": rep, "arm": arm, "round": n})
    started = time.perf_counter()
    timed_out = False
    try:
        with log.open("wb") as stdout, stderr.open("wb") as err:
            p = subprocess.run(build_cmd(arm, ws, pro), input=prompt(task, n, arm).encode("utf-8"),
                               cwd=ws, stdout=stdout, stderr=err, shell=False, timeout=SESSION_TIMEOUT_SECONDS)
        exit_code = p.returncode
    except subprocess.TimeoutExpired:
        timed_out, exit_code = True, None
    elapsed = round(time.perf_counter() - started, 2)
    summary = summarize(log) if log.exists() else {"turn_completed": False}
    valid_file = (ws / "part.dxf").is_file()
    if valid_file:
        (unit / "snapshots").mkdir(exist_ok=True)
        shutil.copyfile(ws / "part.dxf", unit / "snapshots" / ("round" + str(n) + ".dxf"))
    result = {"round": n, "seconds": elapsed, "exit": exit_code, "timeout": timed_out,
              "drawing_present": valid_file, **summary}
    write_json(unit / ("round" + str(n) + ".json"), result)
    event(out, {"event": "round_finished", "task": task, "rep": rep, "arm": arm,
                "round": n, "seconds": elapsed, "exit": exit_code,
                "calls": summary.get("cad_calls"), "timeout": timed_out})
    return result


def run_unit(out: Path, pro: Path, task: str, rep: int, arm: str) -> dict:
    unit = out / "runs" / task / ("r" + str(rep)) / arm
    result_file = unit / "result.json"
    if result_file.is_file():
        return json.loads(result_file.read_text(encoding="utf-8"))
    if unit.exists():
        raise RuntimeError("Incomplete existing unit preserved; use a new output directory: " + str(unit))
    ws = unit / "workspace"
    ws.mkdir(parents=True)
    fixture = out / "fixtures" / (task + ".dxf")
    shutil.copyfile(fixture, ws / "part.dxf")
    if sha(fixture) != sha(ws / "part.dxf"):
        raise RuntimeError("Fixture copy hash mismatch")
    rounds = []
    for n in range(1, 6 if task == "H1" else 2):
        result = one_round(out, pro, task, rep, arm, ws, n)
        rounds.append(result)
        if round_status(result) != "completed":
            break
    result = {"task": task, "rep": rep, "arm": arm, "fixture_sha256": sha(fixture),
              "seconds": round(sum(x["seconds"] for x in rounds), 2), "rounds": rounds}
    write_json(result_file, result)
    return result


def record_unit_error(out: Path, task: str, rep: int, arm: str, exc: Exception) -> None:
    """Keep completed round evidence and represent a failed runner as a failed sample."""
    unit = out / "runs" / task / ("r" + str(rep)) / arm
    unit.mkdir(parents=True, exist_ok=True)
    result_file = unit / "result.json"
    if not result_file.exists():
        rounds = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(unit.glob("round[0-9]*.json"))]
        write_json(result_file, {"task": task, "rep": rep, "arm": arm,
                                 "seconds": round(sum(r.get("seconds", 0) for r in rounds), 2),
                                 "rounds": rounds, "unit_error": type(exc).__name__ + ": " + str(exc)})
    event(out, {"event": "unit_error", "task": task, "rep": rep, "arm": arm,
                "error": str(exc), "type": type(exc).__name__})


def prepare(out: Path, pro: Path, reps: int, tasks: list[str]) -> None:
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("Output directory is not empty; existing evidence is preserved: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    (out / "fixtures").mkdir()
    for task in tasks:
        MAKERS[task](out / "fixtures" / (task + ".dxf"))
    manifest = {
        "agentcad_commit": version(REPO), "pro_commit": version(pro), "model": MODEL,
        "reasoning_effort": EFFORT, "codex_cli": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "python": sys.version, "session_timeout_seconds": SESSION_TIMEOUT_SECONDS, "repetitions": reps, "tasks": tasks, "arms": {"A": "AgentCAD", "B": "AutoCAD MCP Pro"},
        "pro_config": {"backend": "ezdxf", "discovery_mode": "search", "undo_depth": 5, "allowed_paths": "workspace"},
        "agentcad_config": {"root": "workspace", "scripts": "disabled"},
        "execution": "Each pair concurrently; pairs run sequentially. Every H1 round starts a new Codex and MCP process.",
        "prompt_common": COMMON, "orientation": ORIENT,
        "fixtures": {task: sha(out / "fixtures" / (task + ".dxf")) for task in tasks},
    }
    if manifest["pro_commit"] != PRO_SHA:
        raise RuntimeError("Unexpected AutoCAD MCP Pro commit: " + manifest["pro_commit"])
    pro_python = pro / ".venv" / "Scripts" / "python.exe"
    check = "import importlib.util; print(int(bool(importlib.util.find_spec('PIL')) and bool(importlib.util.find_spec('matplotlib'))))"
    manifest["pro_config"]["png_renderer_available"] = subprocess.check_output(
        [str(pro_python), "-c", check], text=True, timeout=30
    ).strip() == "1"
    write_json(out / "manifest.json", manifest)


def grade(out: Path) -> list[dict]:
    (out / "tmp").mkdir(exist_ok=True)
    tempfile.tempdir = str(out / "tmp")
    from grade_hard import grade_h1  # imported after setting our own temporary directory
    from grade_hard2 import grade_h4, grade_h5
    from grade import check
    graders = {"H4": grade_h4, "H5": grade_h5}
    rows = []
    for file in sorted((out / "runs").glob("*/*/*/result.json")):
        r = json.loads(file.read_text(encoding="utf-8"))
        unit = file.parent
        if r["task"] == "H1":
            g = grade_h1(unit / "workspace", unit / "snapshots")
            ok = g["rounds_ok"] == 5
        else:
            g = graders[r["task"]](unit / "workspace")
            if r["task"] == "H4":
                try:
                    preserved = h4_center_lines_preserved(out / "fixtures" / "H4.dxf", unit / "workspace" / "part.dxf")
                except Exception:
                    preserved = False
                center_check = check(preserved, "centre-line endpoints preserved from fixture", "preserve")
                g["checks"].append(center_check)
                if not preserved:
                    g["fails"].append(center_check["check"])
                    g["ok"] = False
            ok = bool(g["ok"])
        rounds = []
        for v in r["rounds"]:
            log = unit / ("round" + str(v["round"]) + ".jsonl") if "round" in v else None
            rounds.append({**v, **summarize(log)} if log and log.is_file() else v)
        usage = [v.get("usage") or {} for v in rounds]
        status = unit_status(rounds, 5 if r["task"] == "H1" else 1)
        if r.get("unit_error") and status != "tool_policy_violation":
            status = "unclassified_failure"
        rows.append({"task": r["task"], "rep": r["rep"], "arm": r["arm"], "ok": ok,
                     "grade": g, "seconds": r["seconds"],
                     "calls": sum(v.get("cad_calls", 0) for v in rounds),
                     "reported_tool_errors": sum(v.get("reported_tool_errors", 0) for v in rounds),
                     "other_tool_calls": sum(v.get("other_tool_calls", 0) for v in rounds),
                     "input_tokens": sum(v.get("input_tokens", 0) for v in usage),
                     "cached_input_tokens": sum(v.get("cached_input_tokens", 0) for v in usage),
                     "output_tokens": sum(v.get("output_tokens", 0) for v in usage),
                     "rounds_attempted": len(rounds),
                     "rounds_completed": sum(round_status(v) == "completed" for v in rounds),
                     "round_statuses": [round_status(v) for v in rounds],
                     "run_status": status,
                     "eligible_for_rate": status in {"completed", "unclassified_failure"},
                     "counted_success": status == "completed" and ok})
    mark_pair_eligibility(rows)
    write_json(out / "grades.json", rows)
    return rows


def main() -> None:
    global SESSION_TIMEOUT_SECONDS
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pro", type=Path, required=True)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--tasks", nargs="+", choices=sorted(MAKERS), default=["H4", "H5", "H1"])
    p.add_argument("--grade-only", action="store_true")
    p.add_argument("--timeout-sec", type=int, default=900)
    args = p.parse_args()
    if args.reps < 1 or args.timeout_sec < 1:
        p.error("--reps and --timeout-sec must be positive")
    SESSION_TIMEOUT_SECONDS = args.timeout_sec
    out, pro = args.out.resolve(), args.pro.resolve()
    if args.grade_only:
        print(json.dumps(grade(out), ensure_ascii=True, indent=2))
        return
    prepare(out, pro, args.reps, args.tasks)
    incomplete = False
    for task in args.tasks:
        for rep in range(1, args.reps + 1):
            event(out, {"event": "pair_started", "task": task, "rep": rep})
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {arm: ex.submit(run_unit, out, pro, task, rep, arm) for arm in ("A", "B")}
                for arm, future in futures.items():
                    try:
                        future.result()
                    except Exception as exc:
                        record_unit_error(out, task, rep, arm, exc)
            rows = grade(out)
            pair = [r for r in rows if r["task"] == task and r["rep"] == rep]
            pair_complete = len(pair) == 2 and all(r["run_status"] == "completed" for r in pair)
            incomplete |= not pair_complete
            event(out, {"event": "pair_finished" if pair_complete else "pair_incomplete", "task": task, "rep": rep})
    event(out, {"event": "all_incomplete" if incomplete else "all_finished"})
    if incomplete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
