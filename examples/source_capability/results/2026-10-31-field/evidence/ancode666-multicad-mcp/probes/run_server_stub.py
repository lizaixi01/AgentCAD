"""Reviewer launcher: pywin32 stubs (no CAD, GetActiveObject raises), then run src/server.py as __main__."""
import runpy
import sys

sys.path.insert(0, "/out/probes")
import win32shim  # noqa: E402,F401


def _no_cad(*a, **k):
    raise sys.modules["pywintypes"].com_error("Operation unavailable (reviewer stub: no CAD on Linux)")


for n in ("GetActiveObject", "Dispatch", "GetObject", "DispatchEx"):
    setattr(sys.modules["win32com.client"], n, _no_cad)

real = sys.platform
sys.platform = "win32"
try:
    import server  # noqa: F401  (module import registers tools)
finally:
    sys.platform = real
runpy.run_path("/work/src/server.py", run_name="__main__")
