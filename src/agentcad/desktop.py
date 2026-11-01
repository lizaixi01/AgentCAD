"""Show a folder, or a file inside its folder, in the computer's file manager: the viewer's "Show in folder" and the
setup wizard's "Open my drawings folder". Fixed programs only, never a shell, and only paths the caller has already
checked (the viewer allows only its own workspace)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_folder(path: Path) -> None:
    """Open ``path`` (a folder; created if missing) in Explorer / Finder / the desktop's file manager."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)], shell=False)


def reveal(path: Path) -> None:
    """Open the folder holding ``path`` with that file selected (Linux: just the folder; no common way to select)."""
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", "/select,", str(path)], shell=False)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)], shell=False)
    else:
        subprocess.Popen(["xdg-open", str(path.parent)], shell=False)
