"""Delivery gates must fail when independently saved intent or artifacts disagree."""
import ezdxf
import pytest

from agentcad.service import Runtime
from conftest import PLATE_SPEC


def test_delivery_restores_spec_after_restart_and_rejects_wrong_hole(rt, ws):
    assert rt.draw_from_spec(PLATE_SPEC, "plate.dxf")["ok"]
    good = Runtime(rt.policy).deliver_drawing("plate.dxf", "good", formats=["dxf", "pdf", "svg", "json", "csv", "xlsx"])
    assert good["ok"], good
    assert good["validation"]["requirements_source"] == "stored_part_spec"
    assert good["validation"]["summary"]["requirements_total"] > 0
    assert all(a["verification"]["passed"] for a in good["artifacts"])
    doc = ezdxf.readfile(ws / "plate.dxf")
    doc.modelspace().query("CIRCLE")[0].dxf.radius = 5
    doc.saveas(ws / "plate.dxf")
    refused = Runtime(rt.policy).deliver_drawing("plate.dxf", "bad")
    assert refused["error"]["code"] == "DELIVERY_REJECTED", refused
    assert refused["error"]["details"]["validation"]["summary"]["requirements_failed"] > 0
    assert not (ws / "bad" / "manifest.json").exists()


@pytest.mark.parametrize("kind", ["architecture", "mechanical", "pid"])
def test_delivery_enforces_saved_domain_critique(rt, ws, blank, kind):
    if kind == "architecture":
        operation = {"op": "draw_arch_plan", "spec": {
            "walls": [{"id": "outer", "axis": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
                       "closed": True, "thickness": 200}],
            "rooms": [{"id": "living", "number": "01", "name": "Living", "at": [2000, 2000]}]}}
    elif kind == "mechanical":
        operation = {"op": "draw_mechanical_assembly", "spec": {
            "fasteners": [{"part": "hex_bolt", "size": "M8", "length": 30, "insert": [60, 90]}]}}
    else:
        operation = {"op": "draw_pid", "spec": {
            "equipment": [{"id": "P1", "symbol": "centrifugal_pump", "x": 0, "y": 0},
                          {"id": "P2", "symbol": "centrifugal_pump", "x": 50, "y": 20}],
            "lines": [{"from": "P1.discharge", "to": "P2.suction", "number": "DN50-ABC"}]}}
    assert rt.apply_operations(blank, [operation])["ok"]
    good = rt.deliver_drawing(blank, "good")
    assert good["ok"], good
    assert good["validation"]["engineering"][kind]["passed"]
    report = rt.read_engineering(blank, kind)
    doc = ezdxf.readfile(ws / blank)
    if kind == "architecture":
        doc.entitydb[report["rooms"][0]["handle"]].dxf.text = "01 Living 999.00 m2"
    elif kind == "mechanical":
        doc.modelspace().delete_entity(doc.entitydb[report["bom"][0]["handles"][0]])
    else:
        doc.modelspace().query("INSERT")[1].dxf.insert = (100, 100)
    doc.saveas(ws / blank)
    refused = Runtime(rt.policy).deliver_drawing(blank, "bad", min_score=0)
    assert refused["error"]["code"] == "DELIVERY_REJECTED", refused
    assert not refused["error"]["details"]["validation"]["engineering"][kind]["passed"]
    assert not (ws / "bad" / "manifest.json").exists()
    # Explicit non-strict delivery remains possible; the manifest carries the failed gate.
    accepted = rt.deliver_drawing(blank, "diagnostic", min_score=0, strict=False)
    assert accepted["ok"] and not accepted["validation"]["passed"], accepted


@pytest.mark.parametrize("corruption", ["model", "paper", "block", "attribute", "style"])
def test_delivery_detects_dxf_loss_beyond_model_entity_count(rt, ws, blank, monkeypatch, corruption):
    doc = ezdxf.readfile(ws / blank)
    block = doc.blocks.new("PART")
    block.add_circle((0, 0), 2)
    insert = doc.modelspace().add_blockref("PART", (0, 0))
    insert.add_attrib("ID", "part-01", (0, 0))
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.layouts.new("Sheet").add_line((0, 0), (10, 0))
    doc.saveas(ws / blank)
    export = rt.export_drawing
    def damaged(path, output, fmt):
        result = export(path, output, fmt)
        saved = ezdxf.readfile(ws / output)
        if corruption == "model":
            saved.modelspace().query("LINE")[0].dxf.end = (11, 0, 0)
        elif corruption == "paper":
            saved.layouts.get("Sheet").delete_all_entities()
        elif corruption == "block":
            saved.blocks["PART"][0].dxf.radius = 3
        elif corruption == "attribute":
            saved.modelspace().query("INSERT")[0].attribs[0].dxf.text = "wrong"
        else:
            saved.layers.get("0").dxf.color = 2
        saved.saveas(ws / output)
        return result
    monkeypatch.setattr(rt, "export_drawing", damaged)
    result = rt.deliver_drawing(blank, "bad", min_score=0)
    assert result["error"]["code"] == "DELIVERY_PARITY_FAILED", result
    assert not (ws / "bad" / "manifest.json").exists()


@pytest.mark.parametrize("fmt", ["json", "csv", "xlsx", "pdf", "svg"])
def test_delivery_rejects_nonempty_corrupt_exports(rt, ws, blank, monkeypatch, fmt):
    assert rt.apply_operations(blank, [{"op": "add_circle", "center": [0, 0], "radius": 10}])["ok"]
    export = rt.export_drawing
    def damaged(path, output, format):
        result = export(path, output, format)
        (ws / output).write_text("nonempty but invalid", encoding="utf-8")
        return result
    monkeypatch.setattr(rt, "export_drawing", damaged)
    result = rt.deliver_drawing(blank, "bad", formats=[fmt])
    assert result["error"]["code"] == "DELIVERY_PARITY_FAILED", result
    assert not (ws / "bad" / "manifest.json").exists()


def test_invalid_stored_spec_cannot_silently_disable_delivery_requirements(rt, ws, blank):
    from agentcad.metadata import set_meta
    doc = ezdxf.readfile(ws / blank)
    set_meta(doc, "part_spec", {"kind": "not-supported"})
    doc.saveas(ws / blank)
    assert not rt.deliver_drawing(blank, "bad")["ok"]
    assert not (ws / "bad" / "manifest.json").exists()


def test_delivery_checks_paper_space_integrity(rt, ws, blank):
    doc = ezdxf.readfile(ws / blank)
    doc.modelspace().add_circle((0, 0), 3)
    doc.layouts.new("Sheet").add_line((1, 1), (1, 1))
    doc.saveas(ws / blank)
    result = rt.deliver_drawing(blank, "bad")
    assert result["error"]["code"] == "DELIVERY_REJECTED", result
    assert any(i.get("layout") == "Sheet" for i in result["error"]["details"]["validation"]["issues"])
