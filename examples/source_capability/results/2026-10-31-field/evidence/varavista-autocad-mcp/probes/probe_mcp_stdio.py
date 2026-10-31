"""Interface check: start the product's MCP server over stdio (auto backend on Linux)
and make real tool calls with the official mcp client. Saved file is reread with ezdxf."""
import asyncio, json, os, sys, tempfile
import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT = sys.argv[1] if len(sys.argv) > 1 else "/out/mcp_stdio_results.json"

def text(res):
    return " ".join(getattr(c, "text", "") for c in res.content)[:600]

async def main():
    W = tempfile.mkdtemp(prefix="mcp_")
    params = StdioServerParameters(command=sys.executable, args=["-m", "autocad_mcp"],
                                   env={**os.environ, "AUTOCAD_MCP_BACKEND": "auto", "AUTOCAD_MCP_ONLY_TEXT": "true"})
    log = []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            log.append({"call": "list_tools", "result": sorted(t.name for t in tools.tools)})
            calls = [
                ("system", {"operation": "status"}),
                ("entity", {"operation": "create_line", "x1": 0, "y1": 0, "x2": 3, "y2": 4}),
                ("entity", {"operation": "create_circle", "data": {"cx": 0, "cy": 0, "radius": 2}}),
                ("entity", {"operation": "count"}),
                ("geometry", {"operation": "distance", "data": {"x1": 0, "y1": 0, "x2": 3, "y2": 4}}),
                ("entity", {"operation": "move", "entity_id": "NOPE", "data": {"dx": 1, "dy": 1}}),
                ("entity", {"operation": "create_circle", "data": {"cx": 0}}),
                ("system", {"operation": "execute_lisp", "data": {"code": "(+ 1 2)"}}),
                ("drawing", {"operation": "save", "data": {"path": os.path.join(W, "m.dxf")}}),
            ]
            for name, args in calls:
                res = await s.call_tool(name, args)
                log.append({"call": name, "args": args, "isError": res.isError, "result": text(res)})
    d = ezdxf.readfile(os.path.join(W, "m.dxf"))
    log.append({"reopen": sorted(e.dxftype() for e in d.modelspace())})
    json.dump(log, open(OUT, "w"), indent=1, default=str)
    for x in log: print(json.dumps(x)[:400])

asyncio.run(main())
