"""Plot the paper-space layout "A3" of DXF files to PNG with AutoCAD (for reviewing H6); restores the
"Previous plot settings" registry tree it touches.

    python examples/trials/render_layout_png.py out_dir a.dxf b.dxf ...
"""
import shutil, sys, winreg
from pathlib import Path
T = Path(__file__).resolve().parent
sys.path[:0] = [str(T), str(T.parents[1] / "research" / "autocad")]
from acad import run_lisp
from render_png import PREV_PLOT, _save_key, _restore_key
PARENT = PREV_PLOT.rsplit("\\", 1)[0]

def subkeys():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PARENT) as k:
            out, i = [], 0
            while True:
                try: out.append(winreg.EnumKey(k, i))
                except OSError: return out
                i += 1
    except FileNotFoundError:
        return []

LISP = ('(command "_.DXFIN" "%DIR%/in.dxf")\n'
        '(setvar "CTAB" "A3")\n'
        '(command "_.-PLOT" "_Y" "A3" "PublishToWeb PNG.pc3" "" "_L" "_N" "_E" "_F" "_C" "_Y" "monochrome.ctb"'
        ' "_Y" "_N" "_N" "_N" "%DIR%/out.png" "_N" "_Y")\n'
        '(out "png" (if (findfile "%DIR%/out.png") 1 0))\n')

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
for a in sys.argv[2:]:
    dxf = Path(a)
    before = subkeys(); saved = {k: _save_key(PARENT + "\\" + k) for k in before}
    try:
        r = run_lisp("lay_" + dxf.parent.name, LISP, files={"in.dxf": dxf}, timeout=240)
    finally:
        for k in subkeys():
            if k not in before:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PARENT + "\\" + k)
        for k, v in saved.items():
            _restore_key(PARENT + "\\" + k, v)
    png = r.dir / "out.png"
    if png.is_file():
        shutil.copyfile(png, out / f"{dxf.parent.parent.name}_{dxf.parent.name}.png"); print(a, "ok")
    else:
        print(a, "no png", r)

