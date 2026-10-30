"""Local face relationships must be checked on saved geometry, not parameter names or bbox alone."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys

import pytest

from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.service import Runtime

pytestmark = pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed")


def build_plate(runtime, name="plate.FCStd", thickness=6, boss=2, plane="XY"):
    result = runtime.apply_operations(name, [
        {"op": "set_parameters", "params": {"NominalBossExtension": 2}},
        {"op": "add_sketch", "plane": plane, "shapes": [
            {"type": "rectangle", "center": [0, 0], "width": 20, "height": 16}]},
        {"op": "pad", "sketch": "$1", "length": thickness},
        {"op": "add_sketch", "plane": plane, "offset": thickness, "shapes": [
            {"type": "rectangle", "center": [0, 0], "width": 16, "height": 12}]},
        {"op": "pocket", "sketch": "$3", "depth": 2},
        {"op": "add_sketch", "plane": plane, "shapes": [
            {"type": "circle", "center": [x, 0], "radius": 2} for x in [-5, 5]]},
        {"op": "pad", "sketch": "$5", "length": boss, "reversed": True},
    ], create={"units": "mm"})
    assert result["ok"], result
    return result


@pytest.mark.parametrize("plane,axis,bottom", [("XY", "z", "bottom"), ("YZ", "x", "left")])
def test_final_plane_levels_and_coplanar_boss_family_are_measured_read_only(ws, plane, axis, bottom):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime, plane=plane)
    source = ws / "plate.FCStd"
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    reader = Runtime(Policy(root=ws, read_only=True))
    result = reader.measure_entities("plate.FCStd", {"kind": "planar_levels", "axis": axis})
    assert result["ok"] and result["units"] == "mm" and result["of"] == "Body", result
    levels = result["measurements"][0]["levels"]
    assert [x["position"] for x in levels] == [-2, 0, 4, 6]
    assert len(levels[0]["faces"]) == 2
    result = reader.measure_entities("plate.FCStd", {
        "kind": "face_distance", "from": {"normal": f"-{axis}", axis: 0}, "to": bottom})
    measured = result["measurements"][0]
    assert measured["distance"] == pytest.approx(2)
    assert measured["signed_distance"] == pytest.approx(2)
    assert len(measured["to"]["faces"]) == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_local_validation_catches_wrong_stack_despite_correct_bbox_and_parameter(ws):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime, thickness=5, boss=3)
    common = [{"type": "bbox", "size": [20, 16, 8]},
              {"type": "parameter", "name": "NominalBossExtension", "value": 2}]
    assert runtime.validate_drawing("plate.FCStd", requirements=common)["validation"]["passed"]
    actual_gap = {"type": "face_distance", "from": {"normal": "-z", "z": 0}, "to": "bottom", "value": 2}
    report = runtime.validate_drawing("plate.FCStd", requirements=common + [actual_gap], detail=True)["validation"]
    assert not report["passed"]
    assert report["requirements"][-1]["actual"] == 3
    assert report["requirements"][-1]["expected"] == 2


def test_invalid_or_ambiguous_measurements_fail_explicitly(ws):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime)
    cases = [
        ({"kind": "face_distance", "from": {"normal": "+z"}, "to": "bottom"}, "AMBIGUOUS_PLANES"),
        ({"kind": "face_distance", "from": "left", "to": "bottom"}, "NOT_PARALLEL"),
        ({"kind": "face_distance", "from": {"type": "cylinder"}, "to": "bottom"}, "NOT_PLANAR"),
        ({"kind": "face_distance", "from": "Face0", "to": "bottom"}, "SELECTOR_EMPTY"),
        ({"kind": "face_distance", "from": [], "to": "bottom"}, "SELECTOR_EMPTY"),
        ({"kind": "face_distance", "from": "top"}, "BAD_MEASUREMENT"),
        ({"kind": "planar_levels", "typo": 1}, "BAD_MEASUREMENT"),
    ]
    for target, expected in cases:
        result = runtime.measure_entities("plate.FCStd", target)
        assert not result["ok"] and result["error"]["code"] == expected, result
    report = runtime.validate_drawing("plate.FCStd", requirements=[
        {"type": "face_distance", "from": "left", "to": "top", "value": 2}], detail=True)["validation"]
    assert not report["passed"] and report["requirements"][0]["error"]["code"] == "NOT_PARALLEL"
    report = runtime.validate_drawing("plate.FCStd", requirements=[
        {"type": "face_distance", "from": [], "to": "top", "value": 2}], detail=True)["validation"]
    assert not report["passed"] and report["requirements"][0]["error"]["code"] == "SELECTOR_EMPTY"
    report = runtime.validate_drawing("plate.FCStd", requirements=[
        {"type": "face_distance", "from": "top", "to": "bottom", "value": 8, "tolerance": "not a number"}
    ], detail=True)["validation"]
    assert not report["passed"] and "Invalid face_distance" in report["requirements"][0]["message"]


def test_dxf_filter_cannot_silently_return_feature_history_for_a_part(ws):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime)
    for wrong in [{"type": "face"}, {"kind": "features", "selector": {"type": "plane"}}]:
        result = runtime.inspect_entities("plate.FCStd", filter=wrong)
        assert not result["ok"] and result["error"]["code"] == "BAD_FILTER"
    result = runtime.inspect_entities("plate.FCStd", filter={"kind": "faces", "selector": {"normal": "+z"}})
    assert result["ok"] and result["kind"] == "faces"
    assert all(x["name"].startswith("Face") for x in result["entities"])


def test_camera_metadata_preserves_front_side_and_top_correspondence(ws):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime)
    result = runtime.export_drawing("plate.FCStd", "views.png", "png", views=["front", "left", "top"], image_size=128)
    assert result["ok"], result
    frames = {x["view"]: x for x in result["camera_frames"]}
    assert frames["front"]["screen_right"] == [1, 0, 0]
    assert frames["front"]["screen_up"] == [0, 0, 1]
    assert frames["left"]["screen_right"] == [0, -1, 0]
    assert frames["left"]["screen_up"] == [0, 0, 1]
    assert frames["top"]["screen_right"] == [1, 0, 0]
    assert frames["top"]["screen_up"] == [0, 1, 0]
    compared = runtime.export_drawing("plate.FCStd", "comparison.png", "png", views=["front", "left", "top"],
                                      image_size=128, reference="views.png")
    assert compared["ok"], compared
    assert compared["camera_frames"] == result["camera_frames"]
    assert "shape" not in compared  # reference comparisons retain the compact upstream result


def test_cli_and_mcp_measure_real_saved_geometry(ws):
    runtime = Runtime(Policy(root=ws))
    build_plate(runtime)
    target = {"kind": "face_distance", "from": "top", "to": "bottom"}
    process = subprocess.run([sys.executable, "-m", "agentcad.cli", "--root", str(ws), "--read-only",
                              "measure", "plate.FCStd", "--target", json.dumps(target)],
                             capture_output=True, text=True, check=True)
    assert json.loads(process.stdout)["measurements"][0]["distance"] == pytest.approx(8)

    async def call():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = {**os.environ, "AGENTCAD_ROOT": str(ws), "AGENTCAD_READ_ONLY": "1", "AGENTCAD_VIEWER": "0"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                return await client.call_tool("measure_entities", {"path": "plate.FCStd", "target": target})
    reply = asyncio.run(call())
    result = json.loads(reply.content[0].text)
    assert result["ok"] and result["measurements"][0]["distance"] == pytest.approx(8)
