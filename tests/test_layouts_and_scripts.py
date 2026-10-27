"""Paper-space layouts and the opt-in script tool. Both come from the hard-task comparison
(docs/comparison-hard-tasks.md): on a real drawing the printed sheet held its own scaled copy of the part, which the
runtime could neither see nor edit, and plain-code agents handled edits the operation catalogue lacks."""
from __future__ import annotations

import json

import ezdxf
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime
from conftest import ok, reread

A = pytest.approx
SHEET = "Sheet1"


def sheet_drawing(ws, name="part.dxf"):
    """Model: a Ø10 hole. Sheet: the same hole copied at 0.5 scale, a Ø-dimension showing the true size, a note."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_circle((50, 50), 5)
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    lay = doc.layouts.new(SHEET)
    c = lay.add_circle((25, 25), 2.5)
    d = lay.add_diameter_dim(center=(25, 25), radius=2.5, angle=45, override={"dimlfac": 2.0})
    d.render()
    lay.add_text("TITLE", height=3, dxfattribs={"insert": (5, 5)})
    doc.saveas(ws / name)
    return name, c.dxf.handle


def test_read_inspect_and_validate_see_the_sheet(rt, ws):
    name, h = sheet_drawing(ws)
    r = ok(rt.read_drawing(name))
    sheet = next(l for l in r["layouts"] if l["name"] == SHEET)
    assert sheet["entity_types"]["CIRCLE"] == 1 and r["entity_types"]["CIRCLE"] == 1  # model counts unchanged
    ents = ok(rt.inspect_entities(name, layout=SHEET))["entities"]
    assert {e["type"] for e in ents} >= {"CIRCLE", "DIMENSION", "TEXT"} and all(e["layout"] == SHEET for e in ents)
    assert len(ok(rt.inspect_entities(name, layout="*", filter={"type": "CIRCLE"}))["entities"]) == 2
    v = ok(rt.validate_drawing(name))["validation"]
    warn = [i for i in v["issues"] if i["code"] == "LAYOUT_NOT_VALIDATED"]
    assert len(warn) == 1 and warn[0]["details"]["layout"] == SHEET and v["coverage"]["checked_layout"] == "Model"
    # the sheet itself: its dimension is compared as displayed (2.5 * 2 * dimlfac 2 = Ø10)
    v = ok(rt.validate_drawing(name, layout=SHEET, requirements=[
        {"type": "dimension", "kind": "diameter", "value": 10}, {"type": "text", "contains": "TITLE"}]))["validation"]
    assert [r["status"] for r in v["requirements"]] == ["pass", "pass"]
    assert any(i["code"] == "LAYOUT_NOT_VALIDATED" and i["details"]["layout"] == "Model" for i in v["issues"])


def test_operations_work_on_the_sheet(rt, ws):
    name, h = sheet_drawing(ws)
    r = ok(rt.apply_operations(name, [
        {"op": "modify", "target": h, "set": {"radius": 3}},                       # by handle, in the sheet
        {"op": "add_text", "text": "REV B", "insert": [5, 12], "height": 3, "layout": SHEET},
        {"op": "copy", "target": h, "delta": [10, 0]},                              # the copy stays on the sheet
        {"op": "add_point", "location": [0, 0]}]))                                  # default: model space
    added = r["changes"]["added"]
    doc = reread(ws, name)
    sheet = doc.layouts.get(SHEET)
    sheet_h = {e.dxf.handle for e in sheet}
    assert doc.entitydb[h].dxf.radius == A(3)
    assert added[0] in sheet_h and added[1] in sheet_h and added[2] not in sheet_h
    # a filter searches the op's layout: model space has no TEXT, the sheet has two
    e = rt.apply_operations(name, [{"op": "delete", "target": {"type": "TEXT"}}])["error"]
    assert e["code"] == "ENTITY_NOT_FOUND"
    ok(rt.apply_operations(name, [{"op": "delete", "target": {"type": "TEXT"}, "layout": SHEET}]))
    assert not list(reread(ws, name).layouts.get(SHEET).query("TEXT"))
    d = ok(rt.get_diff(name))
    assert all(x.get("layout") == SHEET for x in d["deleted"])
    e = rt.apply_operations(name, [{"op": "add_line", "start": [0, 0], "end": [1, 1], "layout": "Nope"}])["error"]
    assert e["code"] == "LAYOUT_NOT_FOUND" and SHEET in e["hint"] and e["op_index"] == 0


def test_dimensions_on_a_sheet_show_true_size(rt, ws):
    """A sheet showing the part at 0.5 needs DIMLFAC 2 so a Ø5 copy reads Ø10; agents could set it neither on
    creation nor afterwards and worked around it in every hard-task run."""
    name, h = sheet_drawing(ws)
    r = ok(rt.apply_operations(name, [{"op": "add_diameter_dim", "target": h, "length_factor": 2, "layout": SHEET}]))
    new = r["changes"]["added"][0]
    v = ok(rt.validate_drawing(name, layout=SHEET, requirements=[
        {"type": "dimension", "kind": "diameter", "value": 10}]))["validation"]
    assert v["requirements"][0]["status"] == "pass"
    # change an existing dimension: text, height and length factor; the block is re-rendered
    ok(rt.apply_operations(name, [{"op": "modify", "target": new,
                                   "set": {"text": "2X <>", "text_height": 2.5, "length_factor": 4}}]))
    d = reread(ws, name).entitydb[new]
    ov = d.override()
    assert d.dxf.text == "2X <>" and ov.get("dimlfac") == A(4) and ov.get("dimtxt") == A(2.5)
    e = rt.apply_operations(name, [{"op": "modify", "target": new, "set": {"radius": 3}}])["error"]
    assert e["code"] == "UNKNOWN_FIELD" and "length_factor" in e["hint"]


# --- run_script --------------------------------------------------------------------------------------------

@pytest.fixture
def srt(ws):
    return Runtime(Policy(root=ws, allow_scripts=True, script_timeout=20))


SCRIPT = """
n = 0
for lay in [msp, doc.layouts.get("Sheet1")]:
    for c in lay.query("CIRCLE"):
        c.dxf.radius *= 1.2
        n += 1
