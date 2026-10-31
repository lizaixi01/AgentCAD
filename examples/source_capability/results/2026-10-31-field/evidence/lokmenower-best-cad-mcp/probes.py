"""Headless probes for best-cad-mcp @ e02b612 (run offline in Docker).

AutoCAD COM is absent on Linux. Probes call the product's own public functions:
the SQLite understanding layer and CADPlan DSL run for real; the COM controller
is driven through a minimal stub document only to show what the wrapper reports.
"""
import json
import os
import sys
import tempfile
import traceback
import types

sys.path.insert(0, "/work")
# Same stubs the repository's own tests/conftest.py installs on non-Windows hosts.
sys.path.insert(0, "/work/tests")
import conftest  # noqa: E402,F401

WS = tempfile.mkdtemp(prefix="ws-")
os.environ["CAD_MCP_WORKSPACE_ROOT"] = WS
os.chdir(WS)

from src.cad_database import CADDatabase, get_database  # noqa: E402
from src.cad_understanding import plan as P  # noqa: E402
from src.cad_understanding.constraints import extract_drawing_constraints, get_constraints  # noqa: E402
from src.cad_understanding.dimension_binding import bind_dimension_to_geometry  # noqa: E402
from src.cad_understanding.validators import validate_geometry  # noqa: E402
from src.cad_understanding.drawing_graph import infer_cross_entity_closed_profiles  # noqa: E402

results = []


def probe(pid, item, desc):
    def deco(fn):
        try:
            observed, verdict = fn()
        except Exception as exc:  # report, never hide
            observed, verdict = {"exception": repr(exc), "tb": traceback.format_exc()[-800:]}, "error"
        results.append({"id": pid, "item": item, "description": desc, "verdict": verdict, "observed": observed})
        return fn
    return deco


def fresh_db(name):
    db = CADDatabase(os.path.join(WS, name + ".db"))
    db.configure_context(workspace_root=WS, conversation_id="probe", thread_id=name)
    return db


def line(db, h, a, b):
    db.upsert_entity(h, "Line", "AcDbLine", layer="OUTLINE",
                     geometry={"start": [*a, 0.0], "end": [*b, 0.0]},
                     bbox=(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])),
                     topology_detail="full")


# ---------------- F1 geometry / topology ----------------
@probe("P01", "F1", "4 separate lines forming a 10x5 rectangle are found as one closed cross-entity profile with area 50")
def _():
    db = fresh_db("f1a")
    line(db, "A", (0, 0), (10, 0)); line(db, "B", (10, 0), (10, 5))
    line(db, "C", (10, 5), (0, 5)); line(db, "D", (0, 5), (0, 0))
    r = infer_cross_entity_closed_profiles(database=db)
    profs = r if isinstance(r, list) else (r.get("data", {}).get("profiles") or r.get("data", {}).get("closed_profiles") or r)
    txt = json.dumps(profs, default=str)
    areas = []
    if isinstance(profs, list):
        for p in profs:
            for k in ("area", "signed_area", "abs_area"):
                if isinstance(p, dict) and k in p:
                    areas.append(abs(p[k]))
    ok = isinstance(profs, list) and len(profs) == 1 and any(abs(a - 50) < 1e-6 for a in areas)
    return {"profile_count": len(profs) if isinstance(profs, list) else None, "areas": areas, "excerpt": txt[:600]}, ("pass" if ok else "fail")


@probe("P02", "F1", "Boundary: open chain (3 sides) and a 1e-3 gap must not be reported as closed")
def _():
    db = fresh_db("f1b")
    line(db, "A", (0, 0), (10, 0)); line(db, "B", (10, 0), (10, 5)); line(db, "C", (10, 5), (0, 5))
    line(db, "D", (0, 5), (0, 0.001))
    r = infer_cross_entity_closed_profiles(database=db)
    profs = r if isinstance(r, list) else r.get("data", {}).get("profiles", r)
    n = len(profs) if isinstance(profs, list) else None
    return {"profile_count": n, "excerpt": json.dumps(profs, default=str)[:400]}, ("pass" if n == 0 else "observe")


