"""Child process for ``run_script`` on a 3D part with language 'cadquery' (see scripting.py, part/service.py).

Started as ``python -I _cq_runner.py <job dir>`` with the job dir as cwd, by the interpreter AgentCAD runs in
(cadquery is the optional extra agentcad-runtime[cadquery]; FreeCAD's own Python cannot import it). Runs
job/script.py with ``cq`` imported, takes the solid the script leaves in ``result`` (a cq.Workplane, Shape or
Assembly; ``show_object(x)`` also counts) and writes it to job/result.brep, which the FreeCAD runner imports.
BREP is OpenCASCADE's own format: both sides use OCCT, so the solid crosses over exactly (no STEP translation).

The script has passed scripting.check_script(code, "cadquery"). Here it also gets reduced builtins and an import hook
limited to the same allow-list. This guards against mistakes; it is not a security sandbox.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path


class ScriptResultError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint


def _shapes(cq, value) -> list:
    if isinstance(value, cq.Workplane):
        return [v for v in value.vals() if isinstance(v, cq.Shape)]
    if isinstance(value, cq.Assembly):
        return [value.toCompound()]
    if isinstance(value, cq.Shape):
        return [value]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _shapes(cq, v)]
    wrapped = getattr(value, "wrapped", None)  # e.g. a cq.Sketch is not a solid; an OCP TopoDS_Shape is cast
    if wrapped is None and type(value).__module__.startswith("OCP"):
        return [cq.Shape.cast(value)]
    return []


def solid_of(cq, value):
    """The one solid the script built, or ScriptResultError (NO_RESULT, NOT_A_SOLID, NOT_SINGLE_SOLID)."""
    if value is None:
        raise ScriptResultError("NO_RESULT", "The script did not set `result`",
                                "End the script with result = <cq.Workplane or Shape holding the solid>")
    shapes = _shapes(cq, value)
    solids = [s for sh in shapes for s in sh.Solids()]
    if not solids:
        kinds = sorted({type(s).__name__ for s in shapes}) or [type(value).__name__]
        raise ScriptResultError("NOT_A_SOLID", f"`result` holds no solid (found {kinds})",
                                "Extrude, revolve or loft the sketch into a solid; a Workplane's stack must hold "
                                "the solid (e.g. result = wp.extrude(10))")
    fused = len(solids) > 1
    if fused:  # several solids on the stack (e.g. pushPoints + box with combine=False): unite them
        solid = solids[0].fuse(*solids[1:]).clean()
        solids = solid.Solids()
        if len(solids) != 1:
            raise ScriptResultError("NOT_SINGLE_SOLID", f"`result` holds {len(solids)} separate solids",
                                    "A part is one solid: make the pieces overlap or touch, then union them")
    solid = solids[0]
    return solid, fused


def main() -> None:
    job = Path(sys.argv[1])
    out: dict = {"ok": False}
    buf = io.StringIO()
    try:
        from agentcad._script_runner import SAFE_BUILTINS
        from agentcad.scripting import LANGUAGES
        allowed = LANGUAGES["cadquery"]["imports"]

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
            if level != 0 or name.split(".")[0] not in allowed:
                raise ImportError(f"import of {name!r} is not allowed in run_script")
            return __import__(name, globals, locals, fromlist, level)

        import math

        import cadquery as cq
        code = (job / "script.py").read_text(encoding="utf-8")
        safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
        safe["__import__"] = guarded_import
        safe["__build_class__"] = builtins.__build_class__
        shown: list = []
        env = {"__builtins__": safe, "__name__": "agent_script", "cq": cq, "cadquery": cq, "math": math,
               "result": None, "show_object": lambda obj, *a, **k: shown.append(obj)}
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, "agent_script.py", "exec"), env)  # the agent's script, checked beforehand
        except BaseException as exc:  # report everything, including SystemExit from the script
            tb = traceback.extract_tb(exc.__traceback__)
            src = code.splitlines()
            lines = [f"line {f.lineno}: {src[f.lineno - 1].strip() if 0 < f.lineno <= len(src) else ''}"
                     for f in tb if f.filename == "agent_script.py"]
            out = {"ok": False, "code": "SCRIPT_FAILED", "error": f"{type(exc).__name__}: {exc}",
                   "script_lines": lines[-3:], "traceback": "".join(traceback.format_exception(exc))[-3000:]}
        else:
            value = env.get("result")
            if value is None and shown:
                value = shown[-1] if len(shown) == 1 else shown
            solid, fused = solid_of(cq, value)
            if not solid.isValid():
                solid = solid.fix()
            solid.exportBrep(str(job / "result.brep"))
            bb = solid.BoundingBox()
            out = {"ok": True, "solids": 1, "fused": fused, "valid": solid.isValid(),
                   "volume": round(solid.Volume(), 6),
                   "size": [round(bb.xlen, 6), round(bb.ylen, 6), round(bb.zlen, 6)]}
    except ScriptResultError as exc:
        out = {"ok": False, "code": exc.code, "error": exc.message, "hint": exc.hint}
    except BaseException as exc:  # noqa: BLE001 - the runner itself (cadquery missing, export failed)
        code = "DEPENDENCY_MISSING" if isinstance(exc, ImportError) and "cadquery" in str(exc) else "SCRIPT_FAILED"
        out = {"ok": False, "code": code, "error": f"{type(exc).__name__}: {exc}",
               "traceback": "".join(traceback.format_exception(exc))[-3000:]}
    out["stdout"] = buf.getvalue()[-8000:]
    (job / "result.json").write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
