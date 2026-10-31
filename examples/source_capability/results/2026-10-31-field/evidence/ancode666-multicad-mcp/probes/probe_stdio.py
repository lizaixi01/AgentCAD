"""Reviewer probe: start the product's src/server.py as a real stdio MCP subprocess and call it.

run_server_stub.py installs win32shim (pywin32 stubs; no CAD) and then runs src/server.py as
__main__, so the product's own transport auto-detection (stdin not a TTY -> stdio) is used.
"""
import asyncio
import json
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main():
    t = StdioTransport(command="python", args=["/out/probes/run_server_stub.py"], cwd="/work")
    out = {}
    async with Client(t) as c:
        tools = await c.list_tools()
        out["tools"] = sorted(x.name for x in tools)
        r = await c.call_tool("manage_session", {"operations": json.dumps([{"action": "list_supported"}])},
                              raise_on_error=False)
        out["list_supported"] = r.content[0].text if r.content else None
        r = await c.call_tool("draw_entities", {"entities": "line|0,0|1,1"}, raise_on_error=False)
        out["draw_without_cad"] = {"is_error": r.is_error, "text": (r.content[0].text if r.content else "")[:300]}
    print(json.dumps(out, indent=2))
    with open("/out/probe_stdio.json", "w") as f:
        json.dump(out, f, indent=2)


asyncio.run(main())
