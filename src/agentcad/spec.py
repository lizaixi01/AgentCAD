"""Structured part specifications.

A spec is the agent-facing description of design intent. It is compiled into
(1) an operation plan with stable tags (executed by the op engine) and (2) a
list of requirements derived *from the spec only* (checked by the independent
validator against the file). Supported kinds:

``plate`` — rectangular plate with holes::

    {"kind": "plate", "units": "mm", "width": 100, "height": 60,
     "corner_radius": 0, "thickness": 3, "material": "Q235", "name": "Mounting plate",
     "holes": [{"pattern": "corners", "diameter": 8, "edge_offset": 10},
               {"pattern": "single", "diameter": 12, "center": [50, 30]}],
     "dimensions": "full", "center_marks": true,
     "sheet": "A4" | null, "title_block": {"TITLE": "...", "DWG_NO": "..."} | null}

``plan`` — a raw operation list plus optional requirements::

    {"kind": "plan", "units": "mm", "operations": [...], "requirements": [...]}
"""
from __future__ import annotations

import copy
from typing import Any

from .errors import AgentCADError, spec_error
from .units import normalize_unit

SHEETS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0)}
LAYERS = [
    {"op": "create_layer", "name": "OUTLINE", "color": 7, "lineweight": 50, "if_exists": "skip"},
    {"op": "create_layer", "name": "HOLES", "color": 7, "lineweight": 50, "if_exists": "skip"},
    {"op": "create_layer", "name": "CENTER", "color": 1, "linetype": "CENTER", "lineweight": 25, "if_exists": "skip"},
    {"op": "create_layer", "name": "DIM", "color": 3, "lineweight": 18, "if_exists": "skip"},
    {"op": "create_layer", "name": "TEXT", "color": 7, "lineweight": 25, "if_exists": "skip"},
    {"op": "create_layer", "name": "BORDER", "color": 7, "lineweight": 50, "if_exists": "skip"},
]


def _num(spec: dict, key: str, path: str, *, required=True, gt: float | None = 0.0, issues: list) -> float | None:
    v = spec.get(key)
    if v is None:
        if required:
            issues.append({"code": "SPEC_MISSING_PARAM", "path": f"{path}{key}", "message": f"Missing required '{key}'"})
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        issues.append({"code": "SPEC_INVALID_VALUE", "path": f"{path}{key}", "message": f"'{key}' must be a number"})
        return None
    if gt is not None and v <= gt:
        issues.append({"code": "SPEC_INVALID_VALUE", "path": f"{path}{key}", "message": f"'{key}' must be > {gt}"})
        return None
    return float(v)


def expand_holes(spec: dict, issues: list) -> list[dict[str, Any]]:
    """Resolve hole patterns into concrete holes (tag, center relative to plate lower-left, diameter)."""
    W, H = spec.get("width"), spec.get("height")
    out: list[dict[str, Any]] = []
    for i, h in enumerate(spec.get("holes") or []):
        path = f"holes[{i}]."
        pat = h.get("pattern", "single")
        d = _num(h, "diameter", path, issues=issues)
        if pat == "corners":
            ox = h.get("edge_offset_x", h.get("edge_offset"))
            oy = h.get("edge_offset_y", h.get("edge_offset"))
            if ox is None or oy is None:
                issues.append({"code": "SPEC_MISSING_PARAM", "path": path + "edge_offset",
                               "message": "Corner holes need 'edge_offset' (or edge_offset_x / edge_offset_y)"})
                continue
            if d is None or W is None or H is None:
                continue
            for name, cx, cy in (("bl", ox, oy), ("br", W - ox, oy), ("tr", W - ox, H - oy), ("tl", ox, H - oy)):
                out.append({"tag": f"hole.{name}", "center": [cx, cy], "diameter": d, "group": i,
                            "edge_ref": {"x": "left" if name in ("bl", "tl") else "right",
                                         "y": "bottom" if name in ("bl", "br") else "top"},
                            "edge_offset": [ox, oy], "source": h.get("source")})
        elif pat == "single":
            c = h.get("center")
            if not (isinstance(c, list) and len(c) == 2):
                issues.append({"code": "SPEC_MISSING_PARAM", "path": path + "center", "message": "Single hole needs 'center' [x, y]"})
                continue
            if d is None:
                continue
            out.append({"tag": h.get("tag", f"hole.{i}"), "center": [float(c[0]), float(c[1])], "diameter": d,
                        "group": i, "source": h.get("source")})
        else:
            issues.append({"code": "SPEC_INVALID_VALUE", "path": path + "pattern", "message": f"Unknown hole pattern {pat!r}"})
    return out


