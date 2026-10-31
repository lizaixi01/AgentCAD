"""Reviewer shim (not part of the product): lets the Windows-only package import on Linux.

Injects MagicMock stand-ins for pywin32 modules and imports the product's packages with
sys.platform temporarily set to "win32", then restores it. Nothing here talks to a CAD
application; any COM call lands on a MagicMock. Loaded with `-p win32shim` or imported first.
"""
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(0, "/work/src")


class _VARIANT:
    def __init__(self, vt, value):
        self.vt, self.value = vt, value


def install():
    if "win32com" in sys.modules and getattr(sys.modules["win32com"], "_reviewer_stub", False):
        return
    win32com = types.ModuleType("win32com"); win32com._reviewer_stub = True
    client = MagicMock(name="win32com.client"); client.VARIANT = _VARIANT
    win32com.client = client
    pythoncom = MagicMock(name="pythoncom"); pythoncom.VT_ARRAY = 8192; pythoncom.VT_R8 = 5
    pythoncom.VT_I2 = 2; pythoncom.VT_VARIANT = 12; pythoncom.VT_DISPATCH = 9
    pywintypes = types.ModuleType("pywintypes")
    class com_error(Exception):
        pass
    pywintypes.com_error = com_error
    for name, mod in {"win32com": win32com, "win32com.client": client, "pythoncom": pythoncom,
                      "win32gui": MagicMock(name="win32gui"), "win32api": MagicMock(name="win32api"),
                      "win32con": MagicMock(name="win32con"), "pywintypes": pywintypes}.items():
        sys.modules[name] = mod
    # Import third-party deps on the real platform first; only the product's own modules
    # see the patched sys.platform.
    import sysconfig; sysconfig.get_config_vars()
    import zoneinfo, pydantic, pydantic_settings, mcp, mcp.server.fastmcp, fastmcp  # noqa: E401,F401
    import fastapi, uvicorn, openpyxl, PIL, asyncio, threading, ctypes  # noqa: E401,F401
    real = sys.platform
    sys.platform = "win32"
    try:
        import adapters  # noqa: F401
        import mcp_tools  # noqa: F401
        if "/work" not in sys.path:
            sys.path.insert(1, "/work")
        try:  # the repo's tests also import the package as `src.adapters`
            import src.adapters  # noqa: F401
            import src.mcp_tools  # noqa: F401
        except ImportError:
            pass
    finally:
        sys.platform = real


install()


def pytest_configure(config):  # pytest plugin hook
    install()
