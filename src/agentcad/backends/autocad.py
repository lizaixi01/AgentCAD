"""Optional AutoCAD backend (headless accoreconsole.exe): DWG import/export and
AutoCAD's own AUDIT. Everything else in the runtime works without it.

Configuration: AGENTCAD_ACCORECONSOLE=<path to accoreconsole.exe>; otherwise it is
discovered under "C:/Program Files/Autodesk/AutoCAD */" or from the AcadLocation
registry value of installed releases (HKLM/SOFTWARE/Autodesk/AutoCAD).

Safety: the executable comes only from that configuration, runs without a shell
and with a timeout, in a job folder created by the runtime. Input files are
copied in under fixed ASCII names (accoreconsole cannot run scripts that mention
non-ASCII paths), so the generated script never contains caller-supplied text.
Scripts are inline (no LISP ``load``) because SECURELOAD refuses untrusted
folders, and that setting is left untouched. Every point argument would need
"_non" because running object snaps alter command input, but these jobs pass
no coordinates.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess  # the only module of the runtime that starts a process (see tests/test_security.py)
import time
import uuid
from pathlib import Path

from ..errors import AgentCADError

DWG_VERSIONS = {"2018": "2018", "2013": "2013", "2010": "2010", "2007": "2007", "2004": "2004", "2000": "2000"}
DXF_OUT_VERSIONS = {"2018", "2013", "2010", "2007", "2004", "2000", "R12"}
TIMEOUT = 180


def find_accoreconsole() -> Path | None:
    env = os.environ.get("AGENTCAD_ACCORECONSOLE")
    if env:
        p = Path(env)
        return p if p.is_file() else None
    hits = [Path(h) for h in sorted(glob.glob(r"C:\Program Files\Autodesk\AutoCAD *\accoreconsole.exe"))]
    hits += _registry_locations()
    hits = [h for h in hits if h.is_file()]
    return hits[-1] if hits else None


def _registry_locations() -> list[Path]:
    """AcadLocation of installed releases (HKLM/SOFTWARE/Autodesk/AutoCAD/R*/ACAD-*), oldest first."""
    try:
        import winreg
    except ImportError:
        return []
    found: list[Path] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Autodesk\AutoCAD")
    except OSError:
        return []
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            rel = winreg.EnumKey(root, i)
            with winreg.OpenKey(root, rel) as rk:
                for j in range(winreg.QueryInfoKey(rk)[0]):
                    try:
                        with winreg.OpenKey(rk, winreg.EnumKey(rk, j)) as pk:
                            loc, _ = winreg.QueryValueEx(pk, "AcadLocation")
                            found.append(Path(loc) / "accoreconsole.exe")
                    except OSError:
                        continue
    return found


def require() -> Path:
    exe = find_accoreconsole()
    if exe is None:
        raise AgentCADError("DEPENDENCY_MISSING", "AutoCAD (accoreconsole.exe) is not available", category="dependency",
                            hint="Install AutoCAD and set AGENTCAD_ACCORECONSOLE to its accoreconsole.exe")
    return exe


def _run(job_root: Path, inputs: dict[str, Path], body: list[str], *, open_dwg: str | None = None) -> tuple[Path, str]:
    exe = require()
    if not str(job_root).isascii():  # accoreconsole cannot use non-ASCII script paths
        import tempfile
        job_root = Path(tempfile.gettempdir()) / "agentcad-acad"
        if not str(job_root).isascii():
            raise AgentCADError("UNSUPPORTED_PATH", "The AutoCAD backend needs an ASCII-only job folder",
                                category="dependency", details={"path": str(job_root)})
    d = job_root / uuid.uuid4().hex[:12]
    d.mkdir(parents=True)
    for name, src in inputs.items():
        shutil.copy2(src, d / name)
    body = [b.replace("__JOBDIR__", d.as_posix()) for b in body]
    res = (d / "result.txt").as_posix()
    lines = [f'(setq *out* (open "{res}" "w"))', '(setvar "CMDECHO" 0)', '(setvar "EXPERT" 5)',
             *body, '(write-line "done=1" *out*)', "(close *out*)", "_.QUIT _Y"]
    (d / "job.scr").write_text("\n".join(lines) + "\n", encoding="ascii")
    args = [str(exe)] + (["/i", str(d / open_dwg)] if open_dwg else []) + ["/s", str(d / "job.scr")]
    t0 = time.perf_counter()
    with open(d / "console.log", "wb") as fo:
        p = subprocess.Popen(args, cwd=d, stdout=fo, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False)
        try:
            p.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            raise AgentCADError("AUTOCAD_TIMEOUT", f"AutoCAD did not finish within {TIMEOUT}s", category="internal",
                                retryable=True, details={"job": str(d)})
    log = (d / "console.log").read_bytes().decode("utf-16-le", "replace")
    if not (d / "result.txt").is_file() or "done=1" not in (d / "result.txt").read_text("utf-8", "replace"):
        raise AgentCADError("AUTOCAD_FAILED", "AutoCAD job did not complete", category="internal",
                            details={"job": str(d), "log_tail": log[-1500:]})
    (d / "seconds.txt").write_text(f"{time.perf_counter() - t0:.2f}")
    return d, log


def _audit_lines(log: str, marker: str = '"_.AUDIT"') -> list[str]:
    # DXFIN already audits implicitly; only the explicit AUDIT's report is counted
    seg = log[log.rfind(marker):] if marker in log else log
    keys = ("重复", "无效", "错误", "Error", "error", "invalid", "duplicate", "found")
    return [ln.strip() for ln in seg.splitlines() if ln.strip() and any(k in ln for k in keys)][:5000]


def dxf_to_dwg(src: Path, dst: Path, job_root: Path, version: str = "2018") -> dict:
    v = DWG_VERSIONS[version]
    d, log = _run(job_root, {"in.dxf": src}, [
        f'(command "_.DXFIN" "__JOBDIR__/in.dxf")',
        f'(command "_.SAVEAS" "{v}" "__JOBDIR__/out.dwg")'])
    return _finish(d, "out.dwg", dst, log)


def dwg_to_dxf(src: Path, dst: Path, job_root: Path, version: str = "2018") -> dict:
    if version not in DXF_OUT_VERSIONS:
        raise AgentCADError("UNSUPPORTED_DXF_VERSION", f"AutoCAD DXFOUT version {version!r} not supported",
                            category="input")
    d, log = _run(job_root, {"in.dwg": src}, [
        # Binary DXF preserves database doubles. AutoCAD's ASCII precision=16
        # can change an eight-decimal dimension at a large coordinate offset.
        # Callers read this intermediate with ezdxf; normal workspace commits
        # still serialize text DXF with roundtrippable Python float values.
        f'(command "_.DXFOUT" "__JOBDIR__/out.dxf" "_V" "{version}" "_Binary")'], open_dwg="in.dwg")
    return _finish(d, "out.dxf", dst, log)


def audit_dxf(src: Path, job_root: Path) -> dict:
    """DXFIN into a fresh drawing and run AUDIT without fixing; returns AutoCAD's findings."""
    d, log = _run(job_root, {"in.dxf": src}, [
        f'(command "_.DXFIN" "__JOBDIR__/in.dxf")',
        '(setq ss (ssget "X"))',
        '(write-line (strcat "nent=" (if ss (itoa (sslength ss)) "0")) *out*)',
        '(write-line (strcat "insunits=" (itoa (getvar "INSUNITS"))) *out*)',
        '(command "_.AUDIT" "_N")'])
    vals = dict(ln.split("=", 1) for ln in (d / "result.txt").read_text("utf-8").splitlines() if "=" in ln)
    msgs = _audit_lines(log)
    audit_seg = log[log.rfind('"_.AUDIT"'):] if '"_.AUDIT"' in log else log
    totals = [int(x) for x in re.findall(r"(?:共发现\s*|Total errors found\s*)(\d+)", audit_seg)]
    counts: dict[str, int] = {}
    for m in msgs:
        if "共发现" not in m and "Total errors" not in m:
            counts[m] = counts.get(m, 0) + 1  # AutoCAD repeats one message per offending record
    # DXFIN may discard the whole drawing (e.g. NaN, unregistered XDATA APPID); AUDIT then sees nothing
    imp = log[log.find("DXFIN"):log.rfind('"_.AUDIT"')] if "DXFIN" in log else ""
    rejected = any(k in imp for k in ("图形被放弃", "drawing discarded", "Invalid or incomplete DXF"))
    import_msgs = [ln.strip() for ln in imp.splitlines()
                   if any(k in ln for k in ("错误", "无效", "放弃", "Error", "Invalid", "discarded"))][:20]
    seconds = float((d / "seconds.txt").read_text())
    shutil.rmtree(d, ignore_errors=True)  # failed jobs are kept (see _run) for forensics
    return {"import_rejected": rejected, "import_messages": import_msgs,
            "entities_seen_by_autocad": int(vals.get("nent", 0)), "insunits": int(vals.get("insunits", -1)),
            "audit_errors": totals[-1] if totals else None,
            "messages": [{"message": m, "count": n} for m, n in list(counts.items())[:50]],
            "seconds": seconds}


def _finish(d: Path, name: str, dst: Path, log: str) -> dict:
    out = d / name
    if not out.is_file() or out.stat().st_size == 0:
        raise AgentCADError("AUTOCAD_FAILED", f"AutoCAD produced no {name}", category="internal",
                            details={"job": str(d), "log_tail": log[-1500:]})
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".agentcad-tmp")
    shutil.copy2(out, tmp)
    os.replace(tmp, dst)
    seconds = float((d / "seconds.txt").read_text())
    shutil.rmtree(d, ignore_errors=True)
    return {"bytes": dst.stat().st_size, "seconds": seconds}
