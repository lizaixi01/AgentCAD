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


@pytest.mark.parametrize("rotate,expected_size,blue,white", [
    (90, (80, 160), (60, 10), (10, 150)),
    (180, (160, 80), (150, 60), (10, 10)),
    (270, (80, 160), (10, 150), (60, 10)),
])
def test_rotation_is_clockwise_after_source_coordinate_crop(ws, rotate, expected_size, blue, white):
    source = ws / "drawing.png"
    drawing(source)
    original = source.read_bytes()
    result = Runtime(Policy(root=ws, read_only=True)).inspect_image("drawing.png", [20, 10, 100, 50], 160, rotate)
    preview = decode(result)
    assert preview.size == expected_size
    assert preview.getpixel(blue) == (0, 0, 255) and preview.getpixel(white) == (255, 255, 255)
    assert result["region"] == [20, 10, 100, 50] and result["rotate"] == rotate
    assert source.read_bytes() == original


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
    assert runtime.inspect_image("drawing.png", rotate=45)["error"]["code"] == "BAD_IMAGE_ROTATION"


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
                             "drawing.png", "--region", "[20,10,100,50]", "--max-size", "160", "--rotate", "90"],
                            capture_output=True, text=True, check=True)
    assert decode(json.loads(result.stdout)).size == (80, 160)


@pytest.mark.parametrize("profile", ["full", "discovery"])
def test_mcp_returns_metadata_and_inline_image(ws, profile):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    drawing(ws / "drawing.png")

    async def run():
        env = {**os.environ, "AGENTCAD_ROOT": str(ws), "AGENTCAD_READ_ONLY": "1", "AGENTCAD_VIEWER": "0",
               "AGENTCAD_TOOL_PROFILE": profile}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                arguments = {"path": "drawing.png", "region": [20, 10, 100, 50], "max_size": 160, "rotate": 90}
                if profile == "discovery":
                    return await client.call_tool("call_tool", {"name":"inspect_image", "arguments":arguments})
                return await client.call_tool("inspect_image", arguments)
    result = asyncio.run(run())
    assert [block.type for block in result.content] == ["text", "image"], result
    metadata = json.loads(result.content[0].text)
    assert metadata["ok"] and "image_base64" not in metadata
    assert result.content[1].mimeType == "image/png"
    assert Image.open(BytesIO(base64.b64decode(result.content[1].data))).size == (80, 160)


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


@pytest.mark.parametrize("profile", ["full", "discovery"])
def test_png_export_preserves_inline_image_through_sdk(ws, monkeypatch, profile):
    """Mixed media must use MCP content, not a JSON output-model serializer."""
    from agentcad.mcp_server import build_server

    drawing(ws / "preview.png")
    monkeypatch.setattr(Runtime, "export_drawing", lambda *a, **kw: {"ok": True, "output": "preview.png"})
    server = build_server(Policy(root=ws), profile=profile)

    async def run():
        args = {"path": "part.FCStd", "output": "preview.png", "format": "png"}
        if profile == "discovery":
            return await server.call_tool("call_tool", {"name": "export_drawing", "arguments": args})
        return await server.call_tool("export_drawing", args)

    result = asyncio.run(run())
    assert [block.type for block in result] == ["text", "image"]
    assert json.loads(result[0].text)["ok"]
    assert Image.open(BytesIO(base64.b64decode(result[1].data))).size == (120, 80)


# --- measuring pixels with code ------------------------------------------------------------------------------

EXTENTS = """
blue = (image[:, :, 2] > 200) & (image[:, :, 0] < 50)
ys, xs = np.nonzero(blue)
print("x", xs.min() + origin[0], xs.max() + origin[0], "y", ys.min() + origin[1], ys.max() + origin[1])
"""


def scripted(ws):
    drawing(ws / "drawing.png")
    return Runtime(Policy(root=ws, allow_scripts=True, script_timeout=60))


