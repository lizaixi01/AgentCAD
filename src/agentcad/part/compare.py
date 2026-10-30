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
   silhouette's bounding box, then scale and position are refined to the best overlap. Framing differences (zoom,
   offset, margins) therefore do not count, and neither does the overall size: only shape and proportions do. A
   reference silhouette that ends on a straight line within a few pixels of its cell border runs out of the picture
   (BenchCAD clips parts inside a 4 px white gutter; see cut_sides): that side does not set the scale or position,
   and our silhouette is cut at the same line.
4. outline = silhouette IoU = |reference AND ours| / |reference OR ours|, after the same opening on both. Ours
   includes what the alignment puts outside the cell, except beyond a cut line: the search cannot win by pushing a
   wrong part out of the picture.
5. edges: what lies inside the outline. Edge pixels differ in colour from a neighbour by more than EDGE_STEP: drawn
   lines and steps in the shading, found the same way in the reference and in our render, away from each
   silhouette's border (step 4 scores that). edges = F1 of the two sets, a pixel counting as matched when the other
   image has one within about 1/128 of the cell. Holes, pockets, steps, ribs and chamfers change it even where
   they leave the outline alone. Cylinder and cone seams, which some renderers draw and ours does not, can match a
   reference line but cost nothing where there is none.
6. score = (outline + edges) / 2; the outline alone where neither image has an edge inside it, or where the
   reference has none in any view (a flat silhouette or a bare outline): edges is None there.

Checked offline against BenchCAD's voxel IoU (examples/benchcad/compare_check.py, 1,297 graded parts of 100 tasks):
of two parts for the same task whose grades differ by 0.1 or more, it ranks 89.6 % the grader's way (silhouette IoU
with the bounding-box alignment it replaces: 83.2 %), and the true part scores 0.967 against its own picture on
average (before: 0.942). It still cannot see what no view shows: hollow insides, wall thickness behind a face.

The output image is laid out like the reference, one cell per view: grey where both have material, light red where
only the reference has, light blue where only ours has; edges dark grey where both have one, red where only the
reference has one (a feature ours lacks or puts elsewhere), blue where only ours has. Pure numpy + Pillow, both
AgentCAD dependencies.

Limits (this runs in the AgentCAD/MCP process): the reference file at most 32 MB and 25 megapixels (checked from the
header, before decoding), cells no more than 8:1; every cell is scaled down to at most 1024 px before any processing,
the alignment search works on at most 256 px, and the output sheet stays within 4096 px a side and 8 megapixels.
The morphology is separable and the hole filling works on pixel runs, so a cell costs about its pixel count times
the filter radius.
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
EDGE_STEP = 30     # max channel difference to a neighbour that makes an edge pixel
DETAIL_SHARE = 0.01  # a reference shows detail inside its outlines when this much of a view's inside is off its colour
CUT_NEAR = 0.016   # a silhouette side this close to the cell border (BenchCAD: a 4 px gutter in a 262 px cell) ...
CUT_RUN = 0.05     # ... with this much of the silhouette's extent on its last row or column ...
CUT_DEPTH = 0.01   # ... and at least CUT_STRAIGHT of the width it has this far (fraction of the cell) inside ...
CUT_STRAIGHT = 0.6  # ... is cut by the frame
SEARCH_MAX = 256   # the alignment search works on cells scaled down to this many pixels
FILL_BOTH, FILL_REF, FILL_OURS = (222, 222, 222), (246, 186, 186), (186, 204, 246)
LINE_BOTH, LINE_REF, LINE_OURS = (95, 95, 95), (215, 25, 25), (35, 85, 225)
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


