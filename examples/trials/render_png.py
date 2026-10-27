"""Render DXF files to PNG with AutoCAD itself (accoreconsole -PLOT to PublishToWeb PNG), for visual review.

    python examples/trials/render_png.py out_dir a.dxf b.dxf ...

LibreOffice drops MTEXT (all dimension values), so it cannot show annotation problems; AutoCAD's own plot can.
The plot uses the drawing extents, fit to 1600x1280 px, monochrome. No persistent AutoCAD setting is changed
(page setup changes are discarded with "_N").
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "autocad"))
from acad import run_lisp  # noqa: E402

LISP = ('(command "_.DXFIN" "%DIR%/in.dxf")\n'
        '(command "_.ZOOM" "_E")\n'
        '(command "_.-PLOT" "_Y" "Model" "PublishToWeb PNG.pc3" "" "_L" "_N" "_E" "_F" "_C" "_Y" "monochrome.ctb"'
        ' "_Y" "" "%DIR%/out.png" "_N" "_Y")\n'
        '(out "png" (if (findfile "%DIR%/out.png") 1 0))\n')


PREV_PLOT = r"Software\Autodesk\AutoCAD\R26.0\ACAD-A101:804\Profiles\<<未命名配置>>\Previous plot settings\Model"


def _save_key(path: str):
    """AutoCAD writes the last plot device/scale to the user's profile on every PLOT, even when the page setup
    is not saved. Snapshot that key so the render leaves the user's 'previous plot' settings as they were."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            vals, i = [], 0
            while True:
                try:
                    vals.append(winreg.EnumValue(k, i))
                except OSError:
                    return vals
                i += 1
    except FileNotFoundError:
        return None


def _restore_key(path: str, vals) -> None:
    import winreg
    if vals is None:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        for name, data, typ in vals:
            winreg.SetValueEx(k, name, 0, typ, data)


def render(dxf: Path, out_dir: Path) -> Path | None:
    saved = _save_key(PREV_PLOT)
    try:
        r = run_lisp("render_" + dxf.parent.name + "_" + dxf.stem, LISP, files={"in.dxf": dxf}, timeout=240)
    finally:
        _restore_key(PREV_PLOT, saved)
    png = r.dir / "out.png"
    if not png.is_file():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{dxf.parent.name}__{dxf.stem}.png"
    shutil.copyfile(png, dest)
    shutil.rmtree(r.dir, ignore_errors=True)
    return dest


if __name__ == "__main__":
    out = Path(sys.argv[1])
    for a in sys.argv[2:]:
        print(a, "->", render(Path(a), out))
