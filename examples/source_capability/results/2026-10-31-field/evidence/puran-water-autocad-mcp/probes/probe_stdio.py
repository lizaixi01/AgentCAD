"""Interface check: start `python -m autocad_mcp` (ezdxf backend) over MCP stdio and make real tool calls."""
import asyncio, json, os
import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="/work/.venv/bin/python", args=["-m", "autocad_mcp"],
                                   env={**os.environ, "AUTOCAD_MCP_BACKEND": "ezdxf", "MPLCONFIGDIR": "/tmp/mpl"}, cwd="/work")
    out = {}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            out["tools"] = {t.name: (t.annotations.readOnlyHint if t.annotations else None) for t in tools.tools}
            async def call(name, args):
                res = await s.call_tool(name, args)
                return [c.text if c.type == "text" else f"<{c.type}>" for c in res.content]
            out["status"] = await call("system", {"operation": "status"})
            out["line"] = await call("entity", {"operation": "create_line", "x1": 0, "y1": 0, "x2": 3, "y2": 4})
            out["bad_get"] = await call("entity", {"operation": "get", "entity_id": "ZZZ"})
            out["exec_lisp"] = await call("system", {"operation": "execute_lisp", "data": {"code": "(+ 1 2)"}})
            out["save"] = await call("drawing", {"operation": "save", "data": {"path": "/out/probe_artifacts/stdio.dxf"}})
            out["shot"] = await call("view", {"operation": "get_screenshot"})
    doc = ezdxf.readfile("/out/probe_artifacts/stdio.dxf")
    out["reopened"] = [(e.dxftype(), list(e.dxf.end)[:2]) for e in doc.modelspace()]
    print(json.dumps(out, indent=1))
    json.dump(out, open("/out/probe_stdio_results.json", "w"), indent=1)
asyncio.run(main())
