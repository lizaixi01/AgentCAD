"""Deterministic internal worker fixture, like the pinned reference's _async probe.

This is the sole adapter fixture that imports product code. It exercises the
same worker used by every MCP call; no sleep/hold capability is exposed to users.
"""

import asyncio
import contextlib
import json
from pathlib import Path
import sys
import threading

from agentcad.mcp_server import build_server
from agentcad.policy import Policy


async def probe(root):
    server = build_server(Policy(root=Path(root)), profile="full")
    entered, release = threading.Event(), threading.Event()
    trace = []

    def held():
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Worker release did not arrive")
        trace.append("A:end")

    try:
        first = asyncio.create_task(server.worker.run(held))
        assert await asyncio.to_thread(entered.wait, 10)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        second = asyncio.create_task(server.worker.run(lambda: trace.append("B:run")))
        await asyncio.sleep(0.3)
        overlapped = "B:run" in trace
        release.set()
        await asyncio.wait_for(second, 10)
        await server.call_tool("create_drawing", {"path": "cancel_safety.dxf"})
        result = await server.call_tool(
            "apply_operations",
            {
                "path": "cancel_safety.dxf",
                "operations": [{"op": "add_line", "start": [0, 0], "end": [10, 0]}],
            },
        )
        payload = result[1] if isinstance(result, tuple) else json.loads(result[0].text)
        print(json.dumps({"trace": trace, "overlapped": overlapped, "healthy": payload["ok"]}))
    finally:
        release.set()
        server.worker.close()


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1]))
