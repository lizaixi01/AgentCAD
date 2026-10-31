"""Read-only image inspection for small callouts and section views in drawings, and pixel measurement by script."""
from __future__ import annotations

import base64
import hashlib
import shutil
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import AgentCADError, file_error, input_error
from .policy import Policy

MAX_PIXELS = 32_000_000
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
FORMATS = {"PNG", "JPEG", "WEBP"}


def inspect_image(policy: Policy, path: str, region: list[int] | None, max_size: int, rotate: int = 0,
                  dimensions: list[dict] | None = None, code: str | None = None) -> dict:
    if code is not None:
        if rotate or dimensions is not None:
            raise input_error("BAD_IMAGE_SCRIPT", "code runs on the unrotated region: it takes no rotate or "
                              "dimensions", hint="Rotate inside the script (np.rot90) if you need to")
        from .scripting import check_script
        policy.check_scripts_allowed()
        check_script(code, "image")
    source = policy.resolve(path, must_exist=True, suffixes=(".png", ".jpg", ".jpeg", ".webp"))
    if isinstance(max_size, bool) or not isinstance(max_size, int) or not 64 <= max_size <= 2048:
        raise input_error("BAD_IMAGE_SIZE", "max_size must be an integer from 64 to 2048")
    if isinstance(rotate, bool) or not isinstance(rotate, int) or rotate not in (0, 90, 180, 270):
        raise input_error("BAD_IMAGE_ROTATION", "rotate must be 0, 90, 180 or 270 clockwise degrees")
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
            extra = {}
            if code is not None:
                extra["script"], crop = _measure(policy, code, crop, (left, top))
                if crop is None:  # numbers only: no picture to send
                    return {"source": source.relative_to(policy.root).as_posix(),
                            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_size": [width, height],
                            "region": list(box), **extra}
            if dimensions is not None:
                from .image_dimensions import check_dimensions, evidence_preview
                evidence = check_dimensions(dimensions, list(box), crop)
            if rotate:
                crop = crop.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                                       270: Image.Transpose.ROTATE_90}[rotate])
            if dimensions is not None:
                preview, scale, panels = evidence_preview(crop, box, rotate, max_size, evidence)
                extra = {"dimension_evidence": evidence, "panels": panels}
                size = preview.size
            else:
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
            "region": list(box), "rotate": rotate, "preview_size": list(size), "pixel_scale": scale,
            "mime_type": "image/png", "image_base64": base64.b64encode(png).decode("ascii"), **extra}


def _measure(policy: Policy, code: str, crop: Image.Image, origin: tuple[int, int]) -> tuple[dict, Image.Image | None]:
    """Run an image script on the region at full source resolution: its output, and the image it returned (or
    None). The job folder is a short path under the system temp directory (a deep workspace would pass Windows'
    260-character limit), removed afterwards."""
    from .scripting import run_image
    stream = BytesIO()
    crop.save(stream, format="PNG")
    job = Path(tempfile.gettempdir()) / "agentcad-img" / uuid.uuid4().hex[:12]
    try:
        res = run_image(code, stream.getvalue(), origin, job, policy.script_timeout)
        if not res["ok"]:
            raise AgentCADError(res.get("code", "SCRIPT_FAILED"), f"The script raised {res.get('error')}",
                                category="input",
                                details={k: res[k] for k in ("script_lines", "stdout", "traceback") if res.get(k)},
                                hint="Fix the script and run it again; `image` is read-only, draw on image.copy()")
        picture = None
        if res.get("image"):
            with Image.open(job / "result.png") as im:
                picture = im.convert("RGB")
    finally:
        shutil.rmtree(job, ignore_errors=True)
    info = {"seconds": res["seconds"], "stdout": res.get("stdout", "")}
    for k in ("result", "result_truncated", "image"):
        if k in res:
            info[k] = res[k]
    return info, picture
