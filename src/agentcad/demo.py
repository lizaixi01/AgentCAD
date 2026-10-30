"""A live demo to show people: ``agentcad demo`` opens the live viewer and draws a mounting plate step by step, then
revises it, the way an assistant would. Nothing to set up, no AI needed; the drawing goes to a folder of its own.

The desktop icon "AgentCAD Demo" ("AgentCAD 演示" on a Chinese system) runs it: ``agentcad demo --shortcut`` and
the setup wizard put it there (install.create_shortcut).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .policy import Policy

MARKER = ".agentcad-demo"  # only a folder holding this file is ever cleared

# (pause before, label, operations): the steps a person watches
STEPS: list[tuple[float, str, list[dict[str, Any]]]] = [
    (1.5, "outline", [
        {"op": "add_rectangle", "corner": [0, 0], "width": 200, "height": 100, "corner_radius": 8,
         "layer": "OUTLINE", "tag": "outline"}]),
    (3.0, "holes", [
        {"op": "add_circle", "center": [15, 15], "diameter": 12, "layer": "HOLES", "tag": "h1"},
        {"op": "add_circle", "center": [185, 15], "diameter": 12, "layer": "HOLES", "tag": "h2"},
        {"op": "add_circle", "center": [15, 85], "diameter": 12, "layer": "HOLES", "tag": "h3"},
        {"op": "add_circle", "center": [185, 85], "diameter": 12, "layer": "HOLES", "tag": "h4"},
        {"op": "add_circle", "center": [100, 50], "diameter": 40, "layer": "HOLES", "tag": "bore"},
        {"op": "add_center_mark", "target": "tag:bore", "layer": "CENTER"}]),
    (3.0, "dimensions", [
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [200, 0], "offset": -14, "layer": "DIM"},
        {"op": "add_linear_dim", "p1": [0, 0], "p2": [0, 100], "orientation": "vertical", "offset": -14,
         "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "tag:bore", "angle": 30, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "tag:h4", "angle": 45, "layer": "DIM"},
        {"op": "add_text", "text": "MOUNTING PLATE", "insert": [0, -32], "height": 5, "layer": "TEXT"}]),
    (4.0, "wider", [  # a revision: 240 wide, holes still 15 from the edges, bore centred
        {"op": "stretch", "window": [[150, -60], [260, 160]], "delta": [40, 0]},
        {"op": "move", "target": "tag:bore", "delta": [20, 0]}]),
]


def demo_root(workspace: Path) -> Path:
    """<workspace>/demo, e.g. C:\\Users\\<you>\\AgentCAD\\demo."""
    return workspace / "demo"


def prepare(root: Path) -> None:
    """An empty demo folder. A folder that exists without the marker is somebody's: refuse to touch it."""
    if root.exists() and any(root.iterdir()):
        if not (root / MARKER).is_file():
            raise FileExistsError(f"{root} exists and was not made by 'agentcad demo'; not touching it")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("made by 'agentcad demo'; it clears this folder each run\n", "utf-8")


def draw(root: Path, pause: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Make plate.dxf in ``root`` step by step; ``pause`` scales the waits between steps (0: no waiting)."""
    from .service import Runtime
    rt = Runtime(Policy(root=root))
    results = [rt.create_drawing("plate.dxf", "mm", overwrite=True)]
    for wait, label, ops in STEPS:
        sleep(wait * pause)
        r = rt.apply_operations("plate.dxf", ops, label=label)
        results.append(r)
        if not r["ok"]:
            break
    return results


def run(workspace: Path, *, open_browser: bool = True, linger: float = 1800.0) -> int:
    """The whole demo: viewer up and open, then draw, then keep the viewer up for ``linger`` seconds."""
    from .viewer import Viewer
    root = demo_root(workspace)
    prepare(root)
    view = None
    for port in [*range(8780, 8790), 0]:
        try:
            view = Viewer(Policy(root=root), port=port).start()
            break
        except OSError:
            continue
    if view is None:
        print(json.dumps({"ok": False, "error": {"code": "PORT_IN_USE", "message": "No free port"}}), flush=True)
        return 2
    print(json.dumps({"ok": True, "viewer": view.url, "root": str(root)}), flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(view.url)
        time.sleep(3)  # let the page load before the first change
    try:
        results = draw(root)
        ok = all(r["ok"] for r in results)
        print(json.dumps({"ok": ok, "steps": len(results)}), flush=True)
        time.sleep(linger)  # people look around; closing the window ends it
    except KeyboardInterrupt:
        pass
    finally:
        view.stop()
    return 0
