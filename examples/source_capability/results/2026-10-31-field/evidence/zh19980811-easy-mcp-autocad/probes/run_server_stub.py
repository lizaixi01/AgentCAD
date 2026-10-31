"""Launch server.py over stdio with the reviewer's win32com stub (Dispatch raises: no AutoCAD)."""
import runpy, sys
sys.path.insert(0, "/out/probes")
from stubs import install_win32com_stub
install_win32com_stub()
runpy.run_path("/work/server.py", run_name="__main__")