# ---------------- C2 intent vs geometry ----------------
@probe("P03", "C2", "Radial dim override R6 on R5 circle -> violated; correct R5 -> satisfied; dim with no candidate -> not satisfied")
def _():
    db = fresh_db("c2")
    db.upsert_entity("C1", "Circle", "AcDbCircle", geometry={"center": [0, 0, 0], "radius": 5}, bbox=(-5, -5, 5, 5))
    db.upsert_entity("D1", "RadialDimension", "AcDbRadialDimension", geometry={"measurement": 5, "text_override": "R6"}, bbox=(-2, -2, 8, 8))
    db.upsert_entity("D2", "RadialDimension", "AcDbRadialDimension", geometry={"measurement": 5}, bbox=(-2, -2, 8, 8))
    db.upsert_entity("D3", "RadialDimension", "AcDbRadialDimension", geometry={"measurement": 77}, bbox=(500, 500, 510, 510))
    extract_drawing_constraints(database=db)
    cons = get_constraints(database=db)["data"]["constraints"]
    by = {}
    for c in cons:
        if str(c.get("source", "")).startswith("dimension:"):
            hs = [h for h in ("D1", "D2", "D3") if h in json.dumps(c, default=str)]
            by[",".join(hs) or c.get("constraint_id", "?")] = {"source": c["source"], "status": c["status"], "value": c.get("value"), "actual": c.get("actual")}
    b3 = bind_dimension_to_geometry("D3", database=db)["data"]["binding"]["status"]
    d1 = next((v for k, v in by.items() if k.split(",")[0] == "D1"), None)
    d2 = next((v for k, v in by.items() if k.split(",")[0] == "D2"), None)
    d3 = next((v for k, v in by.items() if k.split(",")[0] == "D3"), None)
    ok = d1 and d1["status"] == "violated" and d2 and d2["status"] == "satisfied" and (d3 is None or d3["status"] != "satisfied") and b3 != "bound"
    return {"dimension_constraints": by, "D3_binding": b3}, ("pass" if ok else "fail")


@probe("P04", "C2", "validate_geometry flags zero-length line, duplicates and unclosed polyline; clean drawing passes")
def _():
    db = fresh_db("val")
    line(db, "Z", (1, 1), (1, 1)); line(db, "X1", (0, 0), (5, 0)); line(db, "X2", (0, 0), (5, 0))
    r = validate_geometry(database=db)["data"]["validation_report"]
    db2 = fresh_db("val2"); line(db2, "Q", (0, 0), (3, 4))
    r2 = validate_geometry(database=db2)["data"]["validation_report"]
    types = sorted({i["issue_type"] for i in r["issues"]})
    sev = sorted({i["severity"] for i in r["issues"]})
    ok = "zero_length_lines" in types and "duplicate_entities" in types and r2["issue_count"] == 0
    return {"issue_types": types, "severities": sev, "passed": r["passed"], "clean_issue_count": r2["issue_count"]}, ("pass" if ok else "fail")


@probe("P05", "C2", "Plan handle capture: a terse result with coordinates but no handle mis-binds save_as to coordinate tokens")
def _():
    samples = {
        "inserted_with_coords": "Inserted block DOOR at 100,200",
        "created_no_handle": "OK: created table 3x4 at 120 250",
        "proper": "OK: 已绘制圆\n  handle: 8A\n  radius: 5",
    }
    out = {k: P.parse_tool_result_handles(v) for k, v in samples.items()}
    wrong = bool(out["inserted_with_coords"]) or bool(out["created_no_handle"])
    return out, ("reproduced" if wrong else "not reproduced")


# ---------------- C1 transactions / CADPlan ----------------
GOOD_PLAN = {"plan_id": "p", "units": "mm", "steps": [
    {"step_id": "s1", "op": "draw_circle", "args": {"center_x": 0, "center_y": 0, "radius": 5}, "save_as": "$c",
     "postconditions": [{"type": "exists", "target": "$c"}]},
    {"step_id": "s2", "op": "move_entity", "args": {"handle": "$c", "from_point": [0, 0, 0], "to_point": [5, 0, 0]}},
]}


