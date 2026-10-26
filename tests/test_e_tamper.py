"""Test E: the validator judges the file on disk, not the task or the generator.
Files are tampered with by a *different* tool (raw ezdxf), behind the runtime's back."""
from __future__ import annotations

import ezdxf
import pytest

from agentcad.model import get_tag
from conftest import ok


def tamper(ws, name, fn):
    doc = ezdxf.readfile(str(ws / name))
    fn(doc)
    doc.saveas(ws / name)


def tagged(doc, tag):
    return next(e for e in doc.modelspace() if get_tag(e) == tag)


def results(rt, plate):
    v = ok(rt.validate_drawing(plate))["validation"]
    return v, {r["id"]: r for r in v["requirements"]}


def test_moved_hole_detected(rt, ws, plate):
    tamper(ws, plate, lambda d: tagged(d, "hole.tr").translate(1.5, 0, 0))
    v, r = results(rt, plate)
    assert not v["passed"]
    h = r["hole.tr"]
    assert h["status"] == "fail"
    assert h["expected"] == {"center": [90, 50], "diameter": 8.0}
    assert h["actual"]["center"] == [91.5, 50.0]
    assert h["deviation"] == pytest.approx(1.5) and h["tolerance"] == 1e-3
    assert all(r[k]["status"] == "pass" for k in ("hole.bl", "hole.br", "hole.tl"))


def test_resized_outline_detected(rt, ws, plate):
    def grow(doc):
        pl = tagged(doc, "outline")
        pts = [(x * 1.02 if x > 1 else x, y) for x, y in pl.get_points("xy")]
        pl.set_points(pts, format="xy")
    tamper(ws, plate, grow)
    v, r = results(rt, plate)
    o = r["outline"]
    assert o["status"] == "fail" and o["actual"]["width"] == pytest.approx(102.0) and o["deviation"] == pytest.approx(2.0)
    # the width dimension still says 100 but is no longer attached to geometry
    assert any(i["code"] == "DIMENSION_NOT_ATTACHED" for i in v["issues"])


def test_deleted_dimension_detected(rt, ws, plate):
    tamper(ws, plate, lambda d: d.modelspace().delete_entity(tagged(d, "dim.width")))
    v, r = results(rt, plate)
    assert r["dim.width"]["status"] == "fail" and r["dim.width"]["actual"] != 100.0
    assert not v["passed"]


def test_falsified_dimension_text_detected(rt, ws, plate):
    def lie(doc):
        tagged(doc, "dim.height").dxf.text = "65"
    tamper(ws, plate, lie)
    v, _ = results(rt, plate)
    bad = [i for i in v["issues"] if i["code"] == "DIMENSION_TEXT_MISMATCH"]
    assert bad and bad[0]["details"]["expected"] == pytest.approx(60.0)


def test_changed_hole_diameter_detected(rt, ws, plate):
    tamper(ws, plate, lambda d: setattr(tagged(d, "hole.bl").dxf, "radius", 4.5))
    _, r = results(rt, plate)
    assert r["hole.bl"]["status"] == "fail" and r["hole.bl"]["actual"]["diameter"] == 9.0
    assert r["hole_count.d8"]["status"] == "fail" and r["hole_count.d8"]["actual"] == 3


def test_external_modification_is_flagged(rt, ws, plate):
    tamper(ws, plate, lambda d: tagged(d, "hole.tr").translate(1, 0, 0))
    st = ok(rt.read_drawing(plate))["status"]
    assert st["modified_outside_runtime"] is True
