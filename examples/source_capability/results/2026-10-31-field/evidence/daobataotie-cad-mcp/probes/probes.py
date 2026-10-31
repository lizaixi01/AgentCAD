"""Reviewer probes for daobataotie/CAD-MCP @ daf7502 (run in an offline Linux container).

Calls the product's own FastMCP tools through FastMCP.call_tool (pydantic validation included).
The COM layer is replaced by probes/stubs (fakecad), so CAD-side results are interface evidence only.
Usage: python probes.py <mode>   mode = none | mem | faillayer
"""
import asyncio, json, os, sys

MODE = sys.argv[1]
os.environ["FAKECAD"] = "mem" if MODE in ("mem", "faillayer") else "none"
if MODE == "faillayer":
    os.environ["FAKE_FAIL_LAYER"] = "1"
sys.path.insert(0, "/out/probes/stubs")
sys.path.insert(0, "/work/src")
import logging
logging.disable(logging.CRITICAL)
import server  # noqa: E402  product module
import fakecad  # noqa: E402
logging.disable(logging.CRITICAL)

RESULTS = []


def rec(name, expect, ok, detail):
    RESULTS.append({"probe": name, "expect": expect, "result": "PASS" if ok else "FAIL", "detail": detail})


SESSION = None


async def call(tool, args):
    """Real MCP round trip over the SDK's in-memory transport (client <-> product server)."""
    r = await SESSION.call_tool(tool, args)
    if r.isError:
        return {"error": " ".join(getattr(c, "text", "") for c in r.content)[:300]}
    if r.structuredContent is not None:
        return {"structured": r.structuredContent}
    return {"content": [getattr(c, "text", type(c).__name__) for c in r.content]}


async def main():
    global SESSION
    from mcp.shared.memory import create_connected_server_and_client_session
    async with create_connected_server_and_client_session(server.mcp._mcp_server) as SESSION:
        try:
            await body()
        finally:
            print(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str))