def cut_sides(ref: np.ndarray) -> dict[str, int]:
    """{side: line} for each side where the reference silhouette ends on a straight line near the cell border: the
    part runs out of the picture there. The silhouette must cross that line about as wide as it is a few pixels in
    (a curve that reaches the border is narrower at its tip), and a silhouette that reaches all four sides is taken
    as framed tightly rather than cut: nothing would be left to set its scale."""
    th, tw = ref.shape
    bb = _bbox(ref)
    if bb is None:
        return {}
    x0, y0, x1, y1 = bb
    near_x, near_y = max(2.0, CUT_NEAR * tw), max(2.0, CUT_NEAR * th)
    run_x, run_y = max(4.0, CUT_RUN * (x1 - x0)), max(4.0, CUT_RUN * (y1 - y0))
    k = max(2, round(CUT_DEPTH * max(th, tw)))

    def straight(on: np.ndarray, inside: np.ndarray, run: float) -> bool:
        return on.sum() >= run and on.sum() >= CUT_STRAIGHT * inside.sum()
    sides = {"left": (x0 <= near_x and straight(ref[:, x0], ref[:, min(x0 + k, x1 - 1)], run_y), x0),
             "right": (tw - x1 <= near_x and straight(ref[:, x1 - 1], ref[:, max(x1 - 1 - k, x0)], run_y), x1),
             "top": (y0 <= near_y and straight(ref[y0], ref[min(y0 + k, y1 - 1)], run_x), y0),
             "bottom": (th - y1 <= near_y and straight(ref[y1 - 1], ref[max(y1 - 1 - k, y0)], run_x), y1)}
    cuts = {side: line for side, (cut, line) in sides.items() if cut}
    return {} if len(cuts) == 4 else cuts


def _place(a: np.ndarray, shape: tuple[int, int], s: float, cx: float, cy: float, cuts: dict[str, int] | None = None,
           thin: bool = False):
    """``a`` (an image, or a mask) scaled by s and centred on (cx, cy) of a canvas of ``shape``: white, or False.
    A mask is cut at the ``cuts`` lines and comes with the number of its pixels that fell outside the canvas on
    other sides: material of ours where the reference has none, which the IoU counts. A ``thin`` mask (lines) keeps
    every pixel a line touches, so scaling down does not erase it."""
    th, tw = shape
    oh, ow = a.shape[:2]
    w, h = max(1, round(ow * s)), max(1, round(oh * s))
    x0, y0 = round(cx - w / 2), round(cy - h / 2)
    ax0, ay0, ax1, ay1 = max(x0, 0), max(y0, 0), min(x0 + w, tw), min(y0 + h, th)
    sub = (slice(ay0 - y0, ay1 - y0), slice(ax0 - x0, ax1 - x0))
    if a.ndim == 3:
        out = np.full((th, tw, 3), 255, np.uint8)
        a = np.asarray(Image.fromarray(a).resize((w, h), Image.LANCZOS))
        if ax0 < ax1 and ay0 < ay1:
            out[ay0:ay1, ax0:ax1] = a[sub]
        return out
    out = np.zeros((th, tw), bool)
    a = np.asarray(Image.fromarray(a.astype(np.uint8) * 255, "L").resize((w, h), Image.BILINEAR))
    a = a > 0 if thin else a >= 128
    cuts = cuts or {}  # beyond a cut line nothing is compared, on the canvas or off it
    if "left" in cuts:
        a[:, :max(0, min(w, cuts["left"] - x0))] = False
    if "right" in cuts:
        a[:, max(0, min(w, cuts["right"] - x0)):] = False
    if "top" in cuts:
        a[:max(0, min(h, cuts["top"] - y0))] = False
    if "bottom" in cuts:
        a[max(0, min(h, cuts["bottom"] - y0)):] = False
    if ax0 < ax1 and ay0 < ay1:
        out[ay0:ay1, ax0:ax1] = a[sub]
    return out, int(a.sum()) - int(out.sum())


