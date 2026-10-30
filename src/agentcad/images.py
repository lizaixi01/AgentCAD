"""Read-only image inspection for small callouts and section views in drawings."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import file_error, input_error
from .policy import Policy

MAX_PIXELS = 32_000_000
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
FORMATS = {"PNG", "JPEG", "WEBP"}


def inspect_image(policy: Policy, path: str, region: list[int] | None, max_size: int) -> dict:
    source = policy.resolve(path, must_exist=True, suffixes=(".png", ".jpg", ".jpeg", ".webp"))
    if isinstance(max_size, bool) or not isinstance(max_size, int) or not 64 <= max_size <= 2048:
        raise input_error("BAD_IMAGE_SIZE", "max_size must be an integer from 64 to 2048")
    if source.stat().st_size > min(policy.max_file_bytes, MAX_INPUT_BYTES):
        raise file_error("IMAGE_TOO_LARGE", "Source image exceeds the byte budget")
    raw = source.read_bytes()
    try:
        with Image.open(BytesIO(raw)) as opened:
            if opened.format not in FORMATS:
                raise file_error("BAD_IMAGE_FORMAT", "Expected a PNG, JPEG or WebP image")
            if opened.width * opened.height > MAX_PIXELS:
                raise file_error("IMAGE_TOO_LARGE", f"Source image exceeds {MAX_PIXELS} pixels")
            # Region coordinates refer to the displayed orientation, including JPEG EXIF rotation.
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            box = [0, 0, width, height] if region is None else region
            if (not isinstance(box, (list, tuple)) or len(box) != 4
                    or any(isinstance(v, bool) or not isinstance(v, int) for v in box)):
                raise input_error("BAD_IMAGE_REGION", "region must be [left, top, right, bottom] in source pixels")
            left, top, right, bottom = box
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise input_error("BAD_IMAGE_REGION", f"Region must be nonempty and inside {width} x {height}")
            rgba = image.crop(box).convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            crop = background.convert("RGB")
            scale = max_size / max(crop.size)
            size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
            preview = crop.resize(size, Image.Resampling.LANCZOS)
            stream = BytesIO()
            preview.save(stream, format="PNG")
            png = stream.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise file_error("IMAGE_READ_FAILED", f"Cannot read image: {exc}") from exc
    if len(png) > MAX_PREVIEW_BYTES:
        raise input_error("IMAGE_PREVIEW_TOO_LARGE", "Preview exceeds 2 MB", hint="Use a smaller max_size")
    return {"source": source.relative_to(policy.root).as_posix(),
            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_size": [width, height],
            "region": list(box), "preview_size": list(size), "pixel_scale": scale,
            "mime_type": "image/png", "image_base64": base64.b64encode(png).decode("ascii")}