async def body():
    if MODE == "none":
        r = await call("draw_line", {"start_point": [0, 0], "end_point": [10, 0]})
        s = r.get("structured", {})
        rec("no_cad.draw_line", "success=false with diagnosable reason, no crash",
            s.get("success") is False and "AutoCAD.Application" in s.get("message", ""), r)
        r = await call("save_drawing", {"file_path": "/out/tmp/x.dwg"})
        s = r.get("structured", {})
        rec("no_cad.save_drawing", "refuses without starting CAD, writes nothing",
            s.get("success") is False and not os.path.exists("/out/tmp/x.dwg"), r)
        r = await call("open_drawing", {"file_path": "/nonexistent/a.dwg"})
        rec("no_cad.open_missing", "success=false", r.get("structured", {}).get("success") is False, r)
        for tool, args in [("draw_circle", {"center": [0, 0], "radius": -1}),
                           ("draw_circle", {"center": [0, 0], "radius": 0}),
                           ("array_linear_entity", {"handle": "1", "count": 1, "displacement": [1, 0]}),
                           ("draw_hatch", {"points": [[0, 0], [1, 0]]}),
                           ("draw_line", {"start_point": [0], "end_point": [1, 1]})]:
            r = await call(tool, args)
            rec("validation." + tool + "." + json.dumps(args), "tool error before any CAD call", "error" in r, r)
        lst = (await SESSION.list_tools()).tools
        rec("list_tools", "35 tools with annotations", len(lst) == 35,
            {"count": len(lst), "destructive": sorted(t.name for t in lst if t.annotations and t.annotations.destructiveHint)})
        # NLP legacy parser is pure Python
        nlp = server.cad_service.nlp_processor
        cases = {"画一条从(0,0)到(100,100)的红色直线": "draw_line",
                 "画一个圆心在(50,50)半径为20的圆": "draw_circle",
                 "画一个矩形，从(0,0)到(10,5)": "draw_rectangle",
                 "draw a rectangle from (0,0) to (10,5)": "draw_rectangle(english)"}
        for text, want in cases.items():
            p = nlp.parse_command(text)
            rec("nlp.parse." + want, "command type " + want.split("(")[0], p.get("type") == want.split("(")[0], p)

    elif MODE == "mem":
        r = await call("draw_line", {"start_point": [0, 0], "end_point": [30, 40], "layer": "WALL", "color": "red"})
        h = (r.get("structured") or {}).get("entity_handles", [None])[0]
        rec("mem.draw_line", "success with handle", bool(h), r)
        r2 = await call("get_entity_properties", {"handle": h})
        s2 = r2.get("structured", {})
        rec("mem.readback_line", "layer WALL, color 1, endpoints passed through",
            s2.get("layer") == "WALL" and s2.get("color") == 1 and s2.get("properties", {}).get("end_point") == [30.0, 40.0, 0.0], r2)
        r = await call("move_entity", {"handle": "DEAD", "displacement": [1, 1]})
        rec("mem.move_bad_handle", "success=false", r.get("structured", {}).get("success") is False, r)
        r = await call("get_entity_properties", {"handle": "DEAD"})
        rec("mem.props_bad_handle", "success=false with error", r.get("structured", {}).get("success") is False, r)
        fakecad.CALLS.clear()
        r = await call("rotate_entity", {"handle": h, "base_point": [0, 0], "angle_degrees": 90})
        rot = [c for c in fakecad.CALLS if c[1] == "Rotate"]
        rec("mem.rotate_radians", "Rotate called with pi/2", bool(rot) and abs(rot[0][2][1] - 1.5707963) < 1e-6, {"r": r, "calls": rot})
        before = len(server.cad_service.controller.doc.ModelSpace._items)
        r = await call("array_linear_entity", {"handle": h, "count": 3, "displacement": [10, 0]})
        after = len(server.cad_service.controller.doc.ModelSpace._items)
        rec("mem.array_linear", "2 new entities", after - before == 2 and len(r["structured"]["entity_handles"]) == 2, r)
        # Defect D1: undo reports success without verifying anything changed
        n0 = len(server.cad_service.controller.doc.ModelSpace._items)
        fakecad.CALLS.clear()
        r = await call("undo", {})
        n1 = len(server.cad_service.controller.doc.ModelSpace._items)
        rec("defect.undo_false_success", "REPRODUCE: success=true although drawing unchanged",
            r["structured"]["success"] is True and n0 == n1,
            {"result": r, "entities_before": n0, "entities_after": n1, "calls": fakecad.CALLS})
        r = await call("redo", {})
        rec("defect.redo_false_success", "REPRODUCE: success=true with no verification", r["structured"]["success"] is True, r)
        # Defect D2: arbitrary command passthrough enabled by default
        fakecad.CALLS.clear()
        cmd = '(command "_.SHELL" "echo pwned")'
        r = await call("send_command", {"command": cmd})
        sent = [c for c in fakecad.CALLS if c[1] == "SendCommand"]
        rec("defect.send_command_unscoped", "REPRODUCE: LISP/SHELL text forwarded verbatim, success=true",
            r["structured"]["success"] is True and sent and sent[0][2][0].startswith(cmd), {"r": r, "sent": sent})
        # save: no file type passed, no readback
        fakecad.CALLS.clear()
        r = await call("save_drawing", {"file_path": "/out/tmp/sub/out.dxf"})
        sa = [c for c in fakecad.CALLS if c[1] == "SaveAs"]
        rec("save.dxf_no_type", "observe: SaveAs args; tool reports saved without checking the file",
            r["structured"]["success"] is True and len(sa[0][2]) == 1 and not os.path.exists("/out/tmp/sub/out.dxf"),
            {"r": r, "saveas_args": sa, "file_exists_after": os.path.exists("/out/tmp/sub/out.dxf")})
        # hatch with collinear/degenerate boundary still reported (no geometry validation)
        r = await call("draw_hatch", {"points": [[0, 0], [1, 0], [2, 0]]})
        rec("hatch.degenerate", "observe: collinear boundary accepted by the tool layer", True, r)

    elif MODE == "faillayer":
        before = 0
        r = await call("draw_line", {"start_point": [0, 0], "end_point": [5, 0], "layer": "WALL"})
        ents = await call("list_entities", {})
        total = ents["structured"]["total"]
        rec("defect.partial_write_on_failure", "REPRODUCE: tool reports failure but the line stays in the drawing",
            r["structured"]["success"] is False and total == before + 1,
            {"draw": r, "entities_total_after": total, "entities": ents["structured"]["entities"]})


asyncio.run(main())
