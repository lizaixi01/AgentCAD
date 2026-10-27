"""Headless AutoCAD driver for black-box research (accoreconsole.exe).

Not part of the runtime package: it launches an external process. Each job
gets its own directory under <repo>/.acadtmp/<job>/ (accoreconsole fails to
run scripts from very long paths), a LISP file and a script that loads it and
quits. LISP writes results as ``key=value`` lines to ``result.txt``.

    from acad import run_lisp
    res = run_lisp("probe", '(out "ver" (getvar "ACADVER"))')
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

ACCORE = Path(os.environ.get("AGENTCAD_ACCORECONSOLE", r"D:\Apps\AutoCAD\AutoCAD 2027\accoreconsole.exe"))
WORK = Path(__file__).resolve().parents[2] / ".acadtmp"

PRELUDE = r'''
(setq *out* (open "%RESULT%" "w"))
(defun out (k v) (write-line (strcat k "=" (vl-princ-to-string v)) *out*))
(defun pt2s (p) (strcat (rtos (car p) 2 10) "," (rtos (cadr p) 2 10)))
(setvar "CMDECHO" 0) (setvar "EXPERT" 5)
'''
EPILOGUE = '\n(close *out*)\n(princ)\n'


def available() -> bool:
    return ACCORE.is_file()


class AcadResult:
    def __init__(self, job_dir: Path, rc: int | None, log: str, values: list[tuple[str, str]]):
        self.dir, self.rc, self.log, self.pairs = job_dir, rc, log, values

    def get(self, key: str, default=None):
        for k, v in self.pairs:
            if k == key:
                return v
        return default

    def all(self, key: str) -> list[str]:
        return [v for k, v in self.pairs if k == key]

    def __repr__(self) -> str:
        return f"AcadResult(rc={self.rc}, {len(self.pairs)} values, dir={self.dir})"


def run_lisp(job: str, lisp: str, *, dwg: Path | None = None, timeout: int = 180,
             files: dict[str, Path] | None = None) -> AcadResult:
    """Run ``lisp`` in accoreconsole (optionally opening ``dwg``) and collect results."""
    d = WORK / job
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for name, src in (files or {}).items():
        shutil.copy2(src, d / name)
    result = d / "result.txt"
    body = PRELUDE.replace("%RESULT%", result.as_posix()) + lisp.replace("%DIR%", d.as_posix()) + EPILOGUE
    # The LISP goes inline into the script: (load "...") is refused by SECURELOAD for untrusted
    # folders, and we do not change that security setting. Blank lines would repeat the last
    # command, so they are dropped; ';' comments are not allowed in job LISP.
    lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
    (d / "job.scr").write_text("\n".join(lines) + "\n_.QUIT _Y\n", encoding="utf-8")
    args = [str(ACCORE), "/s", str(d / "job.scr")]
    if dwg is not None:
        local = d / Path(dwg).name
        if Path(dwg).resolve() != local.resolve():
            shutil.copy2(dwg, local)
        args = [str(ACCORE), "/i", str(local), "/s", str(d / "job.scr")]
    t0 = time.perf_counter()
    with open(d / "console.log", "wb") as fo:
        p = subprocess.Popen(args, cwd=d, stdout=fo, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = None
    raw = (d / "console.log").read_bytes()
    log = raw.decode("utf-16-le", "replace")
    pairs = []
    if result.is_file():
        for line in result.read_text("utf-8", "replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                pairs.append((k, v))
    r = AcadResult(d, rc, log, pairs)
    r.seconds = round(time.perf_counter() - t0, 2)
    return r
