"""Test A: 100 x 60 mm mounting plate, four Ø8 corner holes 10 mm from the
adjacent edges, all key dimensions. Verified from the re-read file only."""
from __future__ import annotations

import math

import ezdxf
import pytest

from conftest import PLATE_SPEC, ok, reread

A = pytest.approx


def test_plate_generated_and_independently_verified(rt, ws, plate):
    path = ws / plate
    assert path.is_file()
    doc = ezdxf.readfile(str(path))  # valid DXF, re-readable by an independent reader
    assert doc.header["$INSUNITS"] == 4  # millimetres, explicit
    msp = doc.modelspace()

    # outline: computed from raw geometry, not from the spec
    outlines = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "OUTLINE"]
    assert len(outlines) == 1 and outlines[0].closed
    xs = [p[0] for p in outlines[0].get_points("xy")]
    ys = [p[1] for p in outlines[0].get_points("xy")]
    x0, y0 = min(xs), min(ys)
    assert max(xs) - x0 == A(100) and max(ys) - y0 == A(60)

    holes = msp.query("CIRCLE")
    assert len(holes) == 4
    assert all(h.dxf.radius * 2 == A(8) for h in holes)
    rel = sorted((round(h.dxf.center.x - x0, 9), round(h.dxf.center.y - y0, 9)) for h in holes)
    assert rel == [(10, 10), (10, 50), (90, 10), (90, 50)]
    for cx, cy in rel:  # distance to the adjacent edges
        assert min(cx, 100 - cx) == A(10) and min(cy, 60 - cy) == A(10)

    # dimensions: re-measured from definition points
    from agentcad.validate.features import measure_dimension
    meas = sorted((k, round(m, 6)) for k, m in (measure_dimension(d) for d in msp.query("DIMENSION")))
    for need in [("linear", 100), ("linear", 60), ("diameter", 8), ("linear", 10), ("linear", 80), ("linear", 40)]:
        assert need in meas, (need, meas)


def test_runtime_validator_report(rt, plate):
    v = ok(rt.validate_drawing(plate, detail=True))["validation"]
    assert v["requirements_source"] == "stored_part_spec"
    assert v["passed"], v["issues"]
    ids = {r["id"]: r for r in v["requirements"]}
    for k in ("outline", "hole.bl", "hole.br", "hole.tr", "hole.tl", "hole_count", "dim.width", "dim.height",
              "dim.holes0.dia", "dim.holes0.x", "dim.holes0.y"):
        assert ids[k]["status"] == "pass"
        assert {"expected", "actual", "deviation", "tolerance"} <= set(ids[k])


def test_export_and_reread_consistency(rt, ws, plate):
    from agentcad.model import entity_to_dict
    for ver in ("R2000", "R2018"):
        r = ok(rt.export_drawing(plate, f"out_{ver}.dxf", "dxf", ver))
        assert r["reread_ok"]
        a = {e.dxf.handle: entity_to_dict(e) for e in reread(ws, plate).modelspace()}
        b = {e.dxf.handle: entity_to_dict(e) for e in reread(ws, f"out_{ver}.dxf").modelspace()}
        assert a == b
    r12 = ok(rt.export_drawing(plate, "out_r12.dxf", "dxf", "R12"))
    d12 = reread(ws, "out_r12.dxf")
    assert d12.dxfversion == "AC1009"
    assert len(d12.modelspace().query("POLYLINE")) >= 1  # LWPOLYLINE converted, not silently dropped
    assert len(d12.modelspace().query("CIRCLE")) == 4
    svg = ok(rt.export_drawing(plate, "plate.svg", "svg"))
    assert (ws / "plate.svg").read_text("utf-8").lstrip().startswith("<svg") or "<svg" in (ws / "plate.svg").read_text("utf-8")[:500]
    assert svg["bytes"] > 1000


def test_spec_without_units_is_rejected(rt, ws):
    """Units are never assumed: the same task without a unit is refused and nothing is written."""
    spec = dict(PLATE_SPEC)
    spec.pop("units")
    r = rt.draw_from_spec(spec, "nounit.dxf")
    assert not r["ok"] and r["error"]["category"] == "spec"
    assert any(i["code"] == "UNITS_UNDEFINED" for i in r["error"]["details"]["issues"])
    assert not (ws / "nounit.dxf").exists()
