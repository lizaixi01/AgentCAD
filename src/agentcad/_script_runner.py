"""Child process for ``run_script`` (see scripting.py): loads job/in.dxf, runs job/script.py with the drawing as
``doc`` and saves job/out.dxf. Started as ``python -I _script_runner.py <job dir>`` with the job dir as cwd.

The script has already passed scripting.check_script. Here it additionally gets a reduced set of builtins and an
import hook limited to the same allow-list. This is a guard against mistakes, not a security sandbox.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import math
import sys
import traceback
from pathlib import Path

ALLOWED = ("ezdxf", "math", "cmath", "itertools", "functools", "collections", "json", "re", "statistics",
           "fractions", "decimal", "operator", "copy")
SAFE_BUILTINS = ("abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
                 "hasattr", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
                 "object", "pow", "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str",
                 "sum", "tuple", "type", "zip", "chr", "ord", "property", "staticmethod", "classmethod", "super",
                 "Exception", "ValueError", "KeyError", "IndexError", "TypeError", "ZeroDivisionError",
                 "RuntimeError", "StopIteration", "AssertionError", "ArithmeticError", "AttributeError",
                 "NotImplementedError", "LookupError", "True", "False", "None")


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if (level != 0 or name.split(".")[0] not in ALLOWED or name.startswith("ezdxf.addons.odafc")
            or "odafc" in (fromlist or ())):
        raise ImportError(f"import of {name!r} is not allowed in run_script")
    return __import__(name, globals, locals, fromlist, level)


def main() -> None:
    job = Path(sys.argv[1])
    out: dict = {"ok": False}
    buf = io.StringIO()
    try:
        import ezdxf
        from agentcad.model import get_tag, set_tag
        code = (job / "script.py").read_text(encoding="utf-8")
        doc = ezdxf.readfile(job / "in.dxf")
        safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
        safe["__import__"] = _guarded_import
        safe["__build_class__"] = builtins.__build_class__
        env = {"__builtins__": safe, "__name__": "agent_script", "doc": doc, "msp": doc.modelspace(),
               "ezdxf": ezdxf, "math": math, "get_tag": get_tag, "set_tag": lambda e, t: set_tag(doc, e, t),
               "result": None}
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "agent_script.py", "exec"), env)  # the agent's script, checked beforehand
        doc.saveas(job / "out.dxf")
        result = env.get("result")
        try:
            json.dumps(result)
        except TypeError:
            result = repr(result)
        out = {"ok": True, "result": result}
    except BaseException as exc:  # report everything, including SystemExit from the script
        tb = traceback.extract_tb(exc.__traceback__)
        lines = [f"line {f.lineno}: {f.line}" for f in tb if f.filename == "agent_script.py"]
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "script_lines": lines[-3:],
               "traceback": "".join(traceback.format_exception(exc))[-3000:]}
    out["stdout"] = buf.getvalue()[-8000:]
    (job / "result.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
