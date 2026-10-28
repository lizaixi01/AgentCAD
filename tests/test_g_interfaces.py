"""Test G (protocol level): the same business logic through CLI, MCP (official
SDK stdio client spawning the real server process) and HTTP."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import anyio
import pytest

from conftest import PLATE_SPEC

PY = sys.executable


def cli(ws: Path, *args: str) -> tuple[int, dict]:
    p = subprocess.run([PY, "-m", "agentcad.cli", "--root", str(ws), "--compact", *args],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    return p.returncode, json.loads(p.stdout)


def test_cli_end_to_end(ws):
    (ws / "spec.json").write_text(json.dumps(PLATE_SPEC), "utf-8")
    code, r = cli(ws, "draw", "--spec", str(ws / "spec.json"), "--output", "plate.dxf")
    assert code == 0 and r["ok"] and r["validation"]["passed"]
    code, r = cli(ws, "inspect", "plate.dxf")
    assert code == 0 and r["units"] == "mm" and r["entity_types"]["CIRCLE"] == 4
    code, r = cli(ws, "entities", "plate.dxf", "--type", "CIRCLE", "--brief")
    assert code == 0 and r["total"] == 4
    (ws / "changes.json").write_text(json.dumps({"width": 120}), "utf-8")
    code, r = cli(ws, "revise", "plate.dxf", "--spec", str(ws / "changes.json"))
    assert code == 0 and r["validation"]["passed"]
    code, r = cli(ws, "diff", "plate.dxf")
    assert code == 0 and r["summary"]["modified"] == 10
    code, r = cli(ws, "validate", "plate.dxf")
    assert code == 0 and r["validation"]["passed"]
    # error path: exit code + typed error
    code, r = cli(ws, "apply", "plate.dxf", "--ops", '[{"op": "add_circle", "center": [0, 0], "radius": -1}]')
    assert code == 2 and r["error"]["code"] == "OUT_OF_RANGE" and r["error"]["op_index"] == 0
    code, r = cli(ws, "validate", "plate.dxf", "--requirements", '[{"type": "outline", "width": 100, "height": 60, "layer": "OUTLINE"}]')
    assert code == 1 and not r["validation"]["passed"]
    code, r = cli(ws, "inspect", "../escape.dxf")
    assert code == 4 and r["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    code, r = cli(ws, "--read-only", "create", "x.dxf")
    assert code == 4 and r["error"]["code"] == "READ_ONLY"
    code, r = cli(ws, "rollback", "plate.dxf")
    assert code == 0
    code, r = cli(ws, "export", "plate.dxf", "plate.svg")
    assert code == 0 and (ws / "plate.svg").stat().st_size > 1000
    code, r = cli(ws, "ops")
    assert code == 0 and r["count"] >= 30


async def _mcp_session(ws: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {**os.environ, "AGENTCAD_ROOT": str(ws)}
    params = StdioServerParameters(command=PY, args=["-m", "agentcad.mcp_server"], env=env)
    out = {}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            out["tools"] = {t.name: t.inputSchema for t in tools.tools}

            async def call(name, **kw):
                res = await s.call_tool(name, kw)
                return json.loads(res.content[0].text)

            out["create"] = await call("create_drawing", path="m.dxf", units="mm")
            out["apply"] = await call("apply_operations", path="m.dxf", operations=[
                {"op": "add_rectangle", "corner": [0, 0], "width": 100, "height": 60, "layer": "OUTLINE", "tag": "o"},
                {"op": "add_circle", "center": [10, 10], "diameter": 8, "layer": "HOLES", "tag": "h1"}])
            out["read"] = await call("read_drawing", path="m.dxf")
            out["bad"] = await call("apply_operations", path="m.dxf", operations=[
                {"op": "add_circle", "center": [90, 10], "diameter": 8, "layer": "HOLES", "tag": "h1"}])
            # agent reacts to the structured error (TAG_EXISTS) and retries with a new tag
            out["fixed"] = await call("apply_operations", path="m.dxf", operations=[
                {"op": "add_circle", "center": [90, 10], "diameter": 8, "layer": "HOLES", "tag": "h2"}])
            out["validate"] = await call("validate_drawing", path="m.dxf", requirements=[
                {"type": "outline", "width": 100, "height": 60, "layer": "OUTLINE"},
                {"type": "hole", "center": [90, 10], "diameter": 8}])
            out["diff"] = await call("get_diff", path="m.dxf")
            out["rollback"] = await call("rollback", path="m.dxf")
            out["spec"] = await call("draw_from_spec", spec=PLATE_SPEC, output="p.dxf")
            out["metrics"] = await call("get_metrics")
    return out


def test_mcp_stdio_with_official_client(ws):
    out = anyio.run(_mcp_session, ws)
    required = {"create_drawing", "read_drawing", "inspect_entities", "apply_operations", "apply_constraints",
                "validate_drawing", "revise_from_document", "get_diff", "rollback", "export_drawing"}
    assert required <= set(out["tools"])
    ap = out["tools"]["apply_operations"]
    assert ap["properties"]["operations"]["type"] == "array" and "path" in ap["required"]
    assert out["create"]["ok"] and out["apply"]["ok"] and len(out["apply"]["changes"]["added"]) == 2
    assert out["read"]["entity_types"] == {"LWPOLYLINE": 1, "CIRCLE": 1}
    assert not out["bad"]["ok"] and out["bad"]["error"]["code"] == "TAG_EXISTS"
    assert out["fixed"]["ok"]
    assert out["validate"]["validation"]["passed"]
    assert out["diff"]["summary"]["added"] == 1
    assert out["rollback"]["ok"]
    assert out["spec"]["ok"] and out["spec"]["validation"]["passed"]
    assert out["metrics"]["tool_calls"] == 9 and out["metrics"]["model_calls"] == 0


def test_http_api(ws):
    from http.server import ThreadingHTTPServer
    from agentcad.http_api import make_handler
    from agentcad.policy import Policy
    from agentcad.service import Runtime
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Runtime(Policy(root=ws))))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def post(tool, body):
        req = urllib.request.Request(f"{base}/{tool}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    try:
        assert post("draw_from_spec", {"spec": PLATE_SPEC, "output": "h.dxf"})["validation"]["passed"]
        assert post("read_drawing", {"path": "h.dxf"})["entity_types"]["CIRCLE"] == 4
        r = post("apply_operations", {"path": "h.dxf", "operations": [{"op": "nope"}]})
        assert r["error"]["code"] == "UNKNOWN_OP"
        with urllib.request.urlopen(f"{base}/tools", timeout=10) as resp:
            assert "apply_operations" in json.loads(resp.read())["tools"]
    finally:
        srv.shutdown()


def test_interfaces_share_one_implementation():
    """CLI / MCP / HTTP contain no CAD logic: they only call Runtime methods."""
    src = Path(__file__).parents[1] / "src" / "agentcad"
    for adapter in ("cli.py", "mcp_server.py", "http_api.py"):
        text = (src / adapter).read_text("utf-8")
        assert "import ezdxf" not in text and "from ezdxf" not in text
        assert "from .ops" not in text and "engine" not in text


def test_operation_catalog_is_compact_by_default(tmp_path):
    """The full catalog (~90K chars) is over Claude Code's tool-result limit: 34 of 36 Claude Code sessions failed
    their first list_operations call. The default is an index; schemas come per op or per category."""
    from agentcad.ops import REGISTRY
    from agentcad.policy import Policy
    from agentcad.service import Runtime
    rt = Runtime(Policy(root=tmp_path))
    r = rt.list_operations()
    assert r["ok"] and not r["detail"] and r["count"] == len(REGISTRY)
    assert len(json.dumps(r, ensure_ascii=False)) < 20000
    circle = next(o for o in r["operations"] if o["op"] == "add_circle")
    assert circle["category"] == "draw" and "center*" in circle["params"] and circle["draw_params"]
    assert set(r["common_params"]["meaning"]) >= {"layout", "layer", "tag"}
    s = rt.list_operations(ops=["add_circle", "add_viewport"])
    assert [o["op"] for o in s["operations"]] == ["add_circle", "add_viewport"]
    assert "properties" in s["operations"][0]["params"]
    assert {o["category"] for o in rt.list_operations(category="layout")["operations"]} == {"layout"}
    assert rt.list_operations(detail=True)["count"] == len(REGISTRY)
    assert rt.list_operations(ops=["no_such_op"])["error"]["code"] == "UNKNOWN_OPERATION"
    assert rt.list_operations(category="nope")["error"]["code"] == "UNKNOWN_CATEGORY"
