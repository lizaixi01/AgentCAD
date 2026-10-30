from copy import deepcopy

import ezdxf

from agentcad.service import Runtime


def test_pid_reader_reconstructs_connectivity_and_detects_moved_equipment(rt, blank, ws):
    spec = {
        "equipment": [
            {"id": "P1", "symbol": "centrifugal_pump", "x": 0, "y": 0},
            {"id": "P2", "symbol": "centrifugal_pump", "x": 50, "y": 20},
        ],
        "lines": [{"from": "P1.discharge", "to": "P2.suction", "number": "DN50-ABC"}],
    }
    result = rt.apply_operations(blank, [{"op": "draw_pid", "spec": spec}])
    assert result["ok"], result
    read = Runtime(rt.policy).read_engineering(blank, "pid")
    assert read["graph"]["stats"] == {"dangling": 0, "confidence_min": 1.0}
    assert read["line_list"][0]["line_number"] == "DN50-ABC"
    doc = ezdxf.readfile(ws / blank)
    doc.modelspace().query("INSERT")[1].dxf.insert = (100, 100)
    doc.saveas(ws / blank)
    after = Runtime(rt.policy).read_engineering(blank, "pid")
    assert after["graph"]["stats"]["dangling"] == 1
    assert after["critique"]
    before = (ws / blank).read_bytes()
    broken = deepcopy(spec)
    broken["lines"][0]["to"] = "MISSING.suction"
    assert not rt.apply_operations(blank, [{"op": "draw_pid", "spec": broken}])["ok"]
    assert (ws / blank).read_bytes() == before


def test_foreign_network_uses_geometry_sizes_and_missing_tag_uncertainty(rt, ws):
    for filename in ["pid.dxf", "layout.dxf"]:
        doc = ezdxf.new(units=4)
        for tag, x in [("TK-1", 0), ("TK-2", 5000)]:
            doc.modelspace().add_circle((x, 0), 100)
            doc.modelspace().add_text(tag, dxfattribs={"insert": (x, 0), "height": 250})
        if filename == "pid.dxf":
            doc.layers.add("processpipe")
            doc.modelspace().add_line((100, 0), (4900, 0), dxfattribs={"layer": "processpipe"})
            doc.modelspace().add_text("DN50", dxfattribs={"insert": (2500, 300), "height": 250})
        doc.saveas(ws / filename)
    report = rt.plant_takeoff("pid.dxf", "layout.dxf")
    assert report["ok"], report
    run = report["pipe"]["runs"][0]
    assert (run["status"], run["layout_m"], run["diameters"]) == ("A", 5, ["DN50"])
    doc = ezdxf.readfile(ws / "layout.dxf")
    for e in list(doc.modelspace().query("TEXT")):
        if e.dxf.text == "TK-2":
            doc.modelspace().delete_entity(e)
    doc.saveas(ws / "layout.dxf")
    run = rt.plant_takeoff("pid.dxf", "layout.dxf")["pipe"]["runs"][0]
    assert run["status"] == "C" and run["layout_m"] is None


def test_rooms_are_recomputed_after_wall_geometry_changes(rt, blank, ws):
    spec = {
        "walls": [
            {
                "id": "outer",
                "axis": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
                "closed": True,
                "thickness": 200,
            }
        ],
        "rooms": [{"id": "living", "number": "01", "name": "Living", "at": [2000, 2000]}],
    }
    result = rt.apply_operations(blank, [{"op": "draw_arch_plan", "spec": spec}])
    assert result["ok"], result
    before = rt.read_engineering(blank, "architecture")
    assert before["rooms"][0]["detected_area"] == 4800 * 3800
    doc = ezdxf.readfile(ws / blank)
    wall = next(
        e
        for e in doc.modelspace().query('LWPOLYLINE[layer=="ARCH_WALL"]')
        if min(p[0] for p in e.get_points("xy")) == 4900
    )
    wall.translate(-100, 0, 0)
    doc.saveas(ws / blank)
    after = rt.read_engineering(blank, "architecture")
    assert after["rooms"][0]["detected_area"] == 4700 * 3800
    assert after["critique"][0]["code"] == "ROOM_AREA_MISMATCH"


def test_mechanical_bom_and_balloons_detect_deleted_fastener(rt, blank, ws):
    spec = {
        "sheet": {"title": "Test", "drawing_no": "TEST-2"},
        "fasteners": [
            {"part": "hex_bolt", "size": "M8", "length": 30, "insert": [60, 90]},
            {"part": "hex_bolt", "size": "M8", "length": 30, "insert": [100, 90]},
        ],
    }
    result = rt.apply_operations(blank, [{"op": "draw_mechanical_assembly", "spec": spec}])
    assert result["ok"], result
    report = rt.read_engineering(blank, "mechanical")
    assert report["ok"] and report["critique"] == []
    assert report["bom"][0]["quantity"] == 2
    doc = ezdxf.readfile(ws / blank)
    doc.modelspace().delete_entity(doc.entitydb[report["bom"][0]["handles"][0]])
    doc.saveas(ws / blank)
    report = rt.read_engineering(blank, "mechanical")
    assert {i["code"] for i in report["critique"]} >= {"BOM_MISMATCH", "BALLOON_LINK_MISMATCH"}


def test_changed_visible_room_label_cannot_keep_clean_quality(rt, blank, ws):
    spec = {
        "walls": [
            {
                "id": "outer",
                "axis": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
                "closed": True,
                "thickness": 200,
            }
        ],
        "rooms": [{"id": "living", "number": "01", "name": "Living", "at": [2000, 2000]}],
    }
    assert rt.apply_operations(blank, [{"op": "draw_arch_plan", "spec": spec}])["ok"]
    report = rt.read_engineering(blank, "architecture")
    doc = ezdxf.readfile(ws / blank)
    doc.entitydb[report["rooms"][0]["handle"]].dxf.text = "01 Living 999.00 m2"
    doc.saveas(ws / blank)
    report = Runtime(rt.policy).read_engineering(blank, "architecture")
    assert report["rooms"][0]["detected_area"] == 4800 * 3800
    assert report["rooms"][0]["label"] == "01 Living 999.00 m2"
    assert "ROOM_LABEL_MISMATCH" in {i["code"] for i in report["critique"]}
    assert report["quality_score"] < 90


def test_deleted_last_part_invalidates_retained_bom_and_balloon(rt, blank, ws):
    spec = {"fasteners": [{"part": "hex_bolt", "size": "M8", "length": 30, "insert": [60, 90]}]}
    assert rt.apply_operations(blank, [{"op": "draw_mechanical_assembly", "spec": spec}])["ok"]
    report = rt.read_engineering(blank, "mechanical")
    doc = ezdxf.readfile(ws / blank)
    doc.modelspace().delete_entity(doc.entitydb[report["bom"][0]["handles"][0]])
    doc.saveas(ws / blank)
    report = Runtime(rt.policy).read_engineering(blank, "mechanical")
    assert report["bom"] == []
    assert {i["code"] for i in report["critique"]} >= {
        "BOM_MISMATCH",
        "BALLOON_LINK_MISMATCH",
        "EMPTY_ASSEMBLY",
    }
    assert report["quality_score"] < 90