def _refine(crop: np.ndarray, ref: np.ndarray, cuts: dict[str, int], s: float, cx: float,
            cy: float) -> tuple[float, float, float]:
    """Scale and centre of our silhouette crop that give the best overlap with the reference, searched from the
    bounding-box fit: steps of 8 % in scale and 4 % of the cell in position, halved down to a pixel, on a copy of the
    cell at most SEARCH_MAX pixels."""
    k = min(1.0, SEARCH_MAX / max(ref.shape))
    if k < 1:
        size = (max(1, round(ref.shape[1] * k)), max(1, round(ref.shape[0] * k)))
        ref = np.asarray(Image.fromarray(ref.astype(np.uint8) * 255, "L").resize(size, Image.BILINEAR)) >= 128
        cuts = {side: round(line * k) for side, line in cuts.items()}
    pos = (s * k, cx * k, cy * k)

    def overlap(p):
        return iou(ref, *_place(crop, ref.shape, *p, cuts=cuts)) or 0.0

    best, budget = overlap(pos), 300  # evaluations, at most: a bound on time whatever the shapes
    ds, dp = 0.08, 0.04 * max(ref.shape)
    while dp >= 0.5 and budget > 0:
        for step in ((pos[0] * ds, 0, 0), (-pos[0] * ds, 0, 0), (0, dp, 0), (0, -dp, 0), (0, 0, dp), (0, 0, -dp)):
            cand = (pos[0] + step[0], pos[1] + step[1], pos[2] + step[2])
            v, budget = overlap(cand), budget - 1
            if v > best + 1e-9:
                best, pos = v, cand
                break
        else:  # no step improves: finer steps
            ds, dp = ds / 2, dp / 2
    return pos[0] / k, pos[1] / k, pos[2] / k


def align(img: np.ndarray, mask: np.ndarray, ref: np.ndarray, extra: tuple[np.ndarray | None, ...] = ()
          ) -> tuple[np.ndarray, np.ndarray, list, dict[str, Any], int]:
    """Our render and silhouette placed on a canvas the size of the reference cell (see the module docstring), the
    ``extra`` masks (lines) placed the same way, {"cut": [sides]} when the reference runs out of its picture, and
    how many pixels of our silhouette fell outside the cell where the reference is not cut."""
    th, tw = ref.shape
    rb, ob = _bbox(ref), _bbox(mask)
    if rb is None or ob is None:
        return (np.full((th, tw, 3), 255, np.uint8), np.zeros((th, tw), bool),
                [None if e is None else np.zeros((th, tw), bool) for e in extra], {}, 0)
    cuts = cut_sides(ref)
    rx0, ry0, rx1, ry1 = rb
    ox0, oy0, ox1, oy1 = ob
    rw, rh, ow, oh = rx1 - rx0, ry1 - ry0, ox1 - ox0, oy1 - oy0
    cut_l, cut_r, cut_t, cut_b = (side in cuts for side in ("left", "right", "top", "bottom"))
    cut_x, cut_y = cut_l or cut_r, cut_t or cut_b
    sx, sy = rw / ow, rh / oh
    if cut_x != cut_y:  # the uncut axis sets the scale
        s = sy if cut_x else sx
    elif not cut_x:
        s = math.sqrt(sx * sy)
    else:  # cut on both axes: a cut only shrinks the box, so the larger factor is nearer; the search does the rest
        s = max(sx, sy)
    s = min(s, 2 * max(tw, th) / max(ow, oh))  # whatever lies beyond twice the cell is cut off anyway
    w, h = ow * s, oh * s

    def centre(lo, hi, size, cut_lo, cut_hi):
        if cut_lo and not cut_hi:
            return hi - size / 2
        if cut_hi and not cut_lo:
            return lo + size / 2
        return (lo + hi) / 2

    crop = (slice(oy0, oy1), slice(ox0, ox1))
    s, cx, cy = _refine(mask[crop], ref, cuts, s, centre(rx0, rx1, w, cut_l, cut_r), centre(ry0, ry1, h, cut_t, cut_b))
    out, over = _place(mask[crop], ref.shape, s, cx, cy, cuts)
    canvas = _place(img[crop], ref.shape, s, cx, cy)
    canvas[~out] = 255  # nothing beyond our silhouette or a cut line is compared
    placed = [None if e is None else _place(e[crop], ref.shape, s, cx, cy, cuts, thin=True)[0] for e in extra]
    return canvas, out, placed, ({"cut": sorted(cuts)} if cuts else {}), over