@probe("P06", "C1", "validate/dry-run gates: unknown op, send_command, missing variable rejected; execute without allow_modify refused")
def _():
    bad_op = P.validate_cad_plan({"plan_id": "x", "steps": [{"step_id": "a", "op": "explode_everything", "args": {}}]})
    raw = P.validate_cad_plan({"plan_id": "x", "steps": [{"step_id": "a", "op": "send_command", "args": {"command": "SHELL"}}]})
    miss = P.validate_cad_plan({"plan_id": "x", "steps": [{"step_id": "a", "op": "move_entity", "args": {"handle": "$nope", "from_point": [0, 0, 0], "to_point": [1, 0, 0]}}]})
    dry = P.dry_run_cad_plan(GOOD_PLAN)
    ex = P.execute_cad_plan(GOOD_PLAN, allow_modify=False)
    obs = {"unknown_op_ok": bad_op["ok"], "send_command_ok": raw["ok"], "missing_var_ok": miss["ok"],
           "dry_run_ok": dry["ok"], "dry_run_steps": len(dry.get("data", {}).get("steps", [])),
           "execute_without_allow_ok": ex["ok"], "execute_msg": ex["message"]}
    ok = not bad_op["ok"] and not raw["ok"] and not miss["ok"] and dry["ok"] and not ex["ok"]
    return obs, ("pass" if ok else "fail")


class Calls:
    def __init__(self):
        self.log = []


def install_fake_dispatch(calls, fail_at=None):
    def mk(name):
        def fn(**kw):
            calls.log.append((name, kw))
            if name == fail_at:
                return "移动失败: entity not found"
            if name == "draw_circle":
                return "OK: 已绘制圆\n  handle: 1A2\n  radius: 5"
            return f"OK: {name} handle: {kw.get('handle', '1A2')}"
        return fn
    P._tool_dispatch = lambda: {op: mk(op) for op in P.SAFE_PLAN_OPS}
    from src.cad_tools import file_tools
    file_tools.begin_undo_group = lambda name="MCP": (calls.log.append(("begin", name)) or {"ok": True})
    file_tools.end_undo_group = lambda name="MCP": (calls.log.append(("end", name)) or {"ok": True})
    file_tools.rollback_undo_group = lambda name="MCP": (calls.log.append(("rollback", name)) or {"ok": True})


@probe("P07", "C1", "Failed step (string failure) triggers rollback and ok=false with completed_steps")
def _():
    calls = Calls(); install_fake_dispatch(calls, fail_at="move_entity")
    r = P.execute_cad_plan(GOOD_PLAN, allow_modify=True)
    names = [c[0] for c in calls.log]
    ok = (r["ok"] is False and "rollback" in names and len(r["data"]["completed_steps"]) == 1)
    return {"ok": r["ok"], "calls": names, "msg": r["message"][:200]}, ("pass" if ok else "fail")


@probe("P08", "C1", "DEFECT: rollback_on_high_severity_validation=True is ignored when post-plan validation reports high-severity issues")
def _():
    db = get_database()
    db.configure_context(workspace_root=WS, conversation_id="probe", thread_id="default")
    line(db, "Z0", (3, 3), (3, 3))  # zero-length line -> validation issue
    line(db, "Y1", (0, 0), (9, 0)); line(db, "Y2", (0, 0), (9, 0))  # duplicates
    calls = Calls(); install_fake_dispatch(calls)
    r = P.execute_cad_plan(GOOD_PLAN, allow_modify=True, rollback_on_high_severity_validation=True, validate_after_plan=True)
    rep = r["data"]["after_artifacts"]["validation"]["data"]["validation_report"]
    names = [c[0] for c in calls.log]
    sev = sorted({i["severity"] for i in rep["issues"]})
    high = any(s in {"high", "critical"} for s in sev)
    verdict = "reproduced" if (r["ok"] and "rollback" not in names and not rep["passed"]) else ("not reproduced" if "rollback" in names else "inconclusive")
    return {"execute_ok": r["ok"], "validation_passed": rep["passed"], "severities": sev, "high_present": high,
            "rollback_called": "rollback" in names, "calls": names}, verdict


