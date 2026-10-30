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
        refuse_legacy_marker(str(directory / "lock"))
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


def refuse_legacy_marker(shown: str) -> None:
    """A non-cooperating old writer can replace a marker after any PID check.

    No read/check/unlink sequence safely establishes exclusive ownership. Modern
    writers use the OS lock above; legacy migration needs an offline decision.
    """
    raise _busy("An older AgentCAD's 'lock' marker exists; it is not safe to steal it",
                hint=f"Wait for the writer to finish. If {shown} remains, close all older AgentCAD "
                     "processes before manually deleting that marker and retrying")