result = {"changed": n}
"""


def test_scripts_are_off_by_default(rt, ws):
    name, _ = sheet_drawing(ws)
    e = rt.run_script(name, SCRIPT)["error"]
    assert e["code"] == "SCRIPTS_DISABLED" and e["category"] == "policy"


def test_script_is_a_transaction(srt, ws):
    name, h = sheet_drawing(ws)
    before = (ws / name).read_bytes()
    dry = ok(srt.run_script(name, SCRIPT, dry_run=True))
    assert dry["result"] == {"changed": 2} and len(dry["changes"]["modified"]) == 2
    assert (ws / name).read_bytes() == before
    r = ok(srt.run_script(name, SCRIPT, label="scale holes"))
    assert r["checkpoint_before"] and r["validation"]["passed"]
    assert reread(ws, name).entitydb[h].dxf.radius == A(3)
    hist = ok(srt.history(name))["records"][-1]
    assert hist["tool"] == "run_script" and "radius *= 1.2" in hist["code"] and hist["code_sha256"]
    ok(srt.rollback(name))
    assert reread(ws, name).entitydb[h].dxf.radius == A(2.5)


@pytest.mark.parametrize("code, why", [
    ("import os\nos.remove('x')", "import of 'os'"),
    ("open('x.txt', 'w')", "'open'"),
    ("doc.saveas('elsewhere.dxf')", "'saveas'"),
    ("x = ().__class__.__bases__", "'__"),
    ("f = getattr(doc, 'saveas')", "'getattr'"),
    ("from ezdxf.addons import odafc", "odafc"),
])
def test_scripts_are_checked_before_running(srt, ws, code, why):
    name, _ = sheet_drawing(ws)
    before = (ws / name).read_bytes()
    e = srt.run_script(name, code)["error"]
    assert e["code"] == "SCRIPT_REJECTED" and why in e["message"]
    assert (ws / name).read_bytes() == before


def test_script_errors_leave_the_file_unchanged(srt, ws):
    name, _ = sheet_drawing(ws)
    before = (ws / name).read_bytes()
    e = srt.run_script(name, "x = 1\ny = [c for c in msp.query('CIRCLE')]\nz = y[5]")["error"]
    assert e["code"] == "SCRIPT_FAILED" and "IndexError" in e["message"]
    assert any("line 3" in s for s in e["details"]["script_lines"])
    e = srt.run_script(name, "msp.add_line((0, 0), (0, 0))", strict=True)["error"]   # zero-length line
    assert e["code"] == "VALIDATION_FAILED"
    assert (ws / name).read_bytes() == before
    failed = [r for r in json.loads("[" + ",".join(
        (ws / ".agentcad").rglob("journal.jsonl").__next__().read_text("utf-8").splitlines()) + "]")
        if r["tool"] == "run_script"]
    assert [r["ok"] for r in failed] == [False, False]


def test_script_timeout(ws):
    rt = Runtime(Policy(root=ws, allow_scripts=True, script_timeout=2))
    name, _ = sheet_drawing(ws)
    e = rt.run_script(name, "while True:\n    pass")["error"]
    assert e["code"] == "SCRIPT_TIMEOUT"
