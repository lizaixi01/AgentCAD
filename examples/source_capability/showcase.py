"""Reproduce original synthetic production examples, separate from the fixed v8 inputs.

Run with --native only when AutoCAD is available and no other CAD task is running.
The saved PDFs need a separate visual inspection; a structural pass is not that inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import ezdxf

from agentcad.policy import Policy
from agentcad.service import Runtime


MECHANICAL = {
    "sheet": {"title": "STEPPED SLEEVE AND END CAP", "drawing_no": "SC-2026-01", "drawn_by": "AgentCAD"},
    "parts": [
        {"name": "SLEEVE", "at": [130, 190], "views": ["front", "section"], "material": "steel",
         "segments": [{"length": 18, "d_outer": 48, "d_inner": 25},
                      {"length": 24, "d_outer": 60, "d_inner": 25},
                      {"length": 13, "d_outer": 42, "d_inner": 25}]},
        {"name": "CAP", "at": [345, 190], "views": ["front", "side"], "material": "steel",
         "segments": [{"length": 12, "d_outer": 70, "d_inner": 25}],
         "features": [{"kind": "hole_circle", "pcd": 52, "count": 6, "diameter": 6.6, "start_angle": 30}]},
    ],
    "fasteners": [
        {"part": "hex_bolt", "size": "M10", "length": 40, "insert": [60, 90]},
        {"part": "hex_nut", "size": "M10", "insert": [110, 90]},
        {"part": "washer", "size": "M10", "insert": [160, 90]},
    ],
}
ARCHITECTURE = {
    "sheet": {"scale": 50},
    "walls": [{"id": "outer", "axis": [[0,0],[11000,0],[11000,7000],[0,7000]], "closed": True, "thickness": 240},
              {"id": "partition", "axis": [[4200,0],[4200,7000]], "thickness": 200}],
    "rooms": [{"id": "office", "number": "11", "name": "Office", "at": [2100,4300]},
              {"id": "shop", "number": "12", "name": "Workshop", "at": [7400,4300]}],
    "openings": [{"id": "D11", "kind": "door", "wall": "outer", "offset": 1500, "width": 1000},
                 {"id": "D12", "kind": "door", "wall": "partition", "offset": 1500, "width": 900},
                 {"id": "W11", "kind": "window", "wall": "outer", "offset": 22000, "width": 1800}],
    "chains": {"sides": ["bottom", "left"]},
    "schedules": [{"kind": "rooms", "at": [12500,6500]}, {"kind": "doors", "at": [12500,4500]}],
}
PID = {
    "equipment": [{"id": "P-11", "symbol": "centrifugal_pump", "x": 20, "y": 30},
                  {"id": "V-11", "symbol": "vessel_vertical", "x": 160, "y": 45}],
    "valves": [{"id": "CV-11", "symbol": "control_valve", "actuator": "pneumatic", "x": 95, "y": 45}],
    "instruments": [{"id": "FC-11", "type": "panel", "x": 95, "y": 90}],
    "lines": [{"from": "P-11.discharge", "to": "CV-11.in", "number": "DN80-SUPPLY"},
              {"from": "CV-11.out", "to": "V-11.in", "number": "DN80-FEED"},
              {"from": "FC-11.signal", "to": "CV-11.signal", "class": "pneumatic"}],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rt = Runtime(Policy(root=args.out.absolute()))
    repo = Path(__file__).resolve().parents[2]
    report = {"source_commit": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
              "source_sha256": {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((repo / "src").rglob("*.py"))},
              "native": args.native, "calls": [], "checks": {}, "visual_review": "pending separate inspection"}
    def save():
        (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    def call(name, **kw):
        result = getattr(rt, name)(**kw)
        report["calls"].append({"tool": name, "arguments": kw, "result": result})
        save()
        assert result["ok"], result
        return result
    for domain, spec, op in [("mechanical", MECHANICAL, "draw_mechanical_assembly"),
                             ("architecture", ARCHITECTURE, "draw_arch_plan"), ("pid", PID, "draw_pid")]:
        path = domain + ".dxf"
        call("apply_operations", path=path, operations=[{"op": op, "spec": spec}], create={"units": "mm"})
        read = call("read_engineering", path=path, kind=domain)
        assert not read["critique"], read
        if domain == "mechanical":
            found = {p["name"]: p["measured"] for p in read["parts"]}
            assert found == {"SLEEVE": {"length":55, "diameter":60}, "CAP": {"length":12, "diameter":70}}
            holes = [c for c in read["circles"] if c["kind"] == "bolt_hole"]
            assert len(holes) == 6 and all(abs(h["diameter"] - 6.6) < 1e-8 for h in holes)
            assert len(read["bom"]) == 5 and all(r["quantity"] == 1 for r in read["bom"])
            # A model-space frame needs a fixed-scale paper layout. Auto-fit is
            # useful for inspection, but cannot substantiate a printed 1:1 label.
            placed = call("apply_operations", path=path, operations=[
                {"op":"create_layout", "name":"A3-1to1", "paper":"A3"},
                {"op":"add_viewport", "layout":"A3-1to1", "center":[210,148.5],
                 "view_center":[210,148.5], "width":420, "height":297, "scale":1},
                {"op":"add_text", "layout":"A3-1to1", "text":"A3 - 1:1", "insert":[24,278], "height":2.5}])
            assert placed["results"][1]["shows_all_model"]
        elif domain == "architecture":
            assert len(read["rooms"]) == 2 and len(read["schedules"]["doors"]) == 2
            assert {r["number"]: r["detected_area"] for r in read["rooms"]} == {"11":3980*6760, "12":6580*6760}
        else:
            assert read["graph"]["stats"]["dangling"] == 0
            assert [(r["line_class"], r["line_number"]) for r in read["line_list"]] == [
                ("process_major", "DN80-SUPPLY"), ("process_major", "DN80-FEED"), ("pneumatic", None)]
        call("deliver_drawing", path=path, output_dir=domain + "-delivery", formats=["dxf", "pdf", "svg", "json"])
        if args.native:
            call("export_drawing", path=path, output=domain + ".dwg", format="dwg")
            reopened = domain + "-native.dxf"
            call("import_drawing", source=domain + ".dwg", output=reopened)
            after = call("read_engineering", path=reopened, kind=domain)
            assert not after["critique"], after
            if domain == "mechanical":
                native_doc = ezdxf.readfile(args.out / reopened)
                sheet = native_doc.layouts.get("A3-1to1")
                assert abs(sheet.dxf_layout.dxf.paper_width - 420) < 1e-6
                assert abs(sheet.dxf_layout.dxf.paper_height - 297) < 1e-6
                viewport = next(v for v in sheet.query("VIEWPORT") if v.dxf.id > 1)
                assert abs(viewport.dxf.height / viewport.dxf.view_height - 1) < 1e-9
                assert tuple(viewport.dxf.center)[:2] == (210,148.5)
                assert tuple(viewport.dxf.view_center_point)[:2] == (210,148.5)
                assert any(t.dxf.text == "A3 - 1:1" and tuple(t.dxf.insert)[:2] == (24,278)
                           for t in sheet.query("TEXT"))
                report["checks"]["native_A3_page_viewport_1to1"] = "passed"
            audit = call("autocad_audit", path=reopened)
            assert audit["passed"] and audit["audit_errors"] == 0
        report["checks"][domain] = "passed"
        save()
        print(domain + " passed", flush=True)
    fit = call("standard_library", item="iso_fit", size="35 H7/g6")
    call("apply_operations", path="tolerance.dxf", create={"units":"mm"}, operations=[
        {"op":"add_circle", "center":[80,55], "diameter":35, "tag":"bore"},
        {"op":"add_diameter_dim", "target":"tag:bore", "text":"<> H7", "tag":"limit", "angle":0, "text_height":2.5,
         "tolerance":{"lower":fit["hole"]["lower"],"upper":fit["hole"]["upper"],"precision":3}},
        {"op":"add_text", "insert":[10,20], "text":"BORE 35 H7 / SHAFT g6 - dimensions in mm", "height":2.5},
        {"op":"create_layout", "name":"A4-1to1", "paper":"A4"},
        {"op":"add_viewport", "layout":"A4-1to1", "center":[148.5,105],
         "view_center":[75,45], "width":277, "height":190, "scale":1}])
    # Independent readback of native DIMENSION variables and displayed geometry.
    doc = ezdxf.readfile(args.out / "tolerance.dxf")
    dim = next(iter(doc.modelspace().query("DIMENSION")))
    assert dim.get_measurement() == 35 and dim.override().get("dimtp") == .025
    call("deliver_drawing", path="tolerance.dxf", output_dir="tolerance-delivery", formats=["dxf","pdf","svg"])
    if args.native:
        call("export_drawing", path="tolerance.dxf", output="tolerance.dwg", format="dwg")
        call("import_drawing", source="tolerance.dwg", output="tolerance-native.dxf")
        native_doc = ezdxf.readfile(args.out / "tolerance-native.dxf")
        native_dim = native_doc.modelspace().query("DIMENSION").first
        assert native_dim.get_measurement() == 35 and native_dim.override().get("dimtp") == .025
        assert native_dim.override().get("dimtfac") == .7 and native_dim.override().get("dimtolj") == 1
        audit = call("autocad_audit", path="tolerance-native.dxf")
        assert audit["passed"] and audit["audit_errors"] == 0
    report["checks"]["tolerance"] = "passed"
    save()


if __name__ == "__main__":
    main()
