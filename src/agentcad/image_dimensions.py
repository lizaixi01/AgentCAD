"""Check caller-supplied drawing anchors and solve their linear dimension graph.

No OCR or feature recognition: agreement here is conditional on the supplied readings.
Coordinates always refer to the EXIF-oriented source image, before crop rotation.
"""
from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

from PIL import Image, ImageDraw

from .errors import input_error

PIXEL_TOLERANCE = 2.0
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


def _bad(message: str):
    return input_error("BAD_DIMENSION_EVIDENCE", message,
                       hint="Use {id, view, value, unit:'mm', line:[[x,y],[x,y]], "
                            "surfaces:[{name,point:[x,y]},{name,point:[x,y]}]} in source pixels")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise _bad(f"{field} must be a nonempty string of at most 80 characters")
    return value


def _finite_number(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)
    except OverflowError:
        return False


def _point(value: Any, box: list[int]) -> list[float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(not _finite_number(x) for x in value)):
        raise _bad("Each point must contain two finite pixel coordinates")
    x, y = map(float, value)
    if not (box[0] <= x < box[2] and box[1] <= y < box[3]):
        raise _bad("Every anchor must be inside the crop; include both witness lines and measured surfaces")
    return [x, y]


def check_dimensions(readings: list[dict], box: list[int], source_crop=None) -> dict[str, Any]:
    if not isinstance(readings, list) or len(readings) > 12:
        raise _bad("dimensions must be a list of at most 12 readings (empty gives a coordinate guide)")
    checks, ids = [], set()
    for reading in readings:
        if not isinstance(reading, dict) or set(reading) - {"id", "view", "value", "unit", "line", "surfaces"}:
            raise _bad("Unexpected dimension fields")
        identifier = _name(reading.get("id"), "id")
        if identifier in ids:
            raise _bad("Dimension ids must be unique within a call")
        ids.add(identifier)
        view = _name(reading.get("view"), "view")
        value, unit = reading.get("value"), reading.get("unit", "mm")
        if not _finite_number(value) or value <= 0:
            raise _bad("value must be a positive finite number read from the drawing")
        if not isinstance(unit, str) or unit not in UNIT_MM or not math.isfinite(value * UNIT_MM[unit]):
            raise _bad("unit must be mm, cm, m or in, with a finite converted value")
        line, surfaces = reading.get("line"), reading.get("surfaces")
        if not isinstance(line, list) or len(line) != 2 or not isinstance(surfaces, list) or len(surfaces) != 2:
            raise _bad("line and surfaces must each contain two endpoints in corresponding order")
        line = [_point(p, box) for p in line]
        anchors = []
        for surface in surfaces:
            if not isinstance(surface, dict) or set(surface) != {"name", "point"}:
                raise _bad("Each surface needs name and point")
            anchors.append({"name": _name(surface["name"], "surface name"), "point": _point(surface["point"], box)})
        if anchors[0]["name"] == anchors[1]["name"]:
            raise _bad("Use different names for the two measured surfaces/centres")
        delta = [b-a for a, b in zip(*line)]
        axis = int(abs(delta[1]) > abs(delta[0]))
        span = abs(delta[axis])
        if span < 1 or abs(delta[1-axis]) > PIXEL_TOLERANCE:
            raise _bad("Only horizontal/vertical linear dimensions are supported; inspect angles/radii normally")
        errors = [a["point"][axis] - p[axis] for a, p in zip(anchors, line)]
        checks.append({"id": identifier, "view": view, "value": value, "unit": unit,
                       "line": line, "surfaces": anchors, "axis": "xy"[axis],
                       "dimension_span_px": span,
                       "surface_span_px": abs(anchors[1]["point"][axis] - anchors[0]["point"][axis]),
                       "endpoint_errors_px": errors,
                       "aligned": all(abs(e) <= PIXEL_TOLERANCE for e in errors)})

    if source_crop is not None:
        for row in checks:
            row["raster_probe"] = raster_probe(source_crop, box, row)
    groups = defaultdict(list)
    for row in checks:
        groups[(row["view"], row["axis"])].append(row)
    solved = [_solve(view, axis, rows) for (view, axis), rows in groups.items()]
    return {"checks": checks, "groups": solved, "pixel_tolerance": PIXEL_TOLERANCE,
            "consistent": all(g["consistent"] for g in solved) if solved else None,
            "semantics_verified": False,
            "note": "Checks compare supplied anchors and equations only, not pixels/arrow recognition or OCR. "
                    "Inspect the unmarked panel: D1/D2 must be dimension-line endpoints, S1/S2 their actual "
                    "surface witnesses. Aligned anchors do not prove that text or surface names were read correctly. "
                    "Relative levels are in mm along source +x (right) or +y (down), not the CAD axes."}


