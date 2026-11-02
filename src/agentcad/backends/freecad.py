"""Optional FreeCAD backend for the live viewer's 3D view. AgentCAD does not build 3D parts: agents write them with
their own code and save them in the workspace, and the viewer shows each saved version. Every job runs
``backends/_fc_view.py`` in a separate FreeCAD process. The job folder holds ``job.json`` (action and files as data)
and receives ``result.json``. Nothing the caller sends becomes code or a command line: the arguments are the
interpreter, the fixed script path and the job folder.

Configuration: AGENTCAD_FREECAD = FreeCAD's install folder, its ``bin`` folder, its bundled ``python`` or
``freecadcmd``. Otherwise FREECAD_LIB (the folder holding FreeCAD.pyd/.so, imported by this interpreter), then the
usual install locations and ``freecadcmd`` on PATH. FreeCAD 1.1 is the tested release.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess  # starts FreeCAD, and stops its process tree on a timeout (see tests/test_security.py)
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ..errors import AgentCADError

RUNNER = Path(__file__).resolve().with_name("_fc_view.py")
TIMEOUT = float(os.environ.get("AGENTCAD_FREECAD_TIMEOUT", "120"))
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
        raise AgentCADError("DEPENDENCY_MISSING", "FreeCAD is not available; the viewer needs it to show 3D files",
                            category="dependency",
                            hint="Install FreeCAD 1.1 and set AGENTCAD_FREECAD to its folder (or its bin/python)")
    return hit


def available() -> bool:
    return find_freecad() is not None


MEMO = "freecad.txt"  # <workspace>/.agentcad/freecad.txt: the AGENTCAD_FREECAD an agent app was configured with


def remember(state_dir: Path) -> None:
    """Keep this process's AGENTCAD_FREECAD for the workspace: a viewer opened from the desktop icon does not get the
    environment the agent apps start AgentCAD with (the MCP server calls this at start)."""
    path = os.environ.get("AGENTCAD_FREECAD")
    if not path or find_freecad() is None:
        return
    try:
        memo = state_dir / MEMO
        if not memo.is_file() or memo.read_text("utf-8").strip() != path:
            state_dir.mkdir(parents=True, exist_ok=True)
            memo.write_text(path, "utf-8")
    except OSError:
        pass


def recall(state_dir: Path) -> None:
    """Use the workspace's remembered FreeCAD when this process has none of its own."""
    if os.environ.get("AGENTCAD_FREECAD") or os.environ.get("FREECAD_LIB") or find_freecad() is not None:
        return
    try:
        path = (state_dir / MEMO).read_text("utf-8").strip()
    except OSError:
        return
    if path and Path(path).exists():
        os.environ["AGENTCAD_FREECAD"] = path


def _kill_tree(p) -> None:
    """Stop FreeCAD and wait for it. On Windows FreeCADCmd.exe is a launcher and the work runs in a child
    freecadcmd.exe that p.kill() alone leaves running (an endless script then burns a core for good, and keeps
    console.log open so its job folder cannot be removed). Elsewhere it runs in a session of its own (see Popen)."""
    if os.name == "nt":
        # by its full path, so no other 'taskkill' on PATH runs; /T follows recorded parent ids, called right
        # after our own child stopped answering
        taskkill = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe")
        try:
            subprocess.run([taskkill, "/F", "/T", "/PID", str(p.pid)], shell=False, capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        import signal
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    p.kill()
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def run(job: dict[str, Any], inputs: dict[str, Path] | None = None,
        outputs: dict[str, Path] | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Run one job; return the script's result dict ({"ok": ...}). Raises only for process-level failures.
    FreeCAD reads and writes files only inside a short job folder under the system temp directory (deep workspace
    paths exceed Windows' 260-character limit). ``inputs`` {job key: file} are copied in; ``outputs`` {job key:
    destination} are copied out when the job succeeds. ``timeout``: seconds (default AGENTCAD_FREECAD_TIMEOUT, 120).
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
    (d / "job.json").write_text(json.dumps(job), "utf-8")
    args = cmd + [str(RUNNER)] + ([str(d)] if "-I" in cmd else [])
    env = {**os.environ, **extra, "AGENTCAD_FC_JOB": str(d)}
    t0 = time.perf_counter()
    done = False
    try:
        with open(d / "console.log", "wb") as fo:
            p = subprocess.Popen(args, cwd=d, stdout=fo, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 env=env, shell=False, start_new_session=os.name != "nt")
            try:
                p.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                raise AgentCADError("FREECAD_TIMEOUT", f"FreeCAD did not finish within {limit:g}s",
                                    category="internal", retryable=True, details={"job": str(d)})
            except BaseException:  # Ctrl+C or any other exit: FreeCAD runs in a session of its own, stop it too
                _kill_tree(p)
                raise
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
