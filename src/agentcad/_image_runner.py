"""Child process for ``inspect_image(..., code=...)`` (see scripting.py, images.py): measures pixels of a workspace
image. Started as ``python -I _image_runner.py <job dir>`` with the job dir as cwd.

Loads job/image.png (the requested region of the source, unscaled) as ``image``, a numpy uint8 array of shape
(height, width, 3), with ``origin`` = (left, top) of the region in source pixels, and runs job/script.py. The
script prints what it measured and may set ``result``: an image (numpy array or PIL image), which this runner saves
to job/result.png for the caller to show, or a JSON value, which it returns. It never writes anything else.

The script has passed scripting.check_script(code, "image"). Here it also gets reduced builtins and an import hook
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

RESULT_CHARS = 16000


def _as_image(value):
    """A PIL image of ``value`` when it is an image (PIL image, or a 2D/3D numeric array), else None."""
    import numpy as np
    from PIL import Image
    if isinstance(value, Image.Image):
        return value.convert("RGB")
    if isinstance(value, np.ndarray) and value.ndim in (2, 3) and min(value.shape[:2]) > 0:
        a = value
        if a.ndim == 3 and a.shape[2] not in (1, 3, 4):
            return None
        if a.dtype == bool:
            a = a.astype(np.uint8) * 255
        elif a.dtype != np.uint8:
            a = np.clip(np.nan_to_num(a), 0, 255).astype(np.uint8)
        if a.ndim == 3 and a.shape[2] == 1:
            a = a[:, :, 0]
        return Image.fromarray(a).convert("RGB")
    return None


def _plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"{type(value).__name__} is not JSON")


def main() -> None:
    job = Path(sys.argv[1])
    out: dict = {"ok": False}
    buf = io.StringIO()
    try:
        import math

        import numpy as np
        from PIL import Image

        from agentcad._script_runner import SAFE_BUILTINS
        from agentcad.scripting import LANGUAGES
        allowed = LANGUAGES["image"]["imports"]

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
            if level != 0 or name.split(".")[0] not in allowed:
                raise ImportError(f"import of {name!r} is not allowed in an image script")
            return __import__(name, globals, locals, fromlist, level)

        code = (job / "script.py").read_text(encoding="utf-8")
        meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
        with Image.open(job / "image.png") as im:
            image = np.array(im.convert("RGB"))
        image.flags.writeable = False  # a script that draws on it should draw on image.copy()
        safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
        safe["__import__"] = guarded_import
        safe["__build_class__"] = builtins.__build_class__
        env = {"__builtins__": safe, "__name__": "agent_script", "np": np, "numpy": np, "math": math,
               "image": image, "origin": tuple(meta["origin"]), "result": None}
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, "agent_script.py", "exec"), env)  # the agent's script, checked beforehand
        except BaseException as exc:  # report everything, including SystemExit from the script
            tb = traceback.extract_tb(exc.__traceback__)
            src = code.splitlines()
            lines = [f"line {f.lineno}: {src[f.lineno - 1].strip() if 0 < f.lineno <= len(src) else ''}"
                     for f in tb if f.filename == "agent_script.py"]
            out = {"ok": False, "code": "SCRIPT_FAILED", "error": f"{type(exc).__name__}: {exc}",
                   "script_lines": lines[-3:]}
        else:
            value = env.get("result")
            picture = _as_image(value)
            out = {"ok": True}
            if picture is not None:
                picture.save(job / "result.png")
                out["image"] = list(picture.size)
            elif value is not None:
                try:  # numpy numbers and arrays become plain JSON
                    text = json.dumps(value, default=_plain)
                except (TypeError, ValueError):
                    text = json.dumps(repr(value))
                if len(text) > RESULT_CHARS:  # keep a stray full-size array from flooding the agent's context
                    out.update(result=text[:RESULT_CHARS], result_truncated=True)
                else:
                    out["result"] = json.loads(text)
    except BaseException as exc:  # noqa: BLE001 - the runner itself
        out = {"ok": False, "code": "SCRIPT_FAILED", "error": f"{type(exc).__name__}: {exc}",
               "traceback": "".join(traceback.format_exception(exc))[-3000:]}
    out["stdout"] = buf.getvalue()[-8000:]
    (job / "result.json").write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
