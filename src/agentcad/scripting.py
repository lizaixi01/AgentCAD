"""Opt-in escape hatch: run an agent-written ezdxf script on a drawing, inside the runtime's transaction.

Some edits are outside the operation catalogue (the comparison trials showed real drawings needing them). Rather
than letting the agent edit files directly, ``Runtime.run_script`` takes Python source, and this module
  1. checks it statically (imports limited to ezdxf and the standard math/data modules; no file, eval/exec,
     getattr or dunder access; no saving, reading or creating documents),
  2. runs it in a separate Python process (``-I``, no shell, time limit) on a copy of the drawing,
  3. hands the result back to the runtime, which re-reads it strictly and commits it like any batch: checkpoint,
     journal (with the full script), diff, independent validation, optional ``strict``.
3D parts (``.FCStd``) take CadQuery or FreeCAD Part scripts that build a solid (``LANGUAGES``, part/service.py).
``inspect_image(..., code=...)`` takes read-only numpy scripts that measure an image's pixels (images.py).
It is disabled unless the policy allows scripts (``AGENTCAD_ALLOW_SCRIPTS=1``). The checks guard against mistakes;
they are not a security sandbox: only enable scripts for agents you would let run Python as your user.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .errors import AgentCADError, input_error

ALLOWED_IMPORTS = {"ezdxf", "math", "cmath", "itertools", "functools", "collections", "json", "re", "statistics",
                   "fractions", "decimal", "operator", "copy"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "exit", "quit", "help", "memoryview", "dir"}
BANNED_ATTRS = {"saveas", "save", "readfile", "readzip", "write", "write_text", "write_bytes", "unlink", "rmdir",
                "system", "popen", "spawn", "odafc"}
RUNNER = Path(__file__).with_name("_script_runner.py")
CQ_RUNNER = Path(__file__).parent / "part" / "_cq_runner.py"
IMAGE_RUNNER = Path(__file__).with_name("_image_runner.py")

# 3D part scripts (run_script on a .FCStd): the program builds a solid and sets ``result``; the runtime stores it.
# Each runs in a process of its own: CadQuery in a child of this interpreter (cadquery is the optional extra
# agentcad-runtime[cadquery]), FreeCAD Part code in a FreeCAD process with no document open. The names below reject
# the usual ways of reading, writing, importing or exporting files and of reaching FreeCAD's documents and settings.
# They are not complete (numpy and OCP offer more ways): like the 2D check, this guards against mistakes; the
# boundary is that scripts are off unless the policy allows them.
_DATA = {"math", "cmath", "itertools", "functools", "collections", "re", "statistics", "fractions", "decimal",
         "operator", "copy", "typing", "dataclasses", "enum"}
_FILE_ATTRS = {"save", "saveas", "saveAs", "write", "write_text", "write_bytes", "read_text", "read_bytes", "unlink",
               "rmdir", "mkdir", "system", "popen", "spawn", "export", "exporters", "importers", "exportStep",
               "exportStl", "exportBrep", "exportBin", "exportBinary", "exportSvg", "exportDXF", "exportIges",
               "importStep", "importBrep", "importStl", "importDXF", "importBin", "importBinary", "importSvg", "read",
               "readfile", "open", "load", "dump", "loadtxt", "savetxt", "fromfile", "tofile",
               # numpy and OCP file access and native code
               "savez", "savez_compressed", "genfromtxt", "fromregex", "memmap", "open_memmap", "DataSource",
               "ctypeslib", "ctypes",
               "load_library", "Write", "Read", "Write_s", "Read_s",
               # FreeCAD: documents and settings belong to the runtime, not to the script
               "openDocument", "newDocument", "closeDocument", "getDocument", "listDocuments", "ActiveDocument",
               "activeDocument", "setActiveDocument", "loadFile", "ParamGet",
               # cadquery.vis opens a window and would wait for it until the time limit
               "vis"}
LANGUAGES: dict[str, dict] = {
    "ezdxf": {"imports": ALLOWED_IMPORTS, "attrs": BANNED_ATTRS,
              "hint": "Scripts get the drawing as `doc` (and `msp`); edit it in place, do not open, save or import "
                      "other files."},
    "cadquery": {"imports": _DATA | {"cadquery", "numpy"}, "attrs": _FILE_ATTRS,
                 "hint": "Build the part with CadQuery (`cq` is imported) and set `result` to a cq.Workplane or "
                         "Shape (show_object(x) also works); do not import, export or open files."},
    "freecad": {"imports": _DATA | {"Part", "FreeCAD", "numpy"}, "attrs": _FILE_ATTRS,
                "hint": "Build the part with FreeCAD's Part module (`Part`, `App`, `Vector` are given) and set "
                        "`result` to a Part.Shape; do not open, save or export documents or files."},
    # numpy (and scipy where installed) on the pixels of one image; PIL to draw an overlay (Image.fromarray,
    # ImageDraw). Besides the file names above: no screen or clipboard capture (PIL.ImageGrab), font files, scipy's
    # file readers and writers (scipy.io) or its dataset downloads
    "image": {"imports": _DATA | {"numpy", "scipy", "PIL"},
              "attrs": _FILE_ATTRS | {"ImageGrab", "grab", "grabclipboard", "truetype", "FreeTypeFont", "load_path",
                                      "io", "datasets"},
              "hint": "Measure the pixels of `image` (numpy uint8, height x width x 3; source pixel = local + "
                      "`origin`) and print the numbers; optionally set `result` to an image array or a JSON "
                      "value. Do not open or save files."},
}


def check_script(code: str, language: str = "ezdxf") -> None:
    """Static allow-list check. Raises input_error SCRIPT_REJECTED with the line of the first problem."""
    lang = LANGUAGES[language]
    allowed, banned_attrs = lang["imports"], lang["attrs"]
    if not code or not code.strip():
        raise input_error("SCRIPT_EMPTY", "The script is empty")
    try:
        tree = ast.parse(code, filename="agent_script.py")
    except SyntaxError as exc:
        raise input_error("SCRIPT_SYNTAX", f"Syntax error at line {exc.lineno}: {exc.msg}",
                          details={"line": exc.lineno, "text": (exc.text or "").strip()})

    def reject(node: ast.AST, why: str) -> None:
        raise input_error("SCRIPT_REJECTED", f"Line {getattr(node, 'lineno', '?')}: {why}",
                          details={"line": getattr(node, "lineno", None)},
                          hint=f"{lang['hint']} Allowed imports: {sorted(allowed)}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if parts[0] not in allowed or "odafc" in a.name or any(p in banned_attrs for p in parts[1:]):
                    reject(node, f"import of {a.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            parts = mod.split(".")
            if node.level or parts[0] not in allowed or "odafc" in mod or any(p in banned_attrs for p in parts[1:]):
                reject(node, f"import from {mod!r} is not allowed")
            for a in node.names:  # e.g. "from ezdxf.addons import odafc" (launches an external converter)
                if a.name == "odafc" or a.name.startswith("__") or a.name in banned_attrs:
                    reject(node, f"import of {mod}.{a.name!r} is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                reject(node, f"use of {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in banned_attrs:
                reject(node, f"attribute {node.attr!r} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            reject(node, "global/nonlocal statements are not allowed")


def run(source: Path, code: str, job: Path, timeout: float) -> dict[str, Any]:
    """Run ``code`` on a copy of ``source`` in a child process. Returns the runner's result dict; on success
    ``job / 'out.dxf'`` holds the edited drawing."""
    job.mkdir(parents=True, exist_ok=True)
    (job / "in.dxf").write_bytes(source.read_bytes())
    (job / "script.py").write_text(code, encoding="utf-8")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, "-I", str(RUNNER), str(job)], cwd=job, shell=False,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AgentCADError("SCRIPT_TIMEOUT", f"The script ran longer than {timeout:g} s and was stopped",
                            category="input", hint="Simplify the script or split the work into several runs")
    res_file = job / "result.json"
    if not res_file.is_file():
        raise AgentCADError("SCRIPT_CRASHED", "The script process ended without a result", category="internal",
                            details={"returncode": proc.returncode,
                                     "stderr": proc.stderr.decode("utf-8", "replace")[-2000:]})
    res = json.loads(res_file.read_text(encoding="utf-8"))
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res


def run_cadquery(code: str, job: Path, timeout: float) -> dict[str, Any]:
    """Run a CadQuery program (already checked) in a child process of this interpreter, with the job folder as
    working directory. On success ``job / 'result.brep'`` holds the solid and the result dict describes it."""
    job.mkdir(parents=True, exist_ok=True)
    (job / "script.py").write_text(code, encoding="utf-8")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, "-I", str(CQ_RUNNER), str(job)], cwd=job, shell=False,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AgentCADError("SCRIPT_TIMEOUT", f"The script ran longer than {timeout:g} s and was stopped",
                            category="input", hint="Simplify the script (CadQuery itself takes a few seconds to "
                                                   "load), or raise AGENTCAD_SCRIPT_TIMEOUT")
    res_file = job / "result.json"
    if not res_file.is_file():
        raise AgentCADError("SCRIPT_CRASHED", "The script process ended without a result", category="internal",
                            details={"returncode": proc.returncode,
                                     "stderr": proc.stderr.decode("utf-8", "replace")[-2000:]})
    res = json.loads(res_file.read_text(encoding="utf-8"))
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res


def run_image(code: str, crop: bytes, origin: tuple[int, int], job: Path, timeout: float) -> dict[str, Any]:
    """Run an image-measuring script (already checked) on ``crop`` (PNG bytes of the region whose top-left source
    pixel is ``origin``) in a child process. On success with an image result ``job / 'result.png'`` holds it."""
    job.mkdir(parents=True, exist_ok=True)
    (job / "script.py").write_text(code, encoding="utf-8")
    (job / "image.png").write_bytes(crop)
    (job / "job.json").write_text(json.dumps({"origin": list(origin)}), encoding="utf-8")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, "-I", str(IMAGE_RUNNER), str(job)], cwd=job, shell=False,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AgentCADError("SCRIPT_TIMEOUT", f"The script ran longer than {timeout:g} s and was stopped",
                            category="input", hint="Measure a smaller region, or vectorise loops over pixels "
                                                   "with numpy")
    res_file = job / "result.json"
    if not res_file.is_file():
        raise AgentCADError("SCRIPT_CRASHED", "The script process ended without a result", category="internal",
                            details={"returncode": proc.returncode,
                                     "stderr": proc.stderr.decode("utf-8", "replace")[-2000:]})
    res = json.loads(res_file.read_text(encoding="utf-8"))
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res
