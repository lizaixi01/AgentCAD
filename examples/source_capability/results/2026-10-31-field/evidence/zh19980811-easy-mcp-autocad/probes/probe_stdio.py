"""Real MCP stdio interface check: start each server as a subprocess and call tools over stdio."""
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

R = {}

async def run(label, params, calls):
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            out = {"tool_count": len(tools), "calls": []}
            for name, args in calls:
                res = await s.call_tool(name, args)
                out["calls"].append({"tool": name, "isError": res.isError, "text": res.content[0].text[:200]})
            R[label] = out
            print(label, json.dumps(out, ensure_ascii=False)[:800])

async def main():
    await run("server_freecad_stdio",
              StdioServerParameters(command="python", args=["/work/freecad_linux/server_freecad.py"], cwd="/tmp/fc"),
              [("get_all_tables", {}), ("draw_circle", {"center_x": 0, "center_y": 0, "radius": 5}),
               ("execute_query", {"query": "SELECT count(*) AS n FROM cad_elements"})])
    await run("server_autocad_stdio_with_win32com_stub",
              StdioServerParameters(command="python", args=["/out/probes/run_server_stub.py"], cwd="/tmp/ac"),
              [("get_all_tables", {}), ("draw_circle", {"center_x": 0, "center_y": 0, "radius": 5}),
               ("move_entity", {"handle": "ZZ", "start_point": [0, 0, 0], "end_point": [1, 1, 0]})])
    json.dump(R, open("/out/probe_stdio.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

asyncio.run(main())