def iou(a: np.ndarray, b: np.ndarray, outside: int = 0) -> float | None:
    """|a AND b| / |a OR b|; ``outside``: pixels of b beyond the canvas, part of the union."""
    union = int((a | b).sum()) + outside
    return round(int((a & b).sum()) / union, 4) if union else None


def edge_pixels(rgb: np.ndarray) -> np.ndarray:
    """Pixels whose colour differs from one of their 8 neighbours by more than EDGE_STEP in some channel: drawn lines
    (the pixels on both sides of one, too) and steps in the shading."""
    a = rgb.astype(np.int16)
    h, w = a.shape[:2]
    out = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):  # each pair of neighbours once; both pixels of a step are marked
        here = (slice(0, h - dy), slice(max(0, -dx), w - max(0, dx)))
        there = (slice(dy, h), slice(max(0, dx), w - max(0, -dx)))
        step = np.abs(a[here] - a[there]).max(axis=2) > EDGE_STEP
        out[here] |= step
        out[there] |= step
    return out


def edge_score(ref_e: np.ndarray, our_e: np.ndarray, optional: np.ndarray | None,
               r: int) -> tuple[float | None, np.ndarray, np.ndarray]:
    """(F1 of the two edge sets, the reference's edge pixels matched, ours matched): a pixel is matched when the other
    set has one within r pixels. ``optional`` edges of ours (seams) can match a reference pixel but are never
    counted against us. None when neither image has an edge: nothing inside the outline to compare."""
    ours_all = our_e if optional is None else our_e | optional
    ref_hit = ref_e & _morph(ours_all, r, "max")
    our_hit = our_e & _morph(ref_e, r, "max")
    n_ref, n_ours = int(ref_e.sum()), int(our_e.sum())
    if not n_ref and not n_ours:
        return None, ref_hit, our_hit
    p = our_hit.sum() / n_ours if n_ours else 1.0  # no edge of ours is out of place
    rc = ref_hit.sum() / n_ref if n_ref else 1.0   # no edge of the reference is missing
    return (float(2 * p * rc / (p + rc)) if p + rc else 0.0), ref_hit, our_hit


def diff_image(ref: np.ndarray, ours: np.ndarray, ref_e: np.ndarray | None = None, our_e: np.ndarray | None = None,
               ref_hit: np.ndarray | None = None, our_hit: np.ndarray | None = None) -> np.ndarray:
    out = np.full(ref.shape + (3,), 255, np.uint8)
    out[ref & ours] = FILL_BOTH
    out[ref & ~ours] = FILL_REF
    out[~ref & ours] = FILL_OURS
    if ref_e is not None:
        t = round(ref.shape[0] / 512)  # thicker on large cells, so the lines survive scaling the sheet down

        def thick(m):
            return _morph(m, t, "max") if t else m
        out[thick(our_e & ~our_hit)] = LINE_OURS
        out[thick(ref_e & ~ref_hit)] = LINE_REF
        out[thick(ref_hit)] = LINE_BOTH
    return out