def check_plate(spec: dict) -> tuple[list[dict], list[dict]]:
    """Validate a plate spec. Returns (issues, expanded holes)."""
    issues: list[dict] = []
    if not spec.get("units"):
        issues.append({"code": "UNITS_UNDEFINED", "path": "units", "message": "Spec must state its length unit"})
    else:
        try:
            normalize_unit(spec["units"])
        except AgentCADError as exc:
            issues.append({"code": exc.code, "path": "units", "message": exc.message})
    W = _num(spec, "width", "", issues=issues)
    H = _num(spec, "height", "", issues=issues)
    r = _num(spec, "corner_radius", "", required=False, gt=None, issues=issues) or 0.0
    if r < 0:
        issues.append({"code": "SPEC_INVALID_VALUE", "path": "corner_radius", "message": "corner_radius must be >= 0"})
    if W and H and r * 2 > min(W, H):
        issues.append({"code": "SPEC_CONFLICT", "path": "corner_radius",
                       "message": f"corner_radius {r} exceeds half the shorter side"})
    holes = expand_holes(spec, issues)
    if W and H:
        for h in holes:
            cx, cy = h["center"]
            rad = h["diameter"] / 2
            if cx - rad < 0 or cy - rad < 0 or cx + rad > W or cy + rad > H:
                issues.append({"code": "SPEC_CONFLICT", "path": h["tag"],
                               "message": f"Hole {h['tag']} (center {h['center']}, Ø{h['diameter']}) breaks the plate edge "
                                          f"({W} x {H})", "source": h.get("source")})
        for i in range(len(holes)):
            for j in range(i + 1, len(holes)):
                a, b = holes[i], holes[j]
                dd = ((a["center"][0] - b["center"][0]) ** 2 + (a["center"][1] - b["center"][1]) ** 2) ** 0.5
                if dd < (a["diameter"] + b["diameter"]) / 2 - 1e-9:
                    issues.append({"code": "SPEC_CONFLICT", "path": f"{a['tag']},{b['tag']}",
                                   "message": f"Holes {a['tag']} and {b['tag']} overlap (center distance {dd:.6g})"})
    if spec.get("sheet") and spec["sheet"] not in SHEETS:
        issues.append({"code": "SPEC_INVALID_VALUE", "path": "sheet", "message": f"Unknown sheet {spec['sheet']!r}"})
    return issues, holes


def raise_if_issues(issues: list[dict]) -> None:
    if issues:
        codes = {i["code"] for i in issues}
        code = "SPEC_CONFLICT" if "SPEC_CONFLICT" in codes else ("UNITS_UNDEFINED" if codes == {"UNITS_UNDEFINED"}
                                                                 else "SPEC_INVALID")
        raise spec_error(code, f"Specification has {len(issues)} problem(s): " + "; ".join(i["message"] for i in issues),
                         details={"issues": issues}, hint="Fix or supply the listed values; nothing was drawn")


def plate_origin(spec: dict) -> tuple[float, float]:
    if spec.get("origin"):
        return float(spec["origin"][0]), float(spec["origin"][1])
    if spec.get("sheet"):
        return 30.0, 60.0  # leave room for dimensions and the title block
    return 0.0, 0.0


