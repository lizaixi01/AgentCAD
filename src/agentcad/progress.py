"""Progress events: what the runtime is doing right now, in a form the live viewer can show in plain words.

Every tool call that changes (or checks) a drawing or part appends a few short JSON lines to
``<root>/.agentcad/activity.jsonl``::

    {"run": "1f3a9c20", "n": 1, "ts": 1761730000.12, "tool": "apply_operations", "drawing": "plate.dxf",
     "state": "working", "step": 3, "total": 7, "op": {"op": "add_circle", "diameter": 12}}

``state`` is ``working`` (one line when the call starts, then one per operation, at most every 50 ms),
``checking`` (validating the saved file), and finally ``done`` (with change counts, the operations grouped, the
validation verdict) or ``error`` (code and message). The viewer turns these into a progress bar, a status line and
an activity feed; the wording (English or Chinese) lives in the page, the runtime writes only data.

Writing a line is an append of ~200 bytes. It never raises: a full disk or a locked file costs a progress line,
never a commit. Nothing outside the workspace is written, and messages are scrubbed of absolute paths.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

from .policy import STATE_DIR, Policy

LOG_FILE = "activity.jsonl"
MAX_LOG_BYTES = 512 * 1024  # rotated to activity.jsonl.1 when a run starts above this size
STEP_INTERVAL = 0.05  # s: per-operation lines are written at most this often (the first and last always)
BRIEF_NUMBERS = ("diameter", "radius", "count", "occurrences", "rows", "cols", "width", "height", "length", "depth",
                 "thickness", "distance", "angle")
BRIEF_STRINGS = ("size", "kind", "text", "thread", "name", "plane", "pattern")
MAX_GROUPS = 40

_current: ContextVar["Activity | None"] = ContextVar("agentcad_activity", default=None)
_TAIL = r"(?:[^\s\"'<>|]*[^\s\"'<>|,.;:)\]])?"  # a path's characters, without the punctuation after it
_WIN_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/]" + _TAIL)
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|\\]+" + _TAIL)
_POSIX_PATH = re.compile(r"(?<![\w.~])/(?:home|Users|tmp|var|opt|mnt|usr|private|root|srv|etc|Volumes)(?:/"
                         + _TAIL + ")?")


def scrub(text: Any, root: Any = None) -> str:
    """``text`` without absolute paths: the workspace root becomes relative, any other absolute path '<path>'."""
    s = str(text if text is not None else "")
    if root is not None:
        for r in {str(root), str(root).replace("\\", "/")}:
            if r:
                s = s.replace(r + "\\", "").replace(r + "/", "").replace(r, ".")
    s = _UNC_PATH.sub("<path>", s)
    s = _WIN_PATH.sub("<path>", s)
    return _POSIX_PATH.sub("<path>", s)


def op_brief(raw: Any) -> dict[str, Any]:
    """The few parameters that make an operation readable ("a Ø12 hole", "4 holes M8"), nothing large."""
    if not isinstance(raw, dict):
        return {"op": "?"}
    out: dict[str, Any] = {"op": str(raw.get("op", "?"))[:60]}
    for k in BRIEF_NUMBERS:
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(v, 4) if isinstance(v, float) else v
    for k in BRIEF_STRINGS:
        v = raw.get(k)
        if isinstance(v, str) and v and not v.startswith("="):
            out[k] = v[:40]
    if raw.get("through_all") is True:
        out["through_all"] = True
    centers = raw.get("centers")
    if isinstance(centers, list) and centers:
        out["count"] = len(centers)
    shapes = raw.get("shapes")
    if isinstance(shapes, list):
        out["shapes"] = len(shapes)
    dims = raw.get("dims")
    if isinstance(dims, dict):
        out.update({k: v for k, v in dims.items() if k in ("radius", "height", "length", "width")
                    and isinstance(v, (int, float)) and not isinstance(v, bool)})
    params = raw.get("params")
    if isinstance(params, dict):
        out["params"] = {str(k)[:30]: v if isinstance(v, (int, float)) else str(v)[:30]
                         for k, v in list(params.items())[:6]}
    return out


def group_ops(ops: Any) -> list[dict[str, Any]]:
    """Identical briefs merged with a count ``n``, in order of first appearance: "Added 4 Ø8 circles". At most
    MAX_GROUPS groups; the rest is counted in a last {"op": "...", "n"}."""
    groups: dict[str, dict[str, Any]] = {}
    rest = 0
    for raw in ops if isinstance(ops, list) else []:
        b = op_brief(raw)
        key = json.dumps(b, sort_keys=True, default=str)
        if key in groups:
            groups[key]["n"] += 1
        elif len(groups) < MAX_GROUPS:
            groups[key] = {**b, "n": 1}
        else:
            rest += 1
    out = list(groups.values())
    if rest:
        out.append({"op": "...", "n": rest})
    return out


def log_path(policy: Policy):
    return policy.root / STATE_DIR / LOG_FILE


class Activity:
    """One tool call's progress lines. Every method swallows errors."""

    def __init__(self, policy: Policy, tool: str, drawing: str | None) -> None:
        self.policy = policy
        self.tool = tool
        self.drawing = drawing
        self.run = uuid.uuid4().hex[:8]
        self.n = 0
        self.t0 = time.time()
        self._last_step = 0.0
        self.total: int | None = None
        self.path = log_path(policy)
        self._rotate()

    def _rotate(self) -> None:
        try:
            if self.path.stat().st_size > MAX_LOG_BYTES:
                os.replace(self.path, self.path.with_name(LOG_FILE + ".1"))
        except OSError:  # missing, or a reader has it open (Windows): keep appending
            pass

    def emit(self, state: str, **fields: Any) -> None:
        try:
            self.n += 1
            ev = {"run": self.run, "n": self.n, "ts": round(time.time(), 3), "tool": self.tool,
                  "drawing": self.drawing, "state": state, **fields}
            line = json.dumps(ev, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:  # noqa: BLE001 - progress is best effort, never a reason to fail
            pass

    def step(self, index: int, total: int, raw: Any) -> None:
        """Operation ``index`` (0-based) of ``total`` is about to run."""
        now = time.monotonic()
        self.total = total
        if index in (0, total - 1) or now - self._last_step >= STEP_INTERVAL:
            self._last_step = now
            self.emit("working", step=index + 1, total=total, op=op_brief(raw))

    def finish(self, env: dict[str, Any], operations: Any = None) -> None:
        try:
            secs = round(time.time() - self.t0, 2)
            if env.get("drawing"):
                self.drawing = env["drawing"]
            if not env.get("ok"):
                e = env.get("error") or {}
                self.emit("error", seconds=secs, error={"code": e.get("code"),
                                                        "message": scrub(e.get("message"), self.policy.root)[:300],
                                                        **({"op_index": e["op_index"]} if e.get("op_index")
                                                           is not None else {})})
                return
            fields: dict[str, Any] = {"seconds": secs}
            ch = env.get("changes")
            if isinstance(ch, dict):
                fields["changes"] = {k: len(v) if isinstance(v, list) else v for k, v in ch.items()
                                     if k in ("added", "modified", "deleted")}
            if operations is not None:
                fields["ops"] = group_ops(operations)
                fields["total"] = len(operations) if isinstance(operations, list) else None
            val = env.get("validation")
            if isinstance(val, dict) and "passed" in val:
                fields["passed"] = bool(val["passed"])
                fields["issues"] = len(val.get("issues") or [])
            elif "passed" in env:
                fields["passed"] = bool(env["passed"])
                fields["issues"] = len(env.get("issues") or [])
            if env.get("restored") or env.get("checkpoint"):
                fields["checkpoint"] = str(env.get("restored") or env.get("checkpoint"))[:40]
            self.emit("done", **fields)
        except Exception:  # noqa: BLE001
            pass


def current() -> Activity | None:
    return _current.get()


def begin(act: Activity):
    return _current.set(act)


def end(token) -> None:
    _current.reset(token)


def step(index: int, total: int, raw: Any) -> None:
    """Called by the engines before each operation; a no-op unless a tracked tool call is running."""
    act = _current.get()
    if act is not None:
        act.step(index, total, raw)


def checking() -> None:
    act = _current.get()
    if act is not None:
        act.emit("checking", total=act.total)
