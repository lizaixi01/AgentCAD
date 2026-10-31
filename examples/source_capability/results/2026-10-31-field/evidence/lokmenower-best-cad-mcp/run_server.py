"""Start best-cad-mcp's stdio server on Linux with the repo's own COM stubs (tests/conftest.py)."""
import sys
sys.path.insert(0, "/work")
sys.path.insert(0, "/work/tests")
import conftest  # noqa: F401  installs win32com/pythoncom stubs
from src.server import main
main()