def compile_plate(spec: dict) -> dict[str, Any]:
    """Spec -> {operations, requirements}. Requirements are derived from the spec values only."""
    issues, holes = check_plate(spec)
    raise_if_issues(issues)
    W, H = float(spec["width"]), float(spec["height"])
    ox, oy = plate_origin(spec)
    r = float(spec.get("corner_radius") or 0.0)
    ops: list[dict[str, Any]] = copy.deepcopy(LAYERS)
    ops.append({"op": "add_rectangle", "corner": [ox, oy], "width": W, "height": H, "corner_radius": r,
                "layer": "OUTLINE", "tag": "outline"})
    for h in holes:
        c = [ox + h["center"][0], oy + h["center"][1]]
        ops.append({"op": "add_circle", "center": c, "diameter": h["diameter"], "layer": "HOLES", "tag": h["tag"]})
        if spec.get("center_marks", True):
            ext = h["diameter"] / 2 + max(2.0, h["diameter"] * 0.25)
            ops.append({"op": "add_line", "start": [c[0] - ext, c[1]], "end": [c[0] + ext, c[1]], "layer": "CENTER",
                        "tag": f"cl.{h['tag']}.h"})
            ops.append({"op": "add_line", "start": [c[0], c[1] - ext], "end": [c[0], c[1] + ext], "layer": "CENTER",
                        "tag": f"cl.{h['tag']}.v"})
    reqs: list[dict[str, Any]] = [{"id": "outline", "type": "outline", "width": W, "height": H, "layer": "OUTLINE",
                                   "source": spec.get("source", {}).get("width")}]
    for h in holes:
        reqs.append({"id": h["tag"], "type": "hole", "center": h["center"], "diameter": h["diameter"],
                     "outline_layer": "OUTLINE", "layer": "HOLES", "source": h.get("source")})
    if holes:
        reqs.append({"id": "hole_count", "type": "hole_count", "count": len(holes), "outline_layer": "OUTLINE",
                     "layer": "HOLES"})
        for d in sorted({h["diameter"] for h in holes}):
            reqs.append({"id": f"hole_count.d{d:g}", "type": "hole_count", "diameter": d,
                         "count": sum(1 for h in holes if h["diameter"] == d), "outline_layer": "OUTLINE", "layer": "HOLES"})
    dims = spec.get("dimensions", "full")
    if dims != "none":
        th = 3.5 if (normalize_unit(spec["units"]) == "mm") else 0.14
        off = 10.0 if normalize_unit(spec["units"]) == "mm" else 0.4
        dim = {"layer": "DIM"}
        # a negative offset lies to the right of p1->p2: below for the horizontal dims, while the upward
        # vertical dims need a positive offset to land left of the plate (outside it, not across the holes)
        ops.append({"op": "add_linear_dim", "p1": [ox, oy], "p2": [ox + W, oy], "orientation": "horizontal",
                    "offset": -2 * off, "tag": "dim.width", **dim})
        ops.append({"op": "add_linear_dim", "p1": [ox, oy], "p2": [ox, oy + H], "orientation": "vertical",
                    "offset": 2 * off, "tag": "dim.height", **dim})
        reqs += [{"id": "dim.width", "type": "dimension", "kind": "linear", "value": W},
                 {"id": "dim.height", "type": "dimension", "kind": "linear", "value": H}]
        if r > 0:
            ops.append({"op": "add_radius_dim", "center": [ox + W - r, oy + H - r], "radius": r, "angle": 45,
                        "tag": "dim.corner_radius", **dim})
            reqs.append({"id": "dim.corner_radius", "type": "dimension", "kind": "radius", "value": r})
        groups: dict[int, list[dict]] = {}
        for h in holes:
            groups.setdefault(h["group"], []).append(h)
        for g, hs in groups.items():
            first = hs[0]
            c0 = [ox + first["center"][0], oy + first["center"][1]]
            n = len(hs)
            ops.append({"op": "add_diameter_dim", "target": f"tag:{first['tag']}", "angle": 45,
                        "text": (f"{n}X <>" if n > 1 else "<>"), "tag": f"dim.holes{g}.dia", **dim})
            reqs.append({"id": f"dim.holes{g}.dia", "type": "dimension", "kind": "diameter", "value": first["diameter"]})
            # position of the first hole of the group from the left / bottom edge
            ops.append({"op": "add_linear_dim", "p1": [ox, oy], "p2": c0, "orientation": "horizontal",
                        "offset": -off, "tag": f"dim.holes{g}.x", **dim})
            ops.append({"op": "add_linear_dim", "p1": [ox, oy], "p2": c0, "orientation": "vertical",
                        "offset": off, "tag": f"dim.holes{g}.y", **dim})
            reqs += [{"id": f"dim.holes{g}.x", "type": "dimension", "kind": "linear", "value": first["center"][0]},
                     {"id": f"dim.holes{g}.y", "type": "dimension", "kind": "linear", "value": first["center"][1]}]
            if n == 4 and all("edge_ref" in h for h in hs):
                br = next(h for h in hs if h["tag"].endswith("br"))
                tl = next(h for h in hs if h["tag"].endswith("tl"))
                tr = next(h for h in hs if h["tag"].endswith("tr"))
                cbr = [ox + br["center"][0], oy + br["center"][1]]
                ctl = [ox + tl["center"][0], oy + tl["center"][1]]
                ctr = [ox + tr["center"][0], oy + tr["center"][1]]
                pitch_x = tr["center"][0] - tl["center"][0]
                pitch_y = tr["center"][1] - br["center"][1]
                # anchored on the holes nearest the dimension line, so extension lines stay short
                ops.append({"op": "add_linear_dim", "p1": ctl, "p2": ctr, "orientation": "horizontal",
                            "base": [ctl[0], oy + H + off], "tag": f"dim.holes{g}.pitch_x", **dim})
                ops.append({"op": "add_linear_dim", "p1": cbr, "p2": ctr, "orientation": "vertical",
                            "base": [ox + W + off, cbr[1]], "tag": f"dim.holes{g}.pitch_y", **dim})
                reqs += [{"id": f"dim.holes{g}.pitch_x", "type": "dimension", "kind": "linear", "value": pitch_x},
                         {"id": f"dim.holes{g}.pitch_y", "type": "dimension", "kind": "linear", "value": pitch_y}]
        for o in ops:
            if o.get("op", "").startswith("add_") and "dim" in o["op"]:
                o.setdefault("text_height", th)
    if spec.get("sheet"):
        sw, sh = SHEETS[spec["sheet"]]
        ops.append({"op": "add_rectangle", "corner": [0, 0], "width": sw, "height": sh, "layer": "BORDER",
                    "tag": "sheet.trim"})
        ops.append({"op": "add_rectangle", "corner": [10, 10], "width": sw - 20, "height": sh - 20, "layer": "BORDER",
                    "tag": "sheet.border"})
        reqs.append({"id": "within_sheet", "type": "within_bounds", "min": [0, 0], "max": [sw, sh]})
    if spec.get("title_block") is not None:
        fields = {"TITLE": spec.get("name", "PART"), "MATERIAL": spec.get("material", ""), "SCALE": "1:1",
                  "SHEET": "1/1", **(spec.get("title_block") or {})}
        corner = [SHEETS[spec["sheet"]][0] - 10, 10] if spec.get("sheet") else [ox + W + 200, oy - 40]
        ops.append({"op": "add_title_block", "insert": corner, "fields": fields, "layer": "BORDER", "tag": "title_block"})
        reqs.append({"id": "title", "type": "text", "contains": fields["TITLE"]})
    notes = []
    if spec.get("material"):
        notes.append(f"MATERIAL: {spec['material']}")
    if spec.get("thickness"):
        notes.append(f"THICKNESS: {spec['thickness']} {spec['units']}")
    if notes:
        ops.append({"op": "add_mtext", "text": "\\P".join(notes), "insert": [ox, oy - 35 if spec.get("sheet") else oy - 40],
                    "char_height": 3.5 if normalize_unit(spec["units"]) == "mm" else 0.14, "layer": "TEXT", "tag": "notes"})
        if spec.get("material"):
            reqs.append({"id": "material", "type": "text", "contains": str(spec["material"]),
                         "source": spec.get("source", {}).get("material")})
    return {"units": normalize_unit(spec["units"]), "operations": ops, "requirements": reqs}


def compile_spec(spec: dict) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise spec_error("SPEC_INVALID", "Spec must be a JSON object")
    kind = spec.get("kind")
    if kind == "plate":
        return compile_plate(spec)
    if kind == "plan":
        if not spec.get("units"):
            raise spec_error("UNITS_UNDEFINED", "Plan must state 'units'")
        ops = spec.get("operations")
        if not isinstance(ops, list) or not ops:
            raise spec_error("SPEC_MISSING_PARAM", "Plan needs a non-empty 'operations' list")
        return {"units": normalize_unit(spec["units"]), "operations": ops, "requirements": spec.get("requirements", [])}
    raise spec_error("SPEC_INVALID", f"Unknown spec kind {kind!r}", hint="Use 'plate' or 'plan'")


def merge(base: dict, changes: dict) -> dict:
    """Deep merge; lists are replaced; ``null`` deletes a key."""
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
