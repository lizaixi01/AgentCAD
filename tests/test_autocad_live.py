"""Live checks against a real AutoCAD (headless accoreconsole). Skipped when the
optional AutoCAD backend is not installed. Each AutoCAD job takes ~3 s."""
from __future__ import annotations

import pytest

from agentcad.backends.autocad import find_accoreconsole
from conftest import PLATE_SPEC, ok, reread

pytestmark = pytest.mark.skipif(find_accoreconsole() is None, reason="AutoCAD (accoreconsole.exe) not installed")


def test_generated_drawing_passes_autocad_audit(rt, plate):
    r = ok(rt.autocad_audit(plate))
    assert r["passed"] and r["audit_errors"] == 0
    assert r["entities_seen_by_autocad"] == len(ok(rt.inspect_entities(plate))["entities"])
    assert r["insunits"] == 4  # millimetres survive


def test_r12_export_passes_autocad_audit(rt, ws, plate):
    ok(rt.export_drawing(plate, "r12.dxf", "dxf", "R12"))
    r = ok(rt.autocad_audit("r12.dxf"))
    assert r["audit_errors"] == 0, r["messages"]


def test_dwg_round_trip_keeps_spec_and_revises(rt, ws, plate):
    e = ok(rt.export_drawing(plate, "plate.dwg", "dwg"))
    assert e["readback"]["readable"] and e["readback"]["entities"] == e["readback"]["source_entities"]
    ok(rt.import_drawing("plate.dwg", "from_dwg.dxf"))
    v = ok(rt.validate_drawing("from_dwg.dxf"))["validation"]
    assert v["passed"] and v["requirements_source"] == "stored_part_spec"
    r = ok(rt.revise_drawing("from_dwg.dxf", {"width": 120}))
    assert len(r["changes"]["modified"]) == 10 and r["validation"]["passed"]
    # and AutoCAD accepts the revised file too
    assert ok(rt.autocad_audit("from_dwg.dxf"))["passed"]
    holes = sorted((round(c.dxf.center.x, 6), round(c.dxf.center.y, 6)) for c in reread(ws, "from_dwg.dxf").modelspace().query("CIRCLE"))
    assert holes == [(10, 10), (10, 50), (110, 10), (110, 50)]


def test_autocad_audit_accepts_dwg(rt, ws, plate):
    """Agents audited the DWG they had just exported (hard-task trials); the runtime converts it first."""
    ok(rt.export_drawing(plate, "audit.dwg", "dwg"))
    a = ok(rt.autocad_audit("audit.dwg"))
    assert a["passed"] and a["entities_seen_by_autocad"] > 0


def test_autocad_audit_detects_defects(rt, ws, plate):
    """The audit is not a rubber stamp: ezdxf's raw R12 export (before clean_r12)
    defines BYBLOCK/BYLAYER linetypes and unused styles, which AutoCAD rejects."""
    import ezdxf
    from ezdxf.addons import r12export
    r12export.saveas(ezdxf.readfile(ws / plate), ws / "raw_r12.dxf")
    r = ok(rt.autocad_audit("raw_r12.dxf"))
    assert not r["passed"] and r["audit_errors"] > 0
    msgs = {m["message"]: m["count"] for m in r["messages"]}
    assert any("BYBLOCK" in m for m in msgs) and any("BYLAYER" in m for m in msgs)
    assert sum(msgs.values()) == r["audit_errors"]  # deduplicated, nothing lost


def test_validator_and_autocad_agree_on_rejected_file(rt, ws):
    """A file AutoCAD discards on import (XDATA with an unregistered APPID) is also
    failed by AgentCAD's own validator, so the agent learns before handing it over."""
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_line((0, 0), (10, 0)).set_xdata("NOTREG", [(1000, "x")])
    doc.saveas(ws / "unreg.dxf")
    ours = ok(rt.validate_drawing("unreg.dxf"))["validation"]
    acad = ok(rt.autocad_audit("unreg.dxf"))
    assert not ours["passed"] and "XDATA_APPID_UNREGISTERED" in {i["code"] for i in ours["issues"]}
    assert acad["import_rejected"] and not acad["passed"] and acad["entities_seen_by_autocad"] == 0
