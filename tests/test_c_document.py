"""Test C: technical document (PDF / text) -> traced requirements -> drawing -> item-by-item check."""
from __future__ import annotations

import shutil

import pytest

from conftest import FIXTURES, ok, reread, write_pdf

PDF_PAGES = [
    ["BRACKET PLATE BP-150 - TECHNICAL SPECIFICATION", "1 Scope", "This document defines the bracket plate.",
     "All dimensions are in mm."],
    ["2 Geometry", "Overall size 150 x 90 mm.", "Thickness 5 mm.", "3 Holes",
     "Four through holes, diameter 9 mm, located at each corner,", "15 mm from the adjacent edges.",
     "4 Material", "Material: S355"],
]


@pytest.fixture
def pdf_doc(ws):
    p = ws / "bp150.pdf"
    write_pdf(p, PDF_PAGES)
    return "bp150.pdf"


def test_pdf_extraction_keeps_sources(rt, pdf_doc):
    r = ok(rt.extract_requirements(pdf_doc))
    assert r["status"] == "ok", r["issues"]
    s = r["spec"]
    assert (s["units"], s["width"], s["height"], s["thickness"], s["material"]) == ("mm", 150, 90, 5, "S355")
    assert s["holes"][0] | {"source": None} == {"pattern": "corners", "diameter": 9, "edge_offset": 15, "source": None}
    tr = r["traceability"]
    assert tr["width"][0]["page"] == 2 and "150 x 90" in tr["width"][0]["text"]
    assert tr["hole_diameter"][0]["page"] == 2 and tr["hole_diameter"][0]["section"].startswith("3")
    assert tr["units"][0]["page"] == 1


def test_pdf_to_drawing_and_item_by_item_verification(rt, ws, pdf_doc):
    r = ok(rt.revise_from_document(pdf_doc, "bp150.dxf"))
    assert r["mode"] == "created"
    assert r["validation"]["passed"], r["validation"]
    ver = {v["requirement"]: v for v in r["verification"]}
    assert ver["outline"]["actual"] == {"width": 150.0, "height": 90.0}
    assert ver["outline"]["document_source"]["page"] == 2
    assert ver["hole.tr"]["actual"] == {"center": [135.0, 75.0], "diameter": 9.0}
    assert ver["hole.tr"]["document_source"]["hole_diameter"]["page"] == 2
    assert ver["material"]["status"] == "pass"
    assert all(v["status"] == "pass" for v in r["verification"])
    # drawing on disk agrees
    doc = reread(ws, "bp150.dxf")
    assert sorted(round(c.dxf.radius * 2, 9) for c in doc.modelspace().query("CIRCLE")) == [9.0] * 4


def test_chinese_markdown_spec(rt, ws):
    shutil.copy(FIXTURES / "plate_spec_zh.md", ws / "zh.md")
    r = ok(rt.extract_requirements("zh.md"))
    assert r["status"] == "ok", r["issues"]
    s = r["spec"]
    assert (s["width"], s["height"], s["corner_radius"], s["thickness"], s["material"]) == (120, 80, 5, 4, "Q235")
    assert s["holes"][0]["diameter"] == 10 and s["holes"][0]["edge_offset"] == 12
    assert r["traceability"]["edge_offset"][0]["section"] == "4. 安装孔"
    d = ok(rt.revise_from_document("zh.md", "zh.dxf"))
    assert d["validation"]["passed"], d["validation"]["issues"]
    ver = {v["requirement"]: v for v in d["verification"]}
    assert ver["dim.corner_radius"]["actual"] == 5.0


def test_conflicting_document_is_refused(rt, ws):
    shutil.copy(FIXTURES / "plate_spec_conflict.txt", ws / "conflict.txt")
    r = ok(rt.extract_requirements("conflict.txt"))
    assert r["status"] == "conflict"
    c = next(i for i in r["issues"] if i["code"] == "SPEC_CONFLICT")
    assert c["field"] == "width" and {s["line"] for s in c["sources"]} == {5, 7}
    d = rt.revise_from_document("conflict.txt", "conflict.dxf")
    assert not d["ok"] and d["error"]["code"] == "SPEC_CONFLICT" and d["error"]["category"] == "spec"
    assert not (ws / "conflict.dxf").exists()


def test_missing_information_is_reported_not_invented(rt, ws):
    shutil.copy(FIXTURES / "plate_spec_missing.txt", ws / "missing.txt")
    r = ok(rt.extract_requirements("missing.txt"))
    assert r["status"] == "incomplete"
    codes = {(i["code"], i["field"]) for i in r["issues"]}
    assert ("UNITS_UNDEFINED", "units") in codes
    assert ("SPEC_MISSING_PARAM", "hole_diameter") in codes
    assert "diameter" not in (r["spec"]["holes"][0] if r["spec"].get("holes") else {}) or r["spec"]["holes"][0]["diameter"] is None
    d = rt.revise_from_document("missing.txt", "missing.dxf")
    assert not d["ok"] and d["error"]["code"] == "SPEC_INCOMPLETE"
    # the caller may supply the missing decisions explicitly; they are recorded as overrides
    d = ok(rt.revise_from_document("missing.txt", "missing.dxf", overrides={
        "units": "mm", "holes": [{"pattern": "corners", "diameter": 6.6, "edge_offset": 10}]}))
    assert d["traceability"]["units"] == [{"origin": "caller_override"}]
    assert d["validation"]["passed"]


def test_agent_supplied_facts_are_citation_checked(rt, ws, pdf_doc):
    facts = [{"field": "units", "value": "mm", "quote": "All dimensions are in mm", "page": 1},
             {"field": "width", "value": 150, "unit": "mm", "quote": "Overall size 150 x 90 mm", "page": 2},
             {"field": "height", "value": 90, "unit": "mm", "quote": "Overall size 150 x 90 mm", "page": 2},
             {"field": "hole_diameter", "value": 9, "unit": "mm", "quote": "diameter 9 mm", "page": 2},
             {"field": "hole_pattern", "value": "corners", "quote": "located at each corner", "page": 2},
             {"field": "edge_offset", "value": 15, "unit": "mm", "quote": "15 mm from the adjacent edges", "page": 2}]
    r = ok(rt.extract_requirements(pdf_doc, facts=facts))
    assert r["status"] == "ok" and r["extractor"] == "agent-citations"
    bad = facts + [{"field": "thickness", "value": 12, "quote": "Thickness 12 mm", "page": 2}]  # hallucinated
    r = ok(rt.extract_requirements(pdf_doc, facts=bad))
    assert r["status"] != "ok"
    assert any(i["code"] == "CITATION_NOT_FOUND" and i["field"] == "thickness" for i in r["issues"])


def test_document_revision_updates_existing_drawing(rt, ws, pdf_doc):
    ok(rt.revise_from_document(pdf_doc, "bp.dxf"))
    write_pdf(ws / "bp150_revB.pdf", [PDF_PAGES[0], [ln.replace("150 x 90", "180 x 90") for ln in PDF_PAGES[1]]])
    r = ok(rt.revise_from_document("bp150_revB.pdf", "bp.dxf"))
    assert r["mode"] == "revised" and r["validation"]["passed"]
    d = ok(rt.get_diff("bp.dxf"))
    assert d["summary"]["added"] == 0 and d["summary"]["deleted"] == 0 and d["summary"]["modified"] > 0