def raster_probe(crop: Image.Image, box: list[int], row: dict) -> dict:
    """Expose nearby ink crossings independently of the proposed endpoint coordinates.

    This deliberately does not classify arrowheads, select endpoints or change the graph.
    A physical edge, text or hatch can produce a crossing too. Inspect the source region.
    """
    import numpy as np

    axis = "xy".index(row["axis"])
    points = row["line"]
    centre = round(sum(p[1-axis] for p in points)/2)
    margin = max(12, min(64, math.ceil(row["dimension_span_px"]/2)))
    lo = max(box[axis], math.floor(min(p[axis] for p in points))-margin)
    hi = min(box[axis+2], math.ceil(max(p[axis] for p in points))+margin+1)
    cross_lo, cross_hi = max(box[1-axis], centre-16), min(box[3-axis], centre+17)
    region = [lo, cross_lo, hi, cross_hi] if axis == 0 else [cross_lo, lo, cross_hi, hi]
    result = {"detail_region": region, "axis": row["axis"], "crossings": [],
              "note": "Raster ink crossings only, not recognized arrows or confirmed witnesses. "
                      "Inspect detail_region without overlays. Short dimensions may have OUTSIDE arrows: "
                      "the tip touches the witness, while the broad arrow base and shaft extend beyond it. "
                      "Neighbouring dimensions, text, hatching and edges may also cross the shaft."}
    if hi-lo > 4096:
        result["status"] = "region_too_long"
        result["note"] += " Raster scanning is limited to 4096 source pixels along the dimension."
        return result
    local = [region[i]-box[i % 2] for i in range(4)]
    values = np.asarray(crop.crop(local).convert("L"), dtype=float)
    # Rows follow the dimension axis; columns run perpendicular to it.
    if axis == 0:
        values = values.T
    background, dark = float(np.percentile(values, 90)), float(np.percentile(values, 5))
    contrast = background-dark
    if contrast < 24:
        result["status"] = "low_contrast"
        return result
    mask = values < background-max(16, min(64, contrast*.35))
    middle = centre-cross_lo
    crossings = []
    for offset, pixels in enumerate(mask):
        near = [i for i in range(max(0, middle-2), min(len(pixels), middle+3)) if pixels[i]]
        if not near:
            continue
        stem = min(near, key=lambda i: abs(i-middle))
        left = right = stem
        while left > 0 and pixels[left-1]:
            left -= 1
        while right+1 < len(pixels) and pixels[right+1]:
            right += 1
        reaches = [stem-left, right-stem]
        if max(reaches) >= 6:
            crossings.append((lo+offset, reaches))
    for coordinate, reaches in crossings:
        if result["crossings"] and coordinate == result["crossings"][-1]["range_px"][1]+1:
            previous = result["crossings"][-1]
            previous["range_px"][1] = coordinate
            previous["reach_px"] = [max(a, b) for a, b in zip(previous["reach_px"], reaches)]
        else:
            result["crossings"].append({"range_px": [coordinate, coordinate], "reach_px": reaches})
    result["status"] = "candidates" if crossings else "no_crossings_detected"
    return result


def _solve(view: str, axis: str, rows: list[dict]) -> dict:
    index = "xy".index(axis)
    positions, graph = defaultdict(list), defaultdict(list)
    issues = []
    scale_low, scale_high = 0.0, math.inf
    for row in rows:
        if not row["aligned"]:
            issues.append(f"{row['id']}: witness endpoints do not reach the claimed surface levels")
        a, b = row["surfaces"]
        for surface in (a, b):
            positions[surface["name"]].append(surface["point"][index])
        mm = row["value"] * UNIT_MM[row["unit"]]
        signed = math.copysign(mm, row["line"][1][index] - row["line"][0][index])
        graph[a["name"]].append((b["name"], signed))
        graph[b["name"]].append((a["name"], -signed))
        span = row["dimension_span_px"]
        scale_low = max(scale_low, max(0, span - 2*PIXEL_TOLERANCE) / mm)
        scale_high = min(scale_high, (span + 2*PIXEL_TOLERANCE) / mm)
    if scale_low > scale_high:
        issues.append("Callouts imply incompatible image scales; recheck text/endpoints or separate differently scaled views")
    for name, coords in positions.items():
        if max(coords) - min(coords) > 2*PIXEL_TOLERANCE:
            issues.append(f"{name}: the same named surface is anchored at different levels")
    levels, components = {}, []
    for root in sorted(graph, key=lambda n: sum(positions[n]) / len(positions[n])):
        if root in levels:
            continue
        levels[root] = 0.0
        todo, component = [root], []
        while todo:
            name = todo.pop()
            component.append(name)
            for other, gap in graph[name]:
                candidate = levels[name] + gap
                if not math.isfinite(candidate):
                    issues.append("Derived level is not finite")
                    continue
                if other not in levels:
                    levels[other] = candidate
                    todo.append(other)
                elif not math.isclose(levels[other], candidate, rel_tol=1e-8, abs_tol=1e-6):
                    issues.append(f"Inconsistent dimension cycle at {name} / {other}")
        components.append({"origin": root, "levels_mm": {n: round(levels[n], 6) for n in component}})
    return {"view": view, "axis": axis, "consistent": not issues, "issues": list(dict.fromkeys(issues)),
            "components": components if not issues else [],
            "note": "Each disconnected component has its own zero; their relative offsets are undetermined."}


