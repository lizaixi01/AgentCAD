"""Probe helpers (written by the reviewer, not part of the product).

install_win32com_stub(): server.py imports win32com at module load. On Linux it cannot be installed.
The stub's Dispatch() raises, i.e. it behaves like a machine without AutoCAD. It does NOT emulate
AutoCAD, so no COM drawing behaviour is claimed from these probes.

StubBridge: a TCP server on 127.0.0.1:8765 speaking freecad_linux/bridge.py's JSON-line protocol.
It returns exactly what bridge.py returns in headless mode for the commands used (set_color() is
False headless, so highlight/query_highlight colour nothing). FreeCAD itself is not run.
"""
import json
import socket
import sys
import threading
import types


def install_win32com_stub():
    def Dispatch(name):
        raise Exception("COM unavailable (reviewer stub: no AutoCAD on Linux)")

    client = types.ModuleType("win32com.client")
    client.Dispatch = Dispatch
    client.VARIANT = lambda *a, **k: None
    client.pythoncom = types.SimpleNamespace(VT_ARRAY=0x2000, VT_R8=5)
    pkg = types.ModuleType("win32com")
    pkg.client = client
    sys.modules["win32com"] = pkg
    sys.modules["win32com.client"] = client


class StubBridge:
    def __init__(self, texts):
        self.texts = texts  # list of (name, text) annotations in the "document"
        self.calls = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 8765))
        self.srv.listen(5)
        threading.Thread(target=self._loop, daemon=True).start()

    def _reply(self, cmd, params):
        if cmd == "count_text":
            p = params.get("pattern", "")
            return json.dumps([{"name": n, "text": t, "layer": "0"} for n, t in self.texts if p in t])
        if cmd == "highlight_text_matches":
            return "已高亮 0 个文本"  # bridge.py: n counts only set_color()==True; headless -> 0
        if cmd == "query_highlight":
            return "已高亮 0 个实体"  # same rule in bridge.py cmd_query_highlight
        if cmd == "highlight":
            return "headless: 无视图对象（无头模式不显示颜色）"
        raise ValueError("stub: command not emulated: %s" % cmd)

    def _loop(self):
        while True:
            conn, _ = self.srv.accept()
            with conn, conn.makefile("r") as f:
                for line in f:
                    req = json.loads(line)
                    self.calls.append(req)
                    try:
                        resp = {"id": req["id"], "ok": True, "result": self._reply(req["cmd"], req.get("params", {}))}
                    except ValueError as e:
                        resp = {"id": req["id"], "ok": False, "error": str(e)}
                    conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode())
