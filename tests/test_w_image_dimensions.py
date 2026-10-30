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


@pytest.mark.parametrize("horizontal,colour", [(False, "black"), (True, "purple")])
def test_raster_crossings_are_independent_of_guessed_external_arrow_endpoints(ws, horizontal, colour):
    image = Image.new("RGB", (240, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.line((40, 20, 40, 120), fill=colour)
    for y in (60, 80):
        draw.line((40, y, 180, y), fill=colour)
    draw.polygon([(40, 60), (37, 50), (43, 50)], fill=colour)
    draw.polygon([(40, 80), (37, 90), (43, 90)], fill=colour)
    # The caller mistakes the outside arrow's base for its tip; all supplied points agree.
    line, surfaces = [[40, 50], [40, 80]], [[140, 50], [140, 80]]
    if horizontal:
        image = image.transpose(Image.Transpose.TRANSPOSE)
        line, surfaces = [[p[::-1] for p in group] for group in (line, surfaces)]
    image.save(ws / "section.png")
    readings = [{"id": "gap", "view": "detail", "value": 9, "line": line,
                 "surfaces": [{"name": name, "point": point} for name, point in zip(("a", "b"), surfaces)]}]
    result = inspect(ws, readings)
    evidence = result["dimension_evidence"]
    assert evidence["consistent"] and not evidence["semantics_verified"]
    probe = evidence["checks"][0]["raster_probe"]
    assert probe["status"] == "candidates"
    assert [c["range_px"] for c in probe["crossings"]] == [[60, 60], [80, 80]]
    assert "OUTSIDE arrows" in evidence["raster_probe_note"] and "note" not in probe
    # Crop offsets and preview rotation must not change independent source observations.
    box = [20, 10, 200, 130] if not horizontal else [10, 20, 130, 200]
    cropped = inspect(ws, readings, region=box, rotate=90)
    assert cropped["dimension_evidence"]["checks"][0]["raster_probe"]["crossings"] == probe["crossings"]


def test_unreadable_and_overlong_raster_probes_do_not_certify_endpoints(ws):
    image = Image.new("RGB", (4500, 80), "white")
    image.save(ws / "section.png")
    row = {"id": "span", "view": "blank", "value": 100, "line": [[10, 20], [30, 20]],
           "surfaces": [{"name": "a", "point": [10, 40]}, {"name": "b", "point": [30, 40]}]}
    evidence = inspect(ws, [row])["dimension_evidence"]
    assert evidence["checks"][0]["raster_probe"]["status"] == "low_contrast"
    row["line"][1][0] = row["surfaces"][1]["point"][0] = 4400
    evidence = inspect(ws, [row])["dimension_evidence"]
    assert evidence["checks"][0]["raster_probe"]["status"] == "region_too_long"
    assert evidence["semantics_verified"] is False


def test_ink_beside_the_dimension_line_is_not_a_crossing(ws):
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).line((20, 50, 120, 50), fill="black")  # 10 px off the dimension line at y=40
    image.save(ws / "section.png")
    row = {"id": "span", "view": "detail", "value": 10, "line": [[20, 40], [120, 40]],
           "surfaces": [{"name": "a", "point": [20, 60]}, {"name": "b", "point": [120, 60]}]}
    probe = inspect(ws, [row])["dimension_evidence"]["checks"][0]["raster_probe"]
    assert probe["status"] == "no_crossings_detected" and probe["crossings"] == []


def test_the_raster_note_is_stated_once_per_call(ws):
    readings = section(ws / "section.png")
    readings += [dict(copy.deepcopy(readings[0]), id=f"again{n}") for n in range(9)]
    evidence = inspect(ws, readings)["dimension_evidence"]
    assert len(evidence["checks"]) == 12
    assert json.dumps(evidence).count("OUTSIDE arrows") == 1


@pytest.mark.parametrize("transpose", [False, True])
@pytest.mark.parametrize("ink", [0, 128])
def test_sparse_one_pixel_witnesses_survive_the_background_majority(ws, transpose, ink):
    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    colour = (ink, ink, ink)
    draw.line((100, 100, 900, 100), fill=colour)
    for x in (100, 900):
        draw.line((x, 70, x, 160), fill=colour)
    line, surfaces = [[100, 100], [900, 100]], [[100, 160], [900, 160]]
    if transpose:
        image = image.transpose(Image.Transpose.TRANSPOSE)
        line, surfaces = [[p[::-1] for p in group] for group in (line, surfaces)]
    image.save(ws / "section.png")
    readings = [{"id": "long", "view": "detail", "value": 80, "line": line,
                 "surfaces": [{"name": name, "point": point} for name, point in zip(("a", "b"), surfaces)]}]
    evidence = inspect(ws, readings)["dimension_evidence"]
    probe = evidence["checks"][0]["raster_probe"]
    assert probe["status"] == "candidates"
    assert [c["range_px"] for c in probe["crossings"]] == [[100, 100], [900, 900]]
    assert evidence["semantics_verified"] is False


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
    # The first reading's D1 marker sits where Pillow itself moves that source pixel.
    probe = Image.new("L", (300, 160), 0)
    probe.putpixel((20, 30), 255)
    moved = probe.rotate(-rotation, expand=True).resize((width, height), Image.Resampling.BILINEAR)
    px, py = max(((u, v) for u in range(width) for v in range(height)), key=moved.getpixel)
    marked = result["panels"][1]
    assert marked["size"] == panel["size"]

    def marker_green(origin):
        window = output.crop((origin[0]+px-6, origin[1]+py-6, origin[0]+px+7, origin[1]+py+7)).convert("RGB")
        data = window.tobytes()
        return sum(abs(r-0x14) + abs(g-0x6c) + abs(b-0x43) < 60 for r, g, b in zip(data[::3], data[1::3], data[2::3]))

    assert marker_green(marked["origin"]) >= 10 and marker_green(panel["origin"]) == 0


@pytest.mark.parametrize("change", ["duplicate", "outside", "nonfinite", "diagonal", "unknown", "bad_value",
                                  "huge_value", "huge_coordinate", "too_many", "bad_unit", "surface_field",
                                  "same_surface", "short_line"])
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
    if change == "huge_value": readings[0]["value"] = 10**1000
    if change == "huge_coordinate": readings[0]["line"][0][0] = 10**1000
    if change == "too_many": readings += [dict(copy.deepcopy(readings[0]), id=f"x{n}") for n in range(10)]
    if change == "bad_unit": readings[0]["unit"] = "ft"
    if change == "surface_field": readings[0]["surfaces"][0]["role"] = "datum"
    if change == "same_surface": readings[0]["surfaces"][1]["name"] = readings[0]["surfaces"][0]["name"]
    if change == "short_line": readings[0]["line"][1] = [20, 30.5]
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
    readings_file = ws.parent / "readings.json"  # outside the read-only workspace
    readings_file.write_text(encoded, "utf-8")
    from_file = subprocess.run([sys.executable, "-m", "agentcad.cli", "--root", str(ws), "--read-only", "image",
                                "section.png", "--dimensions-file", str(readings_file), "--max-size", "600"],
                               capture_output=True, text=True, check=True)
    assert json.loads(from_file.stdout)["dimension_evidence"] == cli["dimension_evidence"]

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
