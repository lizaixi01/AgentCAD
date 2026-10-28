"""Optional live AutoCAD session (the user's running AutoCAD GUI, over COM; Windows + pywin32).

The agent keeps editing the DXF through the runtime (transactions, checkpoints, validation); this backend shows
the result in AutoCAD and brings the user's edits back:

    open    open a workspace drawing in AutoCAD (start=True launches AutoCAD if it is not running)
    reload  re-open it after the runtime changed the file, keeping the user's view
    pull    save what the user changed in AutoCAD to a temporary DXF; the runtime commits it like any edit
    zoom    show a region of the drawing
    command send a command line to AutoCAD (policy-gated)

Nothing here changes AutoCAD settings: system variables are only read (VIEWCTR/VIEWSIZE), and documents with
unsaved edits in the GUI are never closed unless the caller says discard=True.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from ..errors import AgentCADError

PROGID = "AutoCAD.Application"
AC2018_DXF = 65  # AcSaveAsType.ac2018_dxf
RPC_E_CALL_REJECTED = -2147418111  # AutoCAD is busy (modal dialog, running command)
BUSY_HINT = ("AutoCAD is running a command or showing a dialog (a sign-in or licence screen blocks it the same "
             "way); the user has to finish or close it in AutoCAD, then retry")


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _com():
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise AgentCADError("DEPENDENCY_MISSING", "The live AutoCAD session needs pywin32 on Windows",
                            category="dependency", hint="pip install pywin32 (Windows only)")
    return pythoncom, win32com.client


def progids() -> list[str]:
    """AutoCAD.Application ProgIDs to try, newest release first. AutoCAD 2027 registers only the versioned
    AutoCAD.Application.26, not the version-independent name. AGENTCAD_ACAD_PROGID overrides."""
    if os.environ.get("AGENTCAD_ACAD_PROGID"):
        return [os.environ["AGENTCAD_ACAD_PROGID"]]
    found = []
    try:
        import winreg
        i = 0
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if name.startswith(PROGID + ".") and name.rsplit(".", 1)[1].isdigit():
                    found.append(name)
    except (ImportError, OSError):
        pass
    return sorted(found, key=lambda n: int(n.rsplit(".", 1)[1]), reverse=True) + [PROGID]


def connect(start: bool = False):
    """The running AutoCAD application, or None. start=True launches it (visible) when none is running."""
    pythoncom, client = _com()
    ids = progids()
    for pid in ids:
        try:
            return client.dynamic.Dispatch(client.GetActiveObject(pid)._oleobj_)
        except pythoncom.com_error:
            continue
    if not start:
        return None
    errors = []
    for pid in ids:
        try:
            app = client.dynamic.Dispatch(pid)
            break
        except pythoncom.com_error as exc:
            errors.append(f"{pid}: {exc}")
    else:
        raise AgentCADError("AUTOCAD_NOT_AVAILABLE", "Could not start AutoCAD over COM", category="dependency",
                            details={"tried": errors},
                            hint="Is AutoCAD installed for this user? AGENTCAD_ACAD_PROGID names the COM class")
    _retry(lambda: app.Documents.Count, seconds=90)  # wait until AutoCAD has finished starting
    _retry(lambda: setattr(app, "Visible", True))
    return app


@contextmanager
def com_thread():
    """COM must be initialised on every thread that uses it (MCP tools run on worker threads)."""
    try:
        import pythoncom
    except ImportError:
        yield
        return
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _retry(fn: Callable[[], Any], seconds: float = 30.0):
    """Call into AutoCAD, waiting while it rejects calls because it is busy."""
    pythoncom, _ = _com()
    deadline = time.monotonic() + seconds
    while True:
        try:
            return fn()
        except AttributeError as exc:
            # pywin32's late binding reports a rejected name lookup (AutoCAD busy or still starting) this way
            if time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            raise AgentCADError("AUTOCAD_BUSY", f"AutoCAD did not answer within {seconds:g}s ({exc})",
                                category="dependency", retryable=True, hint=BUSY_HINT)
        except pythoncom.com_error as exc:
            busy = bool(exc.args) and exc.args[0] == RPC_E_CALL_REJECTED
            if busy and time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            raise AgentCADError("AUTOCAD_BUSY" if busy else "AUTOCAD_COM_ERROR",
                                f"AutoCAD rejected the request: {exc}", category="dependency" if busy else "internal",
                                retryable=True, hint=BUSY_HINT)


def _point(xyz):
    pythoncom, client = _com()
    return client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in xyz))


class Session:
    def __init__(self, app) -> None:
        self.app = app

    def documents(self) -> list:
        docs = _retry(lambda: self.app.Documents)
        return [_retry(lambda i=i: docs.Item(i)) for i in range(_retry(lambda: docs.Count))]

    def find(self, path: Path):
        want = _norm(path)
        return next((d for d in self.documents() if _norm(_retry(lambda d=d: d.FullName)) == want), None)

    def describe(self, doc) -> dict[str, Any]:
        return {"name": _retry(lambda: doc.Name), "path": _retry(lambda: doc.FullName),
                "unsaved_changes": not bool(_retry(lambda: doc.Saved))}

    def status(self) -> dict[str, Any]:
        active = None
        try:
            active = _retry(lambda: self.app.ActiveDocument.FullName)
        except AgentCADError:
            pass
        return {"version": _retry(lambda: self.app.Version), "documents": [self.describe(d) for d in self.documents()],
                "active": active}

    def view(self, doc) -> tuple[tuple, float] | None:
        try:
            return tuple(_retry(lambda: doc.GetVariable("VIEWCTR"))), float(_retry(lambda: doc.GetVariable("VIEWSIZE")))
        except (AgentCADError, TypeError, ValueError):
            return None

    def set_view(self, view) -> None:
        if view:
            center, size = view
            _retry(lambda: self.app.ZoomCenter(_point(center), size))

    def open(self, path: Path):
        doc = self.find(path)
        if doc is None:
            doc = _retry(lambda: self.app.Documents.Open(str(path), False))
        _retry(lambda: doc.Activate())
        return doc

    def close(self, doc, discard: bool = False) -> None:
        if not bool(_retry(lambda: doc.Saved)) and not discard:
            raise AgentCADError("AUTOCAD_UNSAVED_CHANGES", f"{_retry(lambda: doc.Name)} has unsaved edits in AutoCAD",
                                category="policy", hint="Bring them in with autocad_live action='pull', or pass "
                                                        "discard=true to throw them away")
        _retry(lambda: doc.Close(False))

    def reload(self, path: Path, discard: bool = False) -> dict[str, Any]:
        doc = self.find(path)
        if doc is None:
            return {"reloaded": False, "open_in_autocad": False}
        view = self.view(doc)
        self.close(doc, discard)
        self.open(path)
        self.set_view(view)
        return {"reloaded": True, "open_in_autocad": True, "view_kept": view is not None}

    def save_copy(self, path: Path, tmp: Path) -> tuple[Any, Any, bool]:
        """Save the open drawing (with the user's edits) as DXF ``tmp``. AutoCAD renames the document to ``tmp``;
        the caller closes it and re-opens ``path`` once the edits are committed. Also returns the view and
        whether the document had unsaved edits."""
        doc = self.find(path)
        if doc is None:
            raise AgentCADError("NOT_OPEN_IN_AUTOCAD", f"{path.name} is not open in AutoCAD", category="input",
                                hint="autocad_live action='open' first")
        view = self.view(doc)
        dirty = not bool(_retry(lambda: doc.Saved))
        tmp.parent.mkdir(parents=True, exist_ok=True)
        _retry(lambda: doc.SaveAs(str(tmp), AC2018_DXF))
        return doc, view, dirty

    def zoom(self, path: Path, window: tuple[tuple[float, float], tuple[float, float]] | None) -> None:
        self.open(path)
        if window is None:
            _retry(lambda: self.app.ZoomExtents())
        else:
            (x0, y0), (x1, y1) = window
            _retry(lambda: self.app.ZoomWindow(_point((x0, y0, 0)), _point((x1, y1, 0))))

    def command(self, path: Path, text: str, wait: float = 60.0) -> bool:
        """Send a command line; returns whether AutoCAD went idle again within ``wait`` seconds (SendCommand
        returns before the command has finished, and a pull right after it would race the command)."""
        doc = self.open(path)
        line = text if text.endswith(("\n", " ")) else text + "\n"
        _retry(lambda: doc.SendCommand(line))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                if _retry(lambda: self.app.GetAcadState().IsQuiescent, seconds=5):
                    return True
            except AgentCADError:
                pass
            time.sleep(0.2)
        return False
