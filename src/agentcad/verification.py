"""Bind physical requirements to dimension anchors, independently of displayed text."""

from __future__ import annotations

import math

from . import geom as G
from .errors import input_error
from .model import circle_wcs
from .validate.checks import crosses, dimension_plain_text, text_values
from .validate.features import extract


def _binding_geometry(doc):
    """Preserve finite arc sweeps, including bulged polyline segments."""
    segments, curves = [], []
    for entity in doc.modelspace():
        if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}:
            primitives = entity.virtual_entities()
        else:
            primitives = (entity,)
        for e in primitives:
            if e.dxftype() == "LINE":
                segments.append((tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]))
            elif e.dxftype() in {"ARC", "CIRCLE"}:
                c, r, start, end = circle_wcs(e)
                curves.append(G.Circ(c, r, start if e.dxftype() == "ARC" else None, end))
    return segments, curves


def verify_dimensions(doc, requirements, tolerance=1e-6):
    features = extract(doc)
    segments, curves = _binding_geometry(doc)
    dimensions = {d["id"]: d for d in features.dimensions}
    rows, findings = [], []
    ids = set()
    for req in requirements:
        if (
            not isinstance(req, dict)
            or set(req) - {"id", "handle", "value", "tolerance"}
            or not {"id", "handle", "value"} <= set(req)
        ):
            raise input_error(
                "BAD_REQUIREMENT", "Dimension requirements need id, handle, value and optional tolerance"
            )
        if (
            not isinstance(req["id"], str)
            or not req["id"]
            or req["id"] in ids
            or not isinstance(req["handle"], str)
        ):
            raise input_error("BAD_REQUIREMENT", "Requirements need unique nonempty ids and string handles")
        ids.add(req["id"])
        for key, v in (("value", req["value"]), ("tolerance", req.get("tolerance", tolerance))):
            if (
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or key == "tolerance"
                and v < 0
            ):
                raise input_error(
                    "BAD_REQUIREMENT", "Values must be finite numbers; tolerance must be nonnegative"
                )
        d = dimensions.get(req["handle"])
        tol = float(req.get("tolerance", tolerance))
        if tol < 0:
            raise input_error("BAD_PARAMETER", "tolerance cannot be negative")
        bound = bool(d and d["anchors"] and d["measurement"] is not None)
        if bound:
            for a in d["anchors"]:
                attached = any(G.dist(a, p) <= tol for p, _ in features.points)
                attached |= any(
                    abs(G.dist(a, curve.c) - curve.r) <= tol
                    and (
                        curve.start is None
                        or G.angle_in_arc(
                            G.angle_of(G.sub(a, curve.c)),
                            curve.start,
                            curve.end,
                            math.degrees(tol / max(curve.r, 1e-12)),
                        )
                    )
                    for curve in curves
                )
                attached |= any(
                    G.dist_to_segment(a, start, end) <= tol and crosses(start, end, d["direction"])
                    for start, end in segments
                )
                bound &= attached
        actual = d["measurement"] if bound else None
        displayed = None if not d else d["displayed"]
        if d and (d["text"] or "").strip() and "<>" not in d["text"]:
            values = text_values(dimension_plain_text(d["text"]))
            displayed = values[0] if len(values) == 1 else None
        ok = actual is not None and abs(actual - req["value"]) <= tol
        row_findings = []
        if not bound:
            row_findings.append("dimension_unbound")
        elif displayed is None or abs(displayed - actual) > tol:
            row_findings.append("dimension_mismatch")
        for kind in row_findings:
            findings.append({"requirement": req["id"], "kind": kind, "handle": req["handle"]})
        rows.append(
            {
                "id": req["id"],
                "handle": req["handle"],
                "status": "pass" if ok else "fail",
                "measured": actual,
                "displayed": displayed,
                "bound": bound,
                "findings": row_findings,
            }
        )
    return {
        "rows": rows,
        "findings": findings,
        "accepted": bool(rows) and all(r["status"] == "pass" for r in rows) and not findings,
    }
