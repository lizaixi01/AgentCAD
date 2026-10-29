"""Compare a part's preview with a reference image (``export_drawing(..., "png", views=[...], reference=...)``).

The reference is a grid of views laid out like AgentCAD's own preview sheet: the same order as ``views``, one cell
for one view, two columns for up to four views (three beyond), one cell for a single view. For each cell:

1. the reference silhouette: pixels that differ from the background colour (the median of the cell's border, so any
   background colour works; with an alpha channel, the opaque pixels). An opening by about 1/128 of the cell removes
   thin lines (grid borders, labels, leader lines). If that removes most of the cell, the reference is a line
   drawing: its outline is closed and filled instead.
2. our part rendered from that view's camera, its silhouette taken from the depth buffer (plus the outline edges,
   which a reference silhouette contains too);
3. alignment: our silhouette is scaled (one factor, so the aspect ratio is kept) and moved onto the reference
   silhouette's bounding box. Framing differences (zoom, offset, margins) therefore do not count, and neither does
   the overall size: only shape and proportions do. A reference silhouette that touches the cell border is taken as
   cropped: that axis is not used for the scale, and our silhouette is aligned to the side that is not cut.
4. silhouette IoU = |reference AND ours| / |reference OR ours|, after the same opening on both.

The output image has one row per view: the reference cell, our aligned render and a diff (red: only in the
reference, blue: only ours, grey: both). Pure numpy + Pillow, both AgentCAD dependencies.

Limits (this runs in the AgentCAD/MCP process): the reference file at most 32 MB and 25 megapixels (checked from the
header, before decoding), cells no more than 8:1; every cell is scaled down to at most 1024 px before any processing,
and the output sheet stays within 4096 px a side and 8 megapixels. The morphology is separable and the hole filling
works on pixel runs, so a cell costs about its pixel count times the filter radius.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ..errors import input_error

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
BG_THRESHOLD = 28  # max channel difference from the background colour that still counts as background
BOTH, ONLY_REF, ONLY_OURS = (150, 150, 150), (220, 40, 40), (40, 90, 220)
LEGEND = "diff: red = only in the reference, blue = only in our part, grey = both"
ALIGNMENT = ("our silhouette scaled (aspect kept) and centred onto the reference silhouette's bounding box: "
             "framing and overall size do not count, shape and proportions do")
MAX_REFERENCE_BYTES = 32 * 1024 * 1024
MAX_REFERENCE_PIXELS = 25_000_000
MAX_CELL_ASPECT = 8.0
CELL_MAX = 1024             # reference cells are scaled down to this many pixels on their longer side
SHEET_MAX_SIDE = 4096
SHEET_MAX_PIXELS = 8_000_000
LAYOUT_HINT = ("The reference is laid out like the preview: same order as views, 2 columns for up to 4 views, "
               "3 beyond, one cell for a single view")


def grid_of(n: int) -> tuple[int, int]:
    """(rows, columns) of a sheet of n views, as the preview renderer lays it out."""
    if n <= 1:
        return 1, 1
    cols = 2 if n <= 4 else 3
    return -(-n // cols), cols


def load_reference(path: Path, n_views: int) -> list[tuple[np.ndarray, np.ndarray | None]]:
    """The reference image split into its view cells: [(rgb uint8, alpha or None)] in view order, each cell scaled
    down to at most CELL_MAX pixels. Size and layout are checked from the header, before the image is decoded."""
    rows, cols = grid_of(n_views)
    nbytes = path.stat().st_size
    if nbytes > MAX_REFERENCE_BYTES:
        raise input_error("BAD_REFERENCE", f"{path.name} is {nbytes} bytes (limit {MAX_REFERENCE_BYTES})",
                          hint="Use a smaller image: about 512 px per view is plenty")
    try:
        im = Image.open(path)  # reads the header only
        w, h = im.size
    except Exception as exc:  # noqa: BLE001 - Pillow raises many kinds for a bad file
        raise input_error("BAD_REFERENCE", f"{path.name} is not a readable image: {exc}")
    if w * h > MAX_REFERENCE_PIXELS:
        raise input_error("BAD_REFERENCE", f"{path.name} is {w}x{h} pixels (limit {MAX_REFERENCE_PIXELS // 10**6} "
                                           "megapixels)", hint="Use a smaller image: about 512 px per view is plenty")
    tw, th = w // cols, h // rows
    if th < 16 or tw < 16:
        raise input_error("BAD_REFERENCE", f"{path.name} is {w}x{h}: too small for a {rows}x{cols} grid of views",
                          hint=LAYOUT_HINT)
    if max(tw / th, th / tw) > MAX_CELL_ASPECT:
        raise input_error("BAD_REFERENCE", f"{path.name} is {w}x{h}: its {rows}x{cols} grid has {tw}x{th} cells, "
                                           f"more than {MAX_CELL_ASPECT:g}:1", hint=LAYOUT_HINT)
    k = min(1.0, CELL_MAX / max(tw, th))
    try:
        if k < 1 and im.format == "JPEG":
            im.draft("RGB", (max(1, round(w * k)), max(1, round(h * k))))  # decode JPEG at a reduced size
        im.load()
        alpha_mode = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if alpha_mode else "RGB")
        if k < 1:
            im = im.resize((max(cols * 16, round(w * k)), max(rows * 16, round(h * k))), Image.LANCZOS)
    except Exception as exc:  # noqa: BLE001
        raise input_error("BAD_REFERENCE", f"{path.name} could not be decoded: {exc}")
    arr = np.asarray(im)
    alpha = None
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3] if arr[:, :, 3].min() < 250 else None
        arr = arr[:, :, :3]
    h, w = arr.shape[:2]
    th, tw = h // rows, w // cols
    cells = []
    for i in range(n_views):
        r, c = divmod(i, cols)
        sl = (slice(r * th, (r + 1) * th), slice(c * tw, (c + 1) * tw))
        cells.append((np.ascontiguousarray(arr[sl]), None if alpha is None else alpha[sl]))
    return cells


def _radius(shape: tuple[int, ...]) -> int:
    return max(1, round(min(shape[:2]) / 128))


def _morph(mask: np.ndarray, r: int, op: str) -> np.ndarray:
    """Binary erosion ('min') or dilation ('max') with a (2r+1) square: a row pass, then a column pass. Edges are
    extended, so a silhouette cut by the cell border stays cut there."""
    f = np.logical_and if op == "min" else np.logical_or
    out = mask.astype(bool)
    for axis in (0, 1):
        n = out.shape[axis]
        pad = [(r, r) if a == axis else (0, 0) for a in (0, 1)]
        p = np.pad(out, pad, mode="edge")
        acc = p[:n] if axis == 0 else p[:, :n]
        for k in range(1, 2 * r + 1):
            acc = f(acc, p[k:k + n] if axis == 0 else p[:, k:k + n])
        out = acc
    return out


def opening(mask: np.ndarray, r: int) -> np.ndarray:
    return _morph(_morph(mask, r, "min"), r, "max")


def _runs(free: np.ndarray) -> np.ndarray:
    """Ids of the horizontal runs of True pixels, unique over the image (0 where False)."""
    h, w = free.shape
    flat = free.ravel()
    start = flat.copy()
    start[1:] &= ~flat[:-1]
    start[::w] = flat[::w]  # every row starts new runs
    return (np.cumsum(start) * flat).reshape(h, w)


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill every region not connected to the border (an outline drawing becomes a solid silhouette). Background
    reachable from the border spreads along whole row and column runs per pass, so a pass costs one sweep of the
    cell and the number of passes is the number of turns a path needs, not its length."""
    free = ~mask.astype(bool)
    rows, cols = _runs(free), _runs(free.T).T
    reached = np.zeros_like(free)
    for edge in ((0, slice(None)), (-1, slice(None)), (slice(None), 0), (slice(None), -1)):
        reached[edge] = free[edge]
    count = -1
    while int(reached.sum()) != count:
        count = int(reached.sum())
        for ids in (rows, cols):
            hit = np.zeros(int(ids.max()) + 1, bool)
            hit[ids[reached]] = True
            hit[0] = False
            reached = hit[ids]
    return ~reached


