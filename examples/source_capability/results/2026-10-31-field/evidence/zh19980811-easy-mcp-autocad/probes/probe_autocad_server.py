"""Probes of server.py (AutoCAD build) with COM unavailable. Run from a scratch cwd (autocad_data.db is cwd-relative)."""
import asyncio, json, sqlite3, sys
sys.path.insert(0, "/work")
sys.path.insert(0, "/out/probes")
from stubs import install_win32com_stub
install_win32com_stub()
import server  # product module

R = {}
def rec(k, v, ok):
    R[k] = {"result": v, "pass": ok}
    print(("PASS " if ok else "FAIL ") + k + ": " + json.dumps(v, ensure_ascii=False)[:300])

async def main():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    rec("tools_registered", sorted(tools), True)
    # duplicate draw_line: which definition is registered? First has 'Args:' docstring.
    rec("draw_line_registered_is_first_definition", "Args:" in (tools["draw_line"].description or ""), "Args:" in (tools["draw_line"].description or ""))

    # COM unavailable: error path for a drawing tool via the MCP layer
    res = await server.mcp.call_tool("draw_line", {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 0})
    txt = res[0].text if isinstance(res, list) else str(res)
    rec("draw_line_without_autocad_reports_failure_text", txt, txt.startswith("创建直线失败"))

    # get_all_tables ordinary
    res = await server.mcp.call_tool("get_all_tables", {})
    rec("get_all_tables", json.loads(res[0].text), set(json.loads(res[0].text)) >= {"cad_elements", "text_patterns"})

    # execute_query ordinary insert + select, independent readback with sqlite3
    await server.mcp.call_tool("execute_query", {"query": "INSERT INTO cad_elements (handle,name,type,layer,properties) VALUES ('A1','Line','AcDbLine','0','{}')"})
    rows = sqlite3.connect("autocad_data.db").execute("SELECT handle FROM cad_elements").fetchall()
    rec("execute_query_insert_readback", rows, rows == [("A1",)])

    # error case: bad SQL
    res = await server.mcp.call_tool("execute_query", {"query": "SELEC nonsense"})
    rec("execute_query_bad_sql_error_text", res[0].text, res[0].text.startswith("执行查询失败"))

    # get_table_schema with an unvalidated name: injection attempt
    res = await server.mcp.call_tool("get_table_schema", {"table_name": "cad_elements); DROP TABLE text_patterns; --"})
    tables = [r[0] for r in sqlite3.connect("autocad_data.db").execute("SELECT name FROM sqlite_master WHERE type='table'")]
    rec("get_table_schema_injection_multi_statement", {"reply": res[0].text[:200], "tables_after": tables}, "text_patterns" in tables)
    res = await server.mcp.call_tool("get_table_schema", {"table_name": "nonexistent_table"})
    rec("get_table_schema_unknown_table", res[0].text, True)

    # S1 defect: destructive SQL through execute_query
    res = await server.mcp.call_tool("execute_query", {"query": "DROP TABLE cad_elements"})
    tables = [r[0] for r in sqlite3.connect("autocad_data.db").execute("SELECT name FROM sqlite_master WHERE type='table'")]
    rec("DEFECT_execute_query_drop_table", {"reply": res[0].text, "tables_after": tables}, "cad_elements" not in tables)

    json.dump(R, open("/out/probe_autocad_server.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

asyncio.run(main())
