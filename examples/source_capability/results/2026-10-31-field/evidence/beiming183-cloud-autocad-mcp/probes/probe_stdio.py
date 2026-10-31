"""Start the pinned AutoCAD-MCP server over stdio (ezdxf backend) and make real tool calls."""
import asyncio
import json
import os
import sys

import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT = os.environ.get("PROBE_OUT", "/tmp/probe")
ROOT = os.path.join(OUT, "stdio_ws")
RESULTS = []


def rec(pid, item, passed, detail):
    row = {"probe": pid, "item": item, "result": "pass" if passed else "fail", "detail": detail}
    RESULTS.append(row)
    print(json.dumps(row, default=str)[:1500])


def parse(res):
    text = "".join(getattr(c, "text", "") for c in res.content)
    try:
        body = json.loads(text)
    except Exception:
        body = {"raw": text[:500]}
    return bool(res.isError), body


async def main():
    env = dict(os.environ, AUTOCAD_MCP_BACKEND="ezdxf", AUTOCAD_MCP_OUTPUT_ROOT=ROOT)
    params = StdioServerParameters(command=sys.executable, args=["-m", "autocad_mcp"], env=env, cwd="/work")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            rec("MCP-list-tools", "B1", len(tools) == 12, {"tools": tools})

            err, st = parse(await s.call_tool("system", {"operation": "status"}))
            rec("MCP-status", "B1", not err, {"backend": (st.get("payload") or st).get("backend") if isinstance(st, dict) else st,
                                               "keys": list(st.keys())[:12] if isinstance(st, dict) else None})

            err, cr = parse(await s.call_tool("drawing", {"operation": "create", "data": {"name": "stdio_probe"}}))
            rec("MCP-create", "F4", not err, cr)
            err, ctx = parse(await s.call_tool("drawing", {"operation": "context"}))
            payload = ctx.get("payload", ctx) if isinstance(ctx, dict) else {}
            doc_id = payload.get("doc_id") or (payload.get("document") or {}).get("doc_id")
            rev = payload.get("revision", (payload.get("document") or {}).get("revision"))
            rec("MCP-context", "C1", bool(doc_id is not None and rev is not None), {"doc_id": doc_id, "revision": rev, "raw_keys": list(payload)[:15]})

            err, ln = parse(await s.call_tool("entity", {"operation": "create_line", "doc_id": doc_id, "expected_revision": rev,
                                                         "idempotency_key": "probe-line-1",
                                                         "x1": 0, "y1": 0, "x2": 50, "y2": 0}))
            rec("MCP-create-line", "F1", not err, ln)

            err, stale = parse(await s.call_tool("entity", {"operation": "create_line", "doc_id": doc_id, "expected_revision": rev,
                                                            "idempotency_key": "probe-line-2",
                                                            "x1": 0, "y1": 0, "x2": 0, "y2": 50}))
            rec("MCP-stale-revision-rejected", "C1", err, stale)

            err, ctx2 = parse(await s.call_tool("drawing", {"operation": "context"}))
            p2 = ctx2.get("payload", ctx2)
            rev2 = p2.get("revision")
            err, ml = parse(await s.call_tool("entity", {"operation": "create_line", "doc_id": doc_id, "expected_revision": rev2,
                                                         "idempotency_key": "probe-line-3", "layer": "NOPE",
                                                         "x1": 0, "y1": 0, "x2": 0, "y2": 50}))
            rec("MCP-missing-layer", "C1", err, ml)

            err, lisp = parse(await s.call_tool("system", {"operation": "execute_lisp", "data": {"code": "(princ)"}}))
            rec("MCP-execute-lisp-refused", "S1", err, lisp)

            err, ctx3 = parse(await s.call_tool("drawing", {"operation": "context"}))
            rev3 = ctx3.get("payload", ctx3).get("revision")
            err, neg = parse(await s.call_tool("entity", {"operation": "create_circle", "doc_id": doc_id, "expected_revision": rev3,
                                                          "idempotency_key": "probe-neg-circle",
                                                          "data": {"cx": 0, "cy": 0, "radius": -5}}))
            rec("MCP-negative-radius-rejected", "F1", err, neg)
            err, ctx3 = parse(await s.call_tool("drawing", {"operation": "context"}))
            rev3 = ctx3.get("payload", ctx3).get("revision")
            err, sv = parse(await s.call_tool("drawing", {"operation": "save", "data": {"path": "/etc/escape_probe.dxf",
                                                                                      "doc_id": doc_id, "expected_revision": rev3}}))
            sp = (sv.get("payload") or {}) if isinstance(sv, dict) else {}
            saved = sp.get("path") or sp.get("actual_path")
            rec("MCP-save-contained", "S1", (not err) and saved and str(saved).startswith(ROOT) and not os.path.exists("/etc/escape_probe.dxf"),
                {"saved_path": saved, "payload": sp or sv})
            if saved and os.path.exists(saved):
                lines = [e for e in ezdxf.readfile(saved).modelspace() if e.dxftype() == "LINE"]
                rec("MCP-save-reopen", "F1", len(lines) == 1 and list(lines[0].dxf.end)[:2] == [50.0, 0.0],
                    {"lines": [[list(l.dxf.start)[:2], list(l.dxf.end)[:2]] for l in lines]})

            err, au = parse(await s.call_tool("drawing", {"operation": "audit"}))
            rec("MCP-audit", "C2", not err, {"keys": list((au.get("payload") or au).keys())[:20] if isinstance(au, dict) else None})

            err, ctx4 = parse(await s.call_tool("drawing", {"operation": "context"}))
            rev4 = ctx4.get("payload", ctx4).get("revision")
            err, dl = parse(await s.call_tool("drawing", {"operation": "deliver", "data": {"name": "probe", "doc_id": doc_id,
                                                                                         "expected_revision": rev4}}))
            rec("MCP-deliver-headless", "C3", not err, dl)

            err, bad = parse(await s.call_tool("entity", {"operation": "get", "entity_id": "ZZZZ"}))
            rec("MCP-bad-handle", "F1", err, bad)
    with open(os.path.join(OUT, "probe_stdio_results.json"), "w") as f:
        json.dump(RESULTS, f, indent=1, default=str)


asyncio.run(main())