def test_code_measures_source_pixels_and_sends_no_picture_for_numbers(ws):
    """The native BenchCAD runs measured drawings with numpy (silhouette extents, fitted ellipses) where the
    AgentCAD runs could only look at crops: code runs on the region at source resolution, in source coordinates."""
    runtime = scripted(ws)
    original = (ws / "drawing.png").read_bytes()
    r = runtime.inspect_image("drawing.png", [10, 5, 100, 50], 160, code=EXTENTS)
    assert r["ok"], r
    assert r["script"]["stdout"].split() == ["x", "20", "59", "y", "10", "29"]
    assert "image_base64" not in r and r["region"] == [10, 5, 100, 50]
    r = runtime.inspect_image("drawing.png", code="result = {'blue': ((image[:, :, 2] > 200) & (image[:, :, 0] < 50)).sum(), "
                                                  "'mean': image.mean(axis=(0, 1))}")
    assert r["ok"] and r["script"]["result"]["blue"] == 40 * 20 and len(r["script"]["result"]["mean"]) == 3
    r = runtime.inspect_image("drawing.png", code="result = np.zeros(100000)")
    assert r["script"]["result_truncated"] and len(r["script"]["result"]) == 16000
    assert (ws / "drawing.png").read_bytes() == original
    assert list(ws.iterdir()) == [ws / "drawing.png"]


def test_code_can_return_an_overlay_image(ws):
    runtime = scripted(ws)
    code = ("canvas = draw_line(image, (0, 0), (image.shape[1] - 1, 0), (255, 0, 0))\n"
            "canvas = draw_rect(canvas, (60, 30, 79, 39), (0, 255, 0))\n"
            "result = draw_text(draw_ellipse(canvas, (0, 0, 10, 10)), (40, 20), 'x')")
    r = runtime.inspect_image("drawing.png", [20, 10, 100, 50], 160, code=code)
    preview = decode(r)
    assert r["script"]["image"] == [80, 40] and preview.size == (160, 80)
    assert r["script"]["preview_scale"] == 2 and "pixel_scale" not in r  # the picture is the script's
    assert preview.getpixel((80, 0))[0] > 200 and preview.getpixel((30, 30)) == (0, 0, 255)
    assert preview.getpixel((158, 70))[1] > 200  # the green rectangle's right edge
    e = runtime.inspect_image("drawing.png", code="result = draw_line(5, (0, 0), (1, 1))")["error"]
    assert e["code"] == "SCRIPT_FAILED" and "canvas must be an image array" in e["message"]
    r = runtime.inspect_image("drawing.png", code="result = image[:, :, 2] > 200")  # a mask shows as an image
    assert decode(r).getpixel((30, 15)) == (255, 255, 255)