def preview_point(point, box, rotate, size):
    """Map source pixel centres through the same crop/transpose/resize as Pillow."""
    x, y = point[0] - box[0], point[1] - box[1]
    w, h = box[2]-box[0], box[3]-box[1]
    if rotate == 90:
        x, y, w, h = h-1-y, x, h, w
    elif rotate == 180:
        x, y = w-1-x, h-1-y
    elif rotate == 270:
        x, y, w, h = y, w-1-x, h, w
    return [(x+0.5)*size[0]/w-0.5, (y+0.5)*size[1]/h-0.5]


def evidence_preview(crop, box, rotate, max_size, evidence):
    """Keep an unmarked panel next to the caller's hypotheses, within the image size budget."""
    gutter, header = 12, 24
    scale = min((max_size-gutter)/(2*crop.width), (max_size-header)/crop.height)
    size = (max(1, int(crop.width*scale)), max(1, int(crop.height*scale)))
    plain = crop.resize(size, Image.Resampling.LANCZOS)
    marked = plain.copy()
    draw = ImageDraw.Draw(marked)

    def point(p):
        return preview_point(p, box, rotate, size)

    def label(p, text, color="black"):
        x, y = p
        bounds = draw.textbbox((0, 0), text)
        x = min(max(1, x+5), max(1, size[0]-(bounds[2]-bounds[0])-2))
        y = min(max(1, y+3), max(1, size[1]-(bounds[3]-bounds[1])-4))
        draw.text((x, y), text, fill=color, stroke_width=2, stroke_fill="white")

    # Sparse source-coordinate guides; unlike a crop-local ruler these survive rotations.
    for axis in (0, 1):
        span = box[axis+2]-box[axis]
        step = 10**math.floor(math.log10(max(1, span/5)))
        step *= next(n for n in (1, 2, 5, 10) if n*step >= span/5)
        tick = math.ceil(box[axis]/step)*step
        while tick < box[axis+2]:
            a, b = [box[0], box[1]], [box[2]-1, box[3]-1]
            a[axis] = b[axis] = tick
            pa, pb = point(a), point(b)
            draw.line([tuple(pa), tuple(pb)], fill="#bcbcbc", width=1)
            label(pa, f"{'xy'[axis]}={tick:g}", "#555555")
            tick += step
    for number, row in enumerate(evidence["checks"], 1):
        color = "#146c43" if row["aligned"] else "#c2272d"
        line = [point(p) for p in row["line"]]
        draw.line([tuple(p) for p in line], fill="#d66b00", width=2)
        for end, (d, surface) in enumerate(zip(line, row["surfaces"]), 1):
            s = point(surface["point"])
            draw.line([tuple(d), tuple(s)], fill=color, width=1)
            for p, letter in ((d, "D"), (s, "S")):
                x, y = p
                draw.ellipse((x-4, y-4, x+4, y+4), outline=color, width=2)
                label(p, f"{number}{letter}{end}", color)
    sheet = Image.new("RGB", (size[0]*2+gutter, size[1]+header), "white")
    sheet.paste(plain, (0, header))
    sheet.paste(marked, (size[0]+gutter, header))
    title = ImageDraw.Draw(sheet)
    title.text((2, 4), "SOURCE (unmarked)", fill="black")
    title.text((size[0]+gutter+2, 4), "ANCHORS (caller supplied)", fill="black")
    panels = [{"kind": name, "origin": [x, header], "size": list(size)}
              for name, x in (("source", 0), ("anchors", size[0]+gutter))]
    return sheet, scale, panels
