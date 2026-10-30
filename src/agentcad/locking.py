"""Nonblocking OS write locks, released on process exit rather than by age."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from .errors import AgentCADError


def _busy(message: str, hint: str = "Wait for the writer to finish") -> AgentCADError:
    return AgentCADError("DRAWING_LOCKED", message, category="policy", retryable=True, hint=hint)


@contextmanager
def drawing_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    # Never guess that a pre-upgrade runtime has died based only on elapsed time.
    if (directory / "lock").exists():
        raise _busy("An older AgentCAD's 'lock' marker exists; it is not safe to steal it",
                    hint="Retry shortly. If the marker stays, call recover: it removes the marker once the "
                         "process it names has exited")
    # Keep the inode: unlinking after unlock can split locks between two files on POSIX.
    with (directory / "write.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise _busy("Another process is modifying this drawing") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def remove_legacy_marker(directory: Path, shown: str) -> int:
    """Delete an older AgentCAD's 'lock' marker once the writer whose PID it holds has exited; return that PID.
    ``shown``: the marker's path as the caller reports it."""
    marker = directory / "lock"
    try:
        pid = int(marker.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if not 0 < pid < 2**31:
        raise AgentCADError("DRAWING_LOCKED", f"{shown} names no process, so its writer cannot be confirmed gone",
                            category="policy", retryable=False,
                            hint=f"Delete {shown} by hand once no older AgentCAD is writing this drawing")
    if _running(pid):
        raise _busy(f"{shown} belongs to process {pid}, which is still running",
                    hint="Wait for that writer to finish, then call recover again")
    marker.unlink(missing_ok=True)
    return pid


def _running(pid: int) -> bool:
    """Whether process ``pid`` exists; True when that cannot be ruled out."""
    if os.name == "nt":  # os.kill would terminate the process on Windows
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process
        try:
            code = wintypes.DWORD()
            return not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # e.g. another user's process
        return True
    return True
