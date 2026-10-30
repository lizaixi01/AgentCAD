"""Dimension numbers need source endpoints; a valid equation alone cannot certify a reading."""
from __future__ import annotations

import asyncio
import base64
import copy
from io import BytesIO
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime


def section(path):
    image = Image.new("RGB", (300, 160), "white")
    draw = ImageDraw.Draw(image)
    for y in (30, 50, 85, 105):
        draw.line((80, y, 230, y), fill="blue")
    readings = []
    for identifier, value, x, start, end, names in [
        ("total", 15, 20, 30, 105, ("upper", "end")),
        ("cut", 4, 40, 30, 50, ("upper", "floor")),
        ("extension", 4, 60, 85, 105, ("underside", "end")),
    ]:
        draw.line((x, start, x, end), fill="purple")
        for y in (start, end):
            draw.line((x, y, 150, y), fill="purple")
        readings.append({"id": identifier, "view": "section", "value": value, "unit": "mm",
                         "line": [[x, start], [x, end]], "surfaces": [
                             {"name": name, "point": [150, y]} for name, y in zip(names, (start, end))]})
    image.save(path)
    return readings


def inspect(ws, readings, **kw):
    return Runtime(Policy(root=ws, read_only=True)).inspect_image("section.png", dimensions=readings, **kw)


def test_connected_dimensions_derive_unlabelled_gap_without_model_parameters(ws):
    source = ws / "section.png"
    readings = section(source)
    before = source.read_bytes()
    result = inspect(ws, readings)
    assert result["ok"], result
    evidence = result["dimension_evidence"]
    assert evidence["consistent"] and not evidence["semantics_verified"]
    levels = evidence["groups"][0]["components"][0]["levels_mm"]
    assert levels == {"upper": 0, "end": 15, "underside": 11, "floor": 4}
    assert levels["underside"]-levels["floor"] == 7
    assert source.read_bytes() == before and list(ws.iterdir()) == [source]


def test_same_number_on_wrong_surfaces_is_not_an_acceptable_mapping(ws):
    readings = section(ws / "section.png")
    readings[2]["surfaces"] = [{"name": "floor", "point": [150, 50]},
                               {"name": "underside", "point": [150, 85]}]
    result = inspect(ws, readings)
    assert result["ok"]  # an inspectable hypothesis, not an I/O failure
    evidence = result["dimension_evidence"]
    assert not evidence["consistent"] and not evidence["checks"][2]["aligned"]
    assert evidence["checks"][2]["endpoint_errors_px"] == [-35, -20]
    assert evidence["groups"][0]["components"] == []


def test_consistent_anchors_still_do_not_verify_their_semantics(ws):
    readings = section(ws / "section.png")
    # Callers can invent surface names; alignment must not claim that those names are recognized.
    readings[1]["surfaces"][1]["name"] = "invented_role"
    evidence = inspect(ws, readings)["dimension_evidence"]
    assert evidence["consistent"] and evidence["semantics_verified"] is False
    assert "not pixels/arrow recognition or OCR" in evidence["note"]


def test_unit_conversion_reversed_endpoint_order_and_disconnected_components(ws):
    readings = section(ws / "section.png")
    readings[0].update(value=1.5, unit="cm")
    readings[0]["line"].reverse()
    readings[0]["surfaces"].reverse()
    extra = {"id": "separate", "view": "section", "value": 4, "line": [[250, 30], [250, 50]],
             "surfaces": [{"name": "other_a", "point": [260, 30]}, {"name": "other_b", "point": [260, 50]}]}
    evidence = inspect(ws, readings+[extra])["dimension_evidence"]
    assert evidence["consistent"]
    components = evidence["groups"][0]["components"]
    assert len(components) == 2
    assert components[0]["levels_mm"]["underside"] == 11
    assert components[1]["levels_mm"] == {"other_a": 0, "other_b": 4}


def test_cycles_scale_conflicts_and_reused_surface_levels_are_reported(ws):
    readings = section(ws / "section.png")
    duplicate = copy.deepcopy(readings[0])
    duplicate.update(id="contradiction", value=16)
    result = inspect(ws, readings+[duplicate])["dimension_evidence"]
    assert not result["consistent"]
    assert any("cycle" in text for text in result["groups"][0]["issues"])
    readings[1]["value"] = 100
    result = inspect(ws, readings)["dimension_evidence"]
    assert any("scales" in text for text in result["groups"][0]["issues"])
    readings = section(ws / "section.png")
    readings[1]["surfaces"][0]["point"][1] = 40
    readings[1]["line"][0][1] = 40
    result = inspect(ws, readings)["dimension_evidence"]
    assert any("same named surface" in text for text in result["groups"][0]["issues"])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_guide_and_evidence_keep_unmarked_source_and_original_coordinates(ws, rotation):
    readings = section(ws / "section.png")
    result = inspect(ws, readings, max_size=321, rotate=rotation)
    assert result["ok"], result
    output = Image.open(BytesIO(base64.b64decode(result["image_base64"])))
    assert max(output.size) <= 321
    panel = result["panels"][0]
    x, y = panel["origin"]
    width, height = panel["size"]
    raw_panel = output.crop((x, y, x+width, y+height))
    with Image.open(ws / "section.png") as source:
        expected = source.rotate(-rotation, expand=True).resize((width, height), Image.Resampling.LANCZOS)
    assert raw_panel.tobytes() == expected.tobytes()
    assert result["dimension_evidence"]["checks"][0]["line"] == [[20, 30], [20, 105]]
    assert result["dimension_evidence"]["groups"][0]["components"][0]["levels_mm"]["underside"] == 11
    guide = inspect(ws, [], max_size=321, rotate=rotation)
    assert guide["ok"] and guide["dimension_evidence"]["consistent"] is None


@pytest.mark.parametrize("change", ["duplicate", "outside", "nonfinite", "diagonal", "unknown", "bad_value"])
def test_invalid_anchor_inputs_fail_without_writing(ws, change):
    source = ws / "section.png"
    readings = section(source)
    before = source.read_bytes()
    if change == "duplicate": readings.append(copy.deepcopy(readings[0]))
    if change == "outside": readings[0]["line"][0][0] = 300
    if change == "nonfinite": readings[0]["surfaces"][0]["point"][0] = float("nan")
    if change == "diagonal": readings[0]["line"][1][0] = 100
    if change == "unknown": readings[0]["answer"] = "guess"
    if change == "bad_value": readings[0]["value"] = True
    result = inspect(ws, readings)
    assert not result["ok"] and result["error"]["code"] == "BAD_DIMENSION_EVIDENCE", result
    assert source.read_bytes() == before and list(ws.iterdir()) == [source]


def test_cli_and_real_mcp_share_dimension_evidence(ws):
    readings = section(ws / "section.png")
    encoded = json.dumps(readings)
    process = subprocess.run([sys.executable, "-m", "agentcad.cli", "--root", str(ws), "--read-only", "image",
                              "section.png", "--dimensions", encoded, "--max-size", "600"],
                             capture_output=True, text=True, check=True)
    cli = json.loads(process.stdout)

    async def call():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = {**os.environ, "AGENTCAD_ROOT": str(ws), "AGENTCAD_READ_ONLY": "1", "AGENTCAD_VIEWER": "0"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                return await client.call_tool("inspect_image", {"path": "section.png", "dimensions": readings,
                                                               "max_size": 600})
    response = asyncio.run(call())
    assert [block.type for block in response.content] == ["text", "image"]
    metadata = json.loads(response.content[0].text)
    assert metadata["dimension_evidence"] == cli["dimension_evidence"]
    assert metadata["source_sha256"] == cli["source_sha256"]