@pytest.mark.parametrize("code, error", [
    ("open('drawing.png')", "SCRIPT_REJECTED"),
    ("from PIL import Image\nImage.open('drawing.png')", "SCRIPT_REJECTED"),
    ("np.save('x.npy', image)", "SCRIPT_REJECTED"),
    ("import os", "SCRIPT_REJECTED"),
    # no PIL (screen and clipboard capture through ImageGrab or Image.core, ImageShow viewers, plugin file I/O), no
    # scipy (scipy.io, sparse.save_npz), no numpy file or download helpers, public or private
    ("from PIL import ImageGrab", "SCRIPT_REJECTED"),
    ("import PIL.ImageGrab", "SCRIPT_REJECTED"),
    ("from PIL import Image", "SCRIPT_REJECTED"),
    ("from PIL import ImageShow", "SCRIPT_REJECTED"),
    ("import scipy.io", "SCRIPT_REJECTED"),
    ("from scipy import sparse", "SCRIPT_REJECTED"),
    ("np.lib.format.open_memmap('x.npy', mode='w+', shape=(1,))", "SCRIPT_REJECTED"),
    ("np.lib._npyio_impl.zipfile_factory('x.zip', mode='w')", "SCRIPT_REJECTED"),
    ("from numpy.lib import _datasource", "SCRIPT_REJECTED"),
    ("np.lib.npyio.DataSource()", "SCRIPT_REJECTED"),
    ("np.testing.tempdir()", "SCRIPT_REJECTED"),
    ("x = image._something", "SCRIPT_REJECTED"),
    # frames reach the runner's real builtins; attrgetter/methodcaller read attributes by name; NpzFile reads any
    # zip by path and its .zip extracts and writes files
    ("def g():\n    yield\ngen = g()\nf = gen.gi_frame.f_back", "SCRIPT_REJECTED"),
    ("def g(f):\n    yield f.f_globals, f.f_locals, f.f_builtins", "SCRIPT_REJECTED"),
    ("def g(t):\n    return t.tb_frame", "SCRIPT_REJECTED"),
    ("async def c():\n    pass\nf = c().cr_frame", "SCRIPT_REJECTED"),
    ("async def a():\n    yield 1\nf = a().ag_frame", "SCRIPT_REJECTED"),
    ("import operator\nf = operator.attrgetter('__globals__')", "SCRIPT_REJECTED"),
    ("from operator import methodcaller", "SCRIPT_REJECTED"),
    ("nz = np.lib.npyio.NpzFile('drawing.png')", "SCRIPT_REJECTED"),
    ("from numpy.lib.npyio import NpzFile", "SCRIPT_REJECTED"),
    ("def f(nz):\n    nz.zip.extractall('out')", "SCRIPT_REJECTED"),
    ("def f(nz):\n    nz.zip.extract('a', 'out')", "SCRIPT_REJECTED"),
    ("def f(nz):\n    type(nz.zip)('x.zip', 'w').writestr('a', 'b')", "SCRIPT_REJECTED"),
    ("x = 1\nimage[0, 0] = 0", "SCRIPT_FAILED"),
    ("x = 1\ny = x / 0", "SCRIPT_FAILED"),
])
def test_code_is_checked_and_its_errors_point_at_the_line(ws, code, error):
    e = scripted(ws).inspect_image("drawing.png", code=code)["error"]
    assert e["code"] == error, e
    if error == "SCRIPT_FAILED":
        assert e["details"]["script_lines"][-1].startswith("line 2:")


@pytest.mark.parametrize("code", ["from PIL import ImageGrab", "import PIL", "import scipy", "import os",
                                  "from numpy import f2py", "from numpy import testing"])
def test_runner_import_hook_refuses_what_the_check_rejects(ws, code):
    """Second line of defence: the runner refuses these imports even for code that skipped the static check."""
    from agentcad import scripting
    png = BytesIO()
    Image.new("RGB", (4, 4), "white").save(png, format="PNG")
    res = scripting.run_image(code, png.getvalue(), (0, 0), ws / "job", 60)
    assert not res["ok"] and "ImportError" in res["error"], res


def test_slow_code_is_stopped(ws):
    drawing(ws / "drawing.png")
    runtime = Runtime(Policy(root=ws, allow_scripts=True, script_timeout=3))
    e = runtime.inspect_image("drawing.png", code="while True:\n    pass")["error"]
    assert e["code"] == "SCRIPT_TIMEOUT"


def test_code_needs_scripts_and_takes_no_rotation(ws):
    drawing(ws / "drawing.png")
    e = Runtime(Policy(root=ws)).inspect_image("drawing.png", code=EXTENTS)["error"]
    assert e["code"] == "SCRIPTS_DISABLED"
    runtime = scripted(ws)
    for kwargs in ({"rotate": 90}, {"dimensions": []}):
        e = runtime.inspect_image("drawing.png", code=EXTENTS, **kwargs)["error"]
        assert e["code"] == "BAD_IMAGE_SCRIPT"


def test_mcp_returns_measurements_without_an_image(ws):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    drawing(ws / "drawing.png")

    async def run():
        env = {**os.environ, "AGENTCAD_ROOT": str(ws), "AGENTCAD_ALLOW_SCRIPTS": "1", "AGENTCAD_VIEWER": "0",
               "AGENTCAD_TOOL_PROFILE": "full"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "agentcad.mcp_server"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                return await client.call_tool("inspect_image", {"path": "drawing.png", "code": EXTENTS})
    result = asyncio.run(run())
    assert [block.type for block in result.content] == ["text"], result
    assert json.loads(result.content[0].text)["script"]["stdout"].split()[1:3] == ["20", "59"]