def silhouette(rgb: np.ndarray, alpha: np.ndarray | None = None) -> tuple[np.ndarray, str]:
    """(mask, mode) of a reference cell; mode 'filled' (shaded or flat silhouette) or 'lines' (line drawing)."""
    if alpha is not None:
        raw = alpha > 127
    else:
        ring = np.concatenate([rgb[:2].reshape(-1, 3), rgb[-2:].reshape(-1, 3), rgb[:, :2].reshape(-1, 3),
                               rgb[:, -2:].reshape(-1, 3)])
        bg = np.median(ring, axis=0)
        raw = np.abs(rgb.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > BG_THRESHOLD
    r = _radius(rgb.shape)
    opened = opening(raw, r)
    if raw.sum() and opened.sum() < 0.25 * raw.sum():  # thin strokes only: an outline drawing
        return opening(fill_holes(_morph(_morph(raw, r, "max"), r, "min")), r), "lines"
    return opened, "filled"


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def align(img: np.ndarray, mask: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Our render and silhouette placed on a canvas the size of the reference cell, scaled and moved onto the
    reference silhouette's bounding box (see the module docstring)."""
    th, tw = ref.shape
    canvas = np.full((th, tw, 3), 255, np.uint8)
    out_mask = np.zeros((th, tw), bool)
    rb, ob = _bbox(ref), _bbox(mask)
    if rb is None or ob is None:
        return canvas, out_mask, {}
    rx0, ry0, rx1, ry1 = rb
    ox0, oy0, ox1, oy1 = ob
    rw, rh, ow, oh = rx1 - rx0, ry1 - ry0, ox1 - ox0, oy1 - oy0
    cut_l, cut_r, cut_t, cut_b = rx0 <= 1, rx1 >= tw - 1, ry0 <= 1, ry1 >= th - 1
    cut_x, cut_y = cut_l or cut_r, cut_t or cut_b
    sx, sy = rw / ow, rh / oh
    s = sy if cut_x and not cut_y else sx if cut_y and not cut_x else math.sqrt(sx * sy)
    s = min(s, 2 * max(tw, th) / max(ow, oh))  # whatever lies beyond twice the cell is cut off anyway
    w, h = max(1, round(ow * s)), max(1, round(oh * s))

    def place(lo, hi, size, cut_lo, cut_hi):
        if cut_lo and not cut_hi:
            return hi - size
        if cut_hi and not cut_lo:
            return lo
        return round((lo + hi - size) / 2)

    x0, y0 = place(rx0, rx1, w, cut_l, cut_r), place(ry0, ry1, h, cut_t, cut_b)
    crop = Image.fromarray(img[oy0:oy1, ox0:ox1]).resize((w, h), Image.LANCZOS)
    cm = Image.fromarray(mask[oy0:oy1, ox0:ox1].astype(np.uint8) * 255, "L").resize((w, h), Image.BILINEAR)
    cm = np.asarray(cm) >= 128
    crop = np.asarray(crop)
    # paste, clipped to the cell
    ax0, ay0, ax1, ay1 = max(x0, 0), max(y0, 0), min(x0 + w, tw), min(y0 + h, th)
    if ax0 < ax1 and ay0 < ay1:
        sub = (slice(ay0 - y0, ay1 - y0), slice(ax0 - x0, ax1 - x0))
        m = cm[sub]
        region = canvas[ay0:ay1, ax0:ax1]
        region[m] = crop[sub][m]
        out_mask[ay0:ay1, ax0:ax1] = m
    info = {"scale": round(s, 4)}
    if cut_x or cut_y:
        info["reference_cropped"] = [side for side, cut in (("left", cut_l), ("right", cut_r), ("top", cut_t),
                                                             ("bottom", cut_b)) if cut]
    return canvas, out_mask, info


def iou(a: np.ndarray, b: np.ndarray) -> float | None:
    union = int((a | b).sum())
    return round(int((a & b).sum()) / union, 4) if union else None


def diff_image(ref: np.ndarray, ours: np.ndarray) -> np.ndarray:
    out = np.full(ref.shape + (3,), 255, np.uint8)
    out[ref & ours] = BOTH
    out[ref & ~ours] = ONLY_REF
    out[~ref & ours] = ONLY_OURS
    return out


def compare_views(cells: list[tuple[np.ndarray, np.ndarray | None]], names: list[str],
                  renders: list[tuple[np.ndarray, np.ndarray]]) -> tuple[list[dict[str, Any]], list[list[np.ndarray]], str]:
    """Per-view results and the three images of each row: (reference cell, our aligned render, diff).
    ``cells`` from load_reference; ``renders`` (image, silhouette) of each view."""
    results, rows, modes = [], [], set()
    for name, (rgb, alpha), (img, mask) in zip(names, cells, renders):
        ref, mode = silhouette(rgb, alpha)
        modes.add(mode)
        r = _radius(rgb.shape)
        # the outline edges are drawn half outside the solid's pixels; a reference's silhouette has them too
        mask = mask | (np.abs(img.astype(np.int16) - 255).max(axis=2) > BG_THRESHOLD)
        # our render at the cell's size first, so both silhouettes are cleaned at the same resolution
        placed, ours, info = align(img, mask, ref)
        ours = opening(fill_holes(ours) if mode == "lines" else ours, r)
        entry: dict[str, Any] = {"view": name, "iou": iou(ref, ours), **info}
        if not ref.any():
            entry["note"] = "no silhouette found in this reference cell"
        results.append(entry)
        rows.append([rgb, placed, diff_image(ref, ours)])
    return results, rows, "lines" if modes == {"lines"} else "filled" if modes == {"filled"} else "mixed"


def save_sheet(rows: list[list[np.ndarray]], labels: list[list[str]], path: Path, cell: int) -> tuple[list[int], int]:
    """One row per view: reference, ours, diff; each cell ``cell`` pixels high, smaller if the sheet would exceed
    SHEET_MAX_SIDE or SHEET_MAX_PIXELS. Returns ([rows, 3], the cell height used)."""
    th, tw = rows[0][0].shape[:2]
    n = len(rows)
    cw = max(16, round(cell * tw / th))
    k = min(1.0, SHEET_MAX_SIDE / (3 * cw), SHEET_MAX_SIDE / (n * cell),
            math.sqrt(SHEET_MAX_PIXELS / (3 * cw * n * cell)))
    if k < 1:
        cell, cw = max(16, int(cell * k)), max(16, int(cw * k))
    sheet = Image.new("RGB", (3 * cw, n * cell), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=max(11, cell // 20))
    except (TypeError, OSError, ImportError):
        font = None
    for i, row in enumerate(rows):
        for j, a in enumerate(row):
            sheet.paste(Image.fromarray(a).resize((cw, cell), Image.LANCZOS), (j * cw, i * cell))
            at = (j * cw + 4, i * cell + 2)
            box = dr.textbbox(at, labels[i][j], font=font)  # on white: the reference may carry its own labels
            dr.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=(255, 255, 255))
            dr.text(at, labels[i][j], fill=(60, 60, 60), font=font)
    for j in range(1, 3):
        dr.line([(j * cw, 0), (j * cw, n * cell)], fill=(200, 200, 200))
    for i in range(1, n):
        dr.line([(0, i * cell), (3 * cw, i * cell)], fill=(200, 200, 200))
    sheet.save(path)
    return [n, 3], cell
