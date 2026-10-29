"""Optional FreeCAD backend: the geometry kernel for 3D parts (``.FCStd``). The 2D runtime never needs it.

Every job runs ``part/_fc_runner.py`` in a separate FreeCAD process. The job folder holds ``job.json`` (action,
files and operations as data) and receives ``result.json``. Nothing the caller sends becomes a command line: the
arguments are the interpreter, the fixed runner path and the job folder. The only code a caller sends is a FreeCAD
Part script for run_script, which the policy keeps off unless scripts are allowed.

Configuration: AGENTCAD_FREECAD = FreeCAD's install folder, its ``bin`` folder, its bundled ``python`` or
``freecadcmd``. Otherwise FREECAD_LIB (the folder holding FreeCAD.pyd/.so, as freecad-validator uses it, imported by
this interpreter), then the usual install locations and ``freecadcmd`` on PATH. FreeCAD 1.1 is the tested release
(CADBench V3 scores with FreeCAD 1.1.0).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess  # starts FreeCAD only (see tests/test_security.py)
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ..errors import AgentCADError

RUNNER = Path(__file__).resolve().parent.parent / "part" / "_fc_runner.py"
TIMEOUT = float(os.environ.get("AGENTCAD_FREECAD_TIMEOUT", "300"))
_EXE = ".exe" if os.name == "nt" else ""


def _from_dir(d: Path) -> tuple[list[str], dict[str, str]] | None:
    for sub in ("", "bin", "Contents/Resources/bin", "usr/bin"):
        b = d / sub if sub else d
        py = b / f"python{_EXE}"
        if py.is_file() and any((b / n).is_file() for n in ("FreeCAD.pyd", "FreeCAD.so")):
            return [str(py), "-I"], {}
        for name in ("freecadcmd", "FreeCADCmd"):
            if (b / f"{name}{_EXE}").is_file():
                return [str(b / f"{name}{_EXE}")], {}
    return None


def find_freecad() -> tuple[list[str], dict[str, str]] | None:
    """(command prefix, extra environment) that runs the runner script under FreeCAD, or None."""
    env = os.environ.get("AGENTCAD_FREECAD")
    if env:
        p = Path(env)
        if p.is_dir():
            return _from_dir(p)
        if p.is_file():
            return ([str(p), "-I"] if p.stem.lower().startswith("python") else [str(p)]), {}
        return None
    lib = os.environ.get("FREECAD_LIB")
    if lib:
        for d in lib.split(os.pathsep):
            hit = _from_dir(Path(d))
            if hit:
                return hit
        return [sys.executable, "-I"], {"AGENTCAD_FREECAD_LIB": lib}
    pats = [r"C:\Program Files\FreeCAD *", os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeCAD *"),
            "/Applications/FreeCAD.app", "/usr/lib/freecad", "/usr/lib/freecad-python3", "/opt/freecad*"]
    for pat in pats:
        for d in sorted(glob.glob(pat), reverse=True):
            hit = _from_dir(Path(d))
            if hit:
                return hit
    for name in ("freecadcmd", "FreeCADCmd"):
        w = shutil.which(name)
        if w:
            return [w], {}
    return None


def require() -> tuple[list[str], dict[str, str]]:
    hit = find_freecad()
    if hit is None:
        raise AgentCADError("DEPENDENCY_MISSING", "FreeCAD is not available; 3D parts (.FCStd) need it",
                            category="dependency",
                            hint="Install FreeCAD 1.1 and set AGENTCAD_FREECAD to its folder (or its bin/python)")
    return hit


def available() -> bool:
    return find_freecad() is not None


def _wait_reporting(p, log: Path, deadline: float, on_progress) -> None:
    """Wait for the process like ``p.wait``, passing each new line of ``log`` to ``on_progress`` meanwhile."""
    pos = 0
    while True:
        try:
            p.wait(timeout=0.1)
            return
        except subprocess.TimeoutExpired:
            if time.perf_counter() >= deadline:
                raise
        try:
            with open(log, "rb") as f:
                f.seek(pos)
                data = f.read()
        except OSError:
            continue
        end = data.rfind(b"\n") + 1  # whole lines only: the runner may be writing the next one
        pos += end
        for raw in data[:end].splitlines():
            try:
                on_progress(json.loads(raw))
            except Exception:  # noqa: BLE001 - progress must never fail the job
                pass


def run(job: dict[str, Any], inputs: dict[str, Path] | None = None,
        outputs: dict[str, Path] | None = None, on_progress=None, timeout: float | None = None) -> dict[str, Any]:
    """Run one job; return the runner's result dict ({"ok": ...}). Raises only for process-level failures.

    ``on_progress(event)``: the runner writes one line per operation to ``progress.jsonl`` in the job folder
    ({"step", "total"} or {"phase": "checking"}); they are passed on while the job runs (polled every 0.1 s).

    FreeCAD reads and writes files only inside a short job folder under the system temp directory: deep workspace
    paths exceed Windows' 260-character limit when FreeCAD saves (it failed in pytest's temp folders). ``inputs``
    {job key: file} are copied in; ``outputs`` {job key: destination} are copied out when the job succeeds.
    ``timeout``: seconds (default AGENTCAD_FREECAD_TIMEOUT, 300).
    """
    limit = TIMEOUT if timeout is None else timeout
    cmd, extra = require()
    d = Path(tempfile.gettempdir()) / "agentcad-fc" / uuid.uuid4().hex[:12]
    d.mkdir(parents=True)
    job = dict(job)
    for key, src in (inputs or {}).items():
        local = d / f"{key}{src.suffix}"
        shutil.copy2(src, local)
        job[key] = str(local)
    for key, dst in (outputs or {}).items():
        job[key] = str(d / f"{key}{dst.suffix}")
    if on_progress is not None:
        job["progress"] = str(d / "progress.jsonl")
    (d / "job.json").write_text(json.dumps(job), "utf-8")
    args = cmd + [str(RUNNER)] + ([str(d)] if "-I" in cmd else [])
    env = {**os.environ, **extra, "AGENTCAD_FC_JOB": str(d)}
    t0 = time.perf_counter()
    done = False
    try:
        with open(d / "console.log", "wb") as fo:
            p = subprocess.Popen(args, cwd=d, stdout=fo, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 env=env, shell=False)
            try:
                if on_progress is None:
                    p.wait(timeout=limit)
                else:
                    _wait_reporting(p, d / "progress.jsonl", t0 + limit, on_progress)
            except subprocess.TimeoutExpired:
                p.kill()
                raise AgentCADError("FREECAD_TIMEOUT", f"FreeCAD did not finish within {limit:g}s",
                                    category="internal", retryable=True, details={"job": str(d)})
        res_path = d / "result.json"
        if not res_path.is_file():
            log = (d / "console.log").read_text("utf-8", errors="replace")[-2000:]
            raise AgentCADError("FREECAD_FAILED", f"FreeCAD exited with code {p.returncode} without a result",
                                category="internal", details={"log": log, "command": args[0], "job": str(d)})
        res = json.loads(res_path.read_text("utf-8"))
        res["seconds"] = round(time.perf_counter() - t0, 2)
        if res.get("ok"):
            for key, dst in (outputs or {}).items():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(job[key], dst)
        done = True
        return res
    finally:
        # a job that crashed stays for diagnosis (its path is in the error)
        if done and not os.environ.get("AGENTCAD_KEEP_JOBS"):
            shutil.rmtree(d, ignore_errors=True)