def compare_views(cells: list[tuple[np.ndarray, np.ndarray | None]], names: list[str],
                  renders: list[tuple]) -> tuple[list[dict[str, Any]], list[np.ndarray], str]:
    """Per-view results and diff images. ``cells`` from load_reference; ``renders`` (image, silhouette[, seams]) of
    each view, seams being the pixels of the seam lines our render leaves out (or None). A reference whose outlines
    are all one colour inside (a flat silhouette, a bare outline, also as a JPEG) says nothing about the inside: in
    no view does DETAIL_SHARE of the inside differ from its median colour. Then no view has an edge score, and each
    scores its outline."""
    views, modes = [], set()
    for name, (rgb, alpha), (img, mask, *rest) in zip(names, cells, renders):
        seams = rest[0] if rest else None
        ref, mode = silhouette(rgb, alpha)
        modes.add(mode)
        r = _radius(rgb.shape)
        # the outline edges are drawn half outside the solid's pixels; a reference's silhouette has them too
        mask = mask | (np.abs(img.astype(np.int16) - 255).max(axis=2) > BG_THRESHOLD)
        # our render at the cell's size first, so both silhouettes are cleaned at the same resolution
        placed, ours, (seams,), info, outside = align(img, mask, ref, (seams,))
        ours = opening(fill_holes(ours) if mode == "lines" else ours, r)
        # edges inside each silhouette, away from its border (the outline is scored on its own)
        inside = _morph(ref, 2 * r, "min")
        ref_e = edge_pixels(rgb) & inside
        our_e = edge_pixels(placed) & _morph(ours, 2 * r, "min")
        if seams is not None:
            seams = _morph(seams, 1, "max") & _morph(ours, 2 * r, "min")
        # how much of the inside differs from its usual colour: shading, lines (JPEG noise is no detail)
        px = rgb[inside].astype(np.int16)
        detail = float((np.abs(px - np.median(px, axis=0)).max(axis=1) > EDGE_STEP).mean()) if len(px) else 0.0
        views.append((name, ref, ours, iou(ref, ours, outside), ref_e, our_e, seams, r, info, detail))
    detailed = any(v[-1] >= DETAIL_SHARE for v in views)
    results, diffs = [], []
    for name, ref, ours, outline, ref_e, our_e, seams, r, info, _ in views:
        edges, ref_hit, our_hit = edge_score(ref_e, our_e, seams, r) if detailed else (None, None, None)
        entry: dict[str, Any] = {"view": name, "score": None, "outline": outline,
                                 "edges": None if edges is None else round(edges, 3)}
        if outline is not None:
            entry["outline"] = round(outline, 3)
            entry["score"] = round(outline if edges is None else (outline + edges) / 2, 3)
        entry.update(info)
        if not ref.any():
            entry["note"] = "no silhouette found in this reference cell"
        results.append(entry)
        diffs.append(diff_image(ref, ours, ref_e, our_e, ref_hit, our_hit) if detailed else diff_image(ref, ours))
    return results, diffs, "lines" if modes == {"lines"} else "filled" if modes == {"filled"} else "mixed"


def save_sheet(cells: list[np.ndarray], labels: list[str], path: Path, cell: int) -> tuple[list[int], int]:
    """The diff images laid out like the reference (grid_of), each cell ``cell`` pixels high (its width keeps the
    reference cell's aspect), smaller if the sheet would exceed SHEET_MAX_SIDE or SHEET_MAX_PIXELS. Returns
    ([rows, columns], the cell height used)."""
    th, tw = cells[0].shape[:2]
    rows, cols = grid_of(len(cells))
    cw = max(16, round(cell * tw / th))
    k = min(1.0, SHEET_MAX_SIDE / (cols * cw), SHEET_MAX_SIDE / (rows * cell),
            math.sqrt(SHEET_MAX_PIXELS / (cols * cw * rows * cell)))
    if k < 1:
        cell, cw = max(16, int(cell * k)), max(16, int(cw * k))
    sheet = Image.new("RGB", (cols * cw, rows * cell), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=max(11, cell // 20))
    except (TypeError, OSError, ImportError):
        font = None
    for i, a in enumerate(cells):
        r, c = divmod(i, cols)
        sheet.paste(Image.fromarray(a).resize((cw, cell), Image.NEAREST if cell >= th else Image.BOX),
                    (c * cw, r * cell))
        dr.text((c * cw + 4, r * cell + 2), labels[i], fill=(60, 60, 60), font=font)
    for c in range(1, cols):
        dr.line([(c * cw, 0), (c * cw, rows * cell)], fill=(200, 200, 200))
    for r in range(1, rows):
        dr.line([(0, r * cell), (cols * cw, r * cell)], fill=(200, 200, 200))
    sheet.save(path)
    return [rows, cols], cell
