"""Real MCP stdio calls against best-cad-mcp (no AutoCAD; headless tools only)."""
import asyncio, json, os, sys, tempfile
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

PLAN = {"plan_id": "stdio", "units": "mm", "steps": [
    {"step_id": "s1", "op": "draw_circle", "args": {"center_x": 0, "center_y": 0, "radius": 5}}]}


async def run(profile):
    ws = tempfile.mkdtemp()
    params = StdioServerParameters(command=sys.executable, args=["/out/probes/run_server.py"], cwd=ws,
                                   env={"CAD_MCP_TOOL_PROFILE": profile, "CAD_MCP_WORKSPACE_ROOT": ws,
                                        "CAD_MCP_LOG_PATH": ws + "/cad_mcp.log", "PATH": os.environ["PATH"]})
    out = {"profile": profile}
    async with Client(stdio_client(params), read_timeout_seconds=60) as c:
        tools = await c.list_tools()
        names = sorted(t.name for t in tools.tools)
        out["protocol"] = c.protocol_version
        out["tool_count"] = len(names)
        out["send_command_exposed"] = "send_command" in names
        out["execute_cad_plan_exposed"] = "execute_cad_plan" in names
        def txt(r):
            return {"isError": getattr(r, "is_error", getattr(r, "isError", None)),
                    "structured": json.dumps(getattr(r, "structured_content", None) or getattr(r, "structuredContent", None), ensure_ascii=False, default=str)[:400]}
        out["validate_cad_plan"] = txt(await c.call_tool("validate_cad_plan", {"plan": PLAN}))
        out["execute_without_allow"] = txt(await c.call_tool("execute_cad_plan", {"plan": PLAN}))
        out["execute_query_insert"] = txt(await c.call_tool("execute_query", {"query": "INSERT INTO cad_entities(handle) VALUES('x')"}))
        out["open_drawing_dxf"] = txt(await c.call_tool("open_drawing", {"filepath": "/tmp/a.dxf"}))
        out["draw_line_no_autocad"] = txt(await c.call_tool("draw_line", {"start_x": 0, "start_y": 0, "end_x": 1, "end_y": 0}))
    return out


async def main():
    res = []
    for p in ("lean", "core", "full"):
        try:
            res.append(await asyncio.wait_for(run(p), 120))
        except Exception as exc:
            res.append({"profile": p, "error": repr(exc)[:500]})
    print(json.dumps(res, ensure_ascii=False, indent=1))

asyncio.run(main())
