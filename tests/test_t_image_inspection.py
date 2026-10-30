"""Magnify public drawing inputs without modifying them or escaping the workspace."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from io import BytesIO
import json
import math
import os
import subprocess
import sys

from PIL import Image
import pytest

from agentcad import images
from agentcad.backends import freecad
from agentcad.policy import Policy
from agentcad.service import Runtime


def drawing(path):
    image = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    image.paste((0, 0, 255, 255), (20, 10, 60, 30))
    image.save(path)


def decode(result):
    assert result["ok"], result
    return Image.open(BytesIO(base64.b64decode(result["image_base64"])))


def test_crop_magnifies_exact_region_on_white_without_writes(ws):
    source = ws / "drawing.png"
    drawing(source)
    original = source.read_bytes()
    runtime = Runtime(Policy(root=ws, read_only=True))
    result = runtime.inspect_image("drawing.png", [20, 10, 100, 50], 160)
    preview = decode(result)
    assert result["source_size"] == [120, 80] and result["region"] == [20, 10, 100, 50]
    assert result["preview_size"] == [160, 80] and result["pixel_scale"] == 2
    assert preview.getpixel((10, 10)) == (0, 0, 255)
    assert preview.getpixel((150, 70)) == (255, 255, 255)
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() == original and list(ws.iterdir()) == [source]


def test_overview_and_exif_rotation_share_displayed_coordinates(ws):
    source = ws / "rotated.jpg"
    image = Image.new("RGB", (40, 80), "white")
    exif = image.getexif()
    exif[274] = 6  # display 90 degrees clockwise
    image.save(source, exif=exif)
    runtime = Runtime(Policy(root=ws))
    overview = runtime.inspect_image("rotated.jpg", max_size=80)
    assert decode(overview).size == (80, 40)
    assert overview["source_size"] == [80, 40] and overview["region"] == [0, 0, 80, 40]
    crop = runtime.inspect_image("rotated.jpg", [40, 0, 80, 40], 64)
    assert decode(crop).size == (64, 64)


@pytest.mark.parametrize("region", [[-1, 0, 10, 10], [0, 0, 121, 80], [10, 10, 10, 20],
                                    [0, 0, 10], [0, 0, 10.5, 20], [False, 0, 10, 20]])
def test_invalid_regions_are_rejected_without_silent_clipping(ws, region):
    drawing(ws / "drawing.png")
    result = Runtime(Policy(root=ws)).inspect_image("drawing.png", region)
    assert result["error"]["code"] == "BAD_IMAGE_REGION"


def test_workspace_boundary_and_invalid_image(ws):
    runtime = Runtime(Policy(root=ws))
    outside = ws.parent / "outside.png"
    drawing(outside)
    assert runtime.inspect_image(str(outside))["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    (ws / "bad.png").write_bytes(b"not an image")
    assert runtime.inspect_image("bad.png")["error"]["code"] == "IMAGE_READ_FAILED"
    drawing(ws / "drawing.png")
    assert runtime.inspect_image("drawing.png", max_size=0)["error"]["code"] == "BAD_IMAGE_SIZE"


def test_input_and_output_budgets(ws, monkeypatch):
    drawing(ws / "drawing.png")
    runtime = Runtime(Policy(root=ws))
    with monkeypatch.context() as patch:
        patch.setattr(images, "MAX_INPUT_BYTES", 10)
        assert runtime.inspect_image("drawing.png")["error"]["code"] == "IMAGE_TOO_LARGE"
    with monkeypatch.context() as patch:
        patch.setattr(images, "MAX_PIXELS", 100)
        assert runtime.inspect_image("drawing.png")["error"]["code"] == "IMAGE_TOO_LARGE"
    monkeypatch.setattr(images, "MAX_PREVIEW_BYTES", 10)
    assert runtime.inspect_image("drawing.png")["error"]["code"] == "IMAGE_PREVIEW_TOO_LARGE"


def test_cli_image_uses_the_same_read_only_crop(ws):
    drawing(ws / "drawing.png")
    result = subprocess.run([sys.executable, "-m", "agentcad.cli", "--root", str(ws), "--read-only", "image",
                             "drawing.png", "--region", "[20,10,100,50]", "--max-size", "160"],
                            capture_output=True, text=True, check=True)
    assert decode(json.loads(result.stdout)).size == (160, 80)


def test_mcp_returns_metadata_and_inline_image(ws):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    drawing(ws / "drawing.png")

    async def run():
        env = {**os.environ, "AGENTCAD_ROOT": str(ws), "AGENTCAD_READ_ONLY": "1", "AGENTCAD_VIEWER": "0"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                return await client.call_tool("inspect_image", {"path": "drawing.png", "region": [20, 10, 100, 50],
                                                                "max_size": 160})
    result = asyncio.run(run())
    assert [block.type for block in result.content] == ["text", "image"]
    metadata = json.loads(result.content[0].text)
    assert metadata["ok"] and "image_base64" not in metadata
    assert result.content[1].mimeType == "image/png"
    assert Image.open(BytesIO(base64.b64decode(result.content[1].data))).size == (160, 80)


@pytest.mark.skipif(not freecad.available(), reason="FreeCAD not installed")
def test_native_pocket_and_pad_honor_opposite_face_levels(ws):
    """Separate cut depth, remaining wall and boss extension: bbox/hole count alone misses this."""
    runtime = Runtime(Policy(root=ws))
    result = runtime.apply_operations("layered.FCStd", [
        {"op": "add_sketch", "plane": "XY", "shapes": [
            {"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}]},
        {"op": "pad", "sketch": "$0", "length": 4},
        {"op": "add_sketch", "plane": "XY", "offset": 4, "shapes": [
            {"type": "rectangle", "center": [0, 0], "width": 10, "height": 10}]},
        {"op": "pocket", "sketch": "$2", "depth": 1.5},
        {"op": "add_sketch", "plane": "XY", "offset": 0, "shapes": [
            {"type": "circle", "center": [0, 0], "radius": 3}]},
        {"op": "pad", "sketch": "$4", "length": 1.5, "reversed": True},
        {"op": "add_sketch", "plane": "XY", "offset": 4, "shapes": [
            {"type": "circle", "center": [0, 0], "radius": 1}]},
        {"op": "pocket", "sketch": "$6", "through_all": True},
    ], create={"units": "mm"})
    assert result["ok"], result
    shape = result["validation"]["shape"]
    assert shape["bbox"] == [[-10, -10, -1.5], [10, 10, 4]]
    assert shape["volume"] == pytest.approx(20 * 20 * 4 - 10 * 10 * 1.5 + math.pi * 3**2 * 1.5 - math.pi * 4)
