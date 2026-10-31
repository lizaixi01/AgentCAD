"""Probes of freecad_linux/server_freecad.py (MCP layer). FreeCAD is not installable from pip, so
the bridge is either absent (error path) or a stub that returns bridge.py's headless replies."""
import asyncio, json, sqlite3, sys
sys.path.insert(0, "/work/freecad_linux")
sys.path.insert(0, "/out/probes")
import server_freecad as sf  # product module
from stubs import StubBridge

R = {}
def rec(k, v, ok):
    R[k] = {"result": v, "pass": ok}
    print(("PASS " if ok else "FAIL ") + k + ": " + json.dumps(v, ensure_ascii=False)[:300])

async def call(name, args):
    res = await sf.mcp.call_tool(name, args)
    return res[0].text

async def main():
    rec("tools_registered", sorted(t.name for t in await sf.mcp.list_tools()), True)
    # error path: bridge not running
    t = await call("draw_line", {"start_x": 0, "start_y": 0, "end_x": 1, "end_y": 0})
    rec("draw_line_bridge_down_reports_failure", t, t.startswith("创建直线失败") and "bridge" in t)
    t = await call("save_drawing", {"path": "/tmp/x"})
    rec("save_bridge_down_reports_failure", t, t.startswith("保存图纸失败"))
    # table-name validation (port)
    t = await call("get_table_schema", {"table_name": "x); DROP TABLE text_patterns; --"})
    rec("port_get_table_schema_rejects_bad_name", t, "非法表名" in t)
    # draw_device_connection with no CustomDevice rows
    t = await call("draw_device_connection", {"start_device": "P14", "end_device": "P02"})
    rec("device_connection_without_devices", t, "未找到" in t)
    # S1: destructive SQL
    t = await call("execute_query", {"query": "DELETE FROM text_patterns"})
    rec("DEFECT_port_execute_query_write_allowed", t, t.startswith("执行成功"))

    # C2 false success: stub bridge returns bridge.py's headless replies (nothing coloured)
    stub = StubBridge([("Text", "PMC-3M A"), ("Text001", "PMC-3M B"), ("Text002", "other")])
    t = await call("highlight_text_matches", {"pattern": "PMC-3M", "color": 1})
    bridge_said = [c for c in stub.calls if c["cmd"] == "highlight_text_matches"]
    rec("DEFECT_highlight_text_matches_reports_count_not_coloured", {"tool_reply": t, "bridge_reply": "已高亮 0 个文本"}, "2" in t)
    con = sqlite3.connect(sf.DB_FILE)
    con.execute("DELETE FROM cad_elements")
    con.execute("INSERT INTO cad_elements (handle,name,type,layer,properties) VALUES ('Line','Line','Part::Line','0','{}'),('Nope','x','Part::Line','0','{}')")
    con.commit()
    t = await call("query_and_highlight", {"sql_query": "SELECT handle FROM cad_elements"})
    rec("DEFECT_query_and_highlight_reports_len_handles", {"tool_reply": t, "bridge_reply": "已高亮 0 个实体", "note": "'Nope' is not an object; bridge colours nothing headless"}, "2" in t)
    t = await call("highlight_entity", {"handle": "Line"})
    rec("highlight_entity_headless_reply", t, True)
    t = await call("move_entity", {"handle": "Line", "start_point": [0, 0, 0], "end_point": [1, 0, 0]})
    rec("unemulated_bridge_error_propagates", t, t.startswith("移动实体失败"))
    json.dump(R, open("/out/probe_freecad_server.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

asyncio.run(main())