# ---------------- F2 / S2: COM wrapper reporting (stub document) ----------------
class FakeState:
    IsQuiescent = True


class FakeMS:
    def __init__(self):
        self.Count = 5

    def Item(self, i):
        raise IndexError(i)


class FakeDoc:
    def __init__(self):
        self.sent = []
        self.ModelSpace = FakeMS()
        self.Name = "stub.dwg"

    def SendCommand(self, s):
        self.sent.append(s)  # a real AutoCAD would just echo an error for a nil entity


class FakeDocs:
    Count = 1


class FakeAcad:
    def __init__(self, doc):
        self.ActiveDocument = doc
        self.Documents = FakeDocs()

    def GetAcadState(self):
        return FakeState()


def stub_controller():
    from src.cad_controller import get_controller
    c = get_controller()
    doc = FakeDoc()
    c.acad = FakeAcad(doc)
    c.doc = doc
    c.connect = lambda *a, **k: None
    return c, doc


@probe("P09", "F2", "DEFECT: trim/extend of handles that do not exist report success; nothing is read back")
def _():
    c, doc = stub_controller()
    t = c.trim(["FFFF0"], ["EEEE0"])
    e = c.extend(["FFFF1"], ["EEEE1"])
    from src.cad_tools import edit_tools
    edit_tools.ctrl = c
    msg = edit_tools.trim_entity("FFFF2", ["EEEE2"])
    verdict = "reproduced" if (t.get("success") and e.get("success") and "失败" not in msg) else "not reproduced"
    return {"trim": t, "extend": e, "trim_entity_tool_text": msg[:200], "lisp_sent": doc.sent[:3]}, verdict


@probe("P10", "S1", "LISP literal guards reject handle/number injection before anything is sent")
def _():
    c, doc = stub_controller()
    before = len(doc.sent)
    t = c.trim(['8A") (command "SHELL" "calc'], ["1"])
    f = c.fillet("8A", "8B", "1)(command \"SHELL\"")
    sent_after = len(doc.sent) - before
    ok = (not t.get("success")) and (not f.get("success")) and sent_after == 0
    return {"trim": t, "fillet": f, "commands_sent": sent_after}, ("pass" if ok else "fail")


@probe("P11", "S1", "send_command forwards an arbitrary string (incl. AutoLISP startapp) with no filter")
def _():
    c, doc = stub_controller()
    r = c.send_command('(startapp "cmd.exe" "/c whoami")')
    return {"result": r, "sent": doc.sent[-1:]}, ("reproduced" if r.get("success") and doc.sent else "not reproduced")


# ---------------- S1 SQL read-only ----------------
@probe("P12", "S1", "execute_query read-only: SELECT works; INSERT/DELETE/ATTACH/PRAGMA writable refused")
def _():
    db = fresh_db("sql")
    line(db, "L1", (0, 0), (1, 0))
    out = {}
    for q in ["SELECT handle, type FROM cad_entities",
              "INSERT INTO cad_entities(handle) VALUES('X')",
              "DELETE FROM cad_entities",
              "ATTACH DATABASE '/tmp/evil.db' AS e",
              "PRAGMA journal_mode=DELETE",
              "WITH x AS (SELECT 1) DELETE FROM cad_entities"]:
        try:
            r = db.execute(q, read_only=True)
            out[q] = {"ok": True, "rows": len(r.get("rows", [])) if isinstance(r, dict) else None, "keys": list(r)[:5] if isinstance(r, dict) else None, "error": r.get("error") if isinstance(r, dict) else None}
        except Exception as exc:
            out[q] = {"ok": False, "error": repr(exc)[:160]}
    left = db.execute("SELECT COUNT(*) AS n FROM cad_entities", read_only=True)
    out["remaining_rows"] = left.get("rows")
    out["evil_db_created"] = os.path.exists("/tmp/evil.db")
    writes_blocked = all((not v["ok"]) or v.get("error") for k, v in out.items() if isinstance(v, dict) and "ok" in v and not k.startswith("SELECT"))
    return out, ("pass" if writes_blocked and not out["evil_db_created"] else "fail")


# ---------------- C4 abnormal input ----------------
@probe("P13", "C4", "open_drawing refuses .dxf before touching AutoCAD; import_dxf without allow_modify and with a missing file is refused")
def _():
    from src.cad_controller import get_controller
    c = get_controller()
    c.acad = None
    c.connect = lambda *a, **k: None
    a = c.open_drawing("/nope/x.dxf")
    b = c.import_dxf("/nope/x.dxf")
    c2, _doc = stub_controller()
    d = c2.import_dxf("/nope/missing.dxf", allow_modify=True)
    ok = not a["success"] and not b["success"] and not d["success"]
    return {"open_dxf": a, "import_no_allow": b, "import_missing": d}, ("pass" if ok else "fail")


@probe("P14", "C4", "Arc without angle unit plus diameter line is not closed into a profile (incomplete data stays unresolved)")
def _():
    db = fresh_db("c4")
    line(db, "DIA", (-10, 0), (10, 0))
    db.upsert_entity("ARC", "Arc", "AcDbArc", layer="OUTLINE",
                     geometry={"center": [0, 0, 0], "radius": 10, "start_angle": 0, "end_angle": 180,
                               "start_point": [10, 0, 0], "end_point": [-10, 0, 0]},
                     bbox=(-10, 0, 10, 10), topology_detail="full")
    r = infer_cross_entity_closed_profiles(database=db)
    profs = r if isinstance(r, list) else r.get("data", {}).get("profiles", r)
    n = len(profs) if isinstance(profs, list) else None
    return {"profile_count": n}, ("pass" if n == 0 else "observe")


def no_autocad():
    """Simulate 'AutoCAD not running': connect() leaves acad=None (what a failed GetActiveObject does)."""
    from src.cad_controller import get_controller
    c = get_controller()
    c.acad = None
    c.doc = None
    c.connect = lambda *a, **k: None
    return c


@probe("P15", "C2", "NEW DEFECT: with AutoCAD not connected, draw_line/draw_polyline-style tools report 'OK' with an empty handle and cache a phantom entity")
def _():
    c = no_autocad()
    from src.cad_tools import drawing_tools
    drawing_tools.ctrl = c
    raw = c.add_line(0, 0, 1, 0)
    msg = drawing_tools.draw_line(0, 0, 10, 0)
    db = get_database()
    phantom = db.get_entity("")
    try:
        circ = drawing_tools.draw_circle(0, 0, 5)
    except Exception as exc:
        circ = "raised " + repr(exc)[:120]
    verdict = "reproduced" if (isinstance(raw, dict) and raw.get("success") is False and msg.startswith("OK")) else "not reproduced"
    return {"controller_add_line_returned": raw, "draw_line_text": msg, "phantom_cached": bool(phantom),
            "draw_circle_same_condition": circ}, verdict


@probe("P16", "C1", "NEW DEFECT: a real CADPlan draw_line step with AutoCAD not connected 'executes' successfully (real dispatch, no stubs)")
def _():
    no_autocad()
    import importlib
    importlib.reload(P)  # restore the real _tool_dispatch replaced by earlier probes
    from src.cad_tools import file_tools, drawing_tools
    drawing_tools.ctrl = no_autocad()
    plan = {"plan_id": "p16", "units": "mm", "steps": [
        {"step_id": "l1", "op": "draw_line", "args": {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 0}, "save_as": "$l"}]}
    r = P.execute_cad_plan(plan, allow_modify=True, transactional=False, validate_after_plan=False)
    st = r.get("data", {}).get("state")
    return {"ok": r["ok"], "message": r["message"][:200], "state": st,
            "step_result": json.dumps(r.get("data", {}).get("results", [{}])[0].get("result"), ensure_ascii=False)[:200]}, \
        ("reproduced" if r["ok"] else "not reproduced")


print(json.dumps(results, ensure_ascii=False, indent=1, default=str))
