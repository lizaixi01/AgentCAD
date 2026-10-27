"""Generic drawing-integrity checks (no spec needed)."""
from __future__ import annotations

import math
import re
from typing import Any

from ezdxf import bbox
from ezdxf.document import Drawing

from .. import geom as G
from ..model import circle_wcs, get_tag
from ..units import unit_from_insunits
from .features import Features, measure_dimension

NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def issue(code: str, severity: str, message: str, entities: list[str] | None = None, **details: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"code": code, "severity": severity, "category": "geometry",
                         "message": message, "entities": entities or []}
    if details:
        d["details"] = details
    return d


def _finite(*vals: float) -> bool:
    return all(math.isfinite(v) for v in vals)


def geometry_key(e, q: float) -> tuple | None:
    """Canonical rounded geometry key for duplicate detection."""
    t = e.dxftype()
    x = e.dxf

    def rp(p):
        return (round(p[0] / q), round(p[1] / q))

    if t == "LINE":
        a, b = rp(x.start), rp(x.end)
        return (t, x.layer, min(a, b), max(a, b))
    if t == "CIRCLE":
        return (t, x.layer, rp(x.center), round(x.radius / q))
    if t == "ARC":
        c, rad, s, en = circle_wcs(e)
        return (t, x.layer, rp(c), round(rad / q), round(s, 4), round(en, 4))
    if t == "LWPOLYLINE":
        pts = tuple(rp(p) + (round(b, 6),) for *p, b in ((p[0], p[1], p[2]) for p in e.get_points("xyb")))
        return (t, x.layer, bool(e.closed), pts)
    if t == "POINT":
        return (t, x.layer, rp(x.location))
    if t in ("TEXT",):
        return (t, x.layer, rp(x.insert), x.text)
    if t == "INSERT":
        return (t, x.layer, x.name, rp(x.insert), round(x.rotation, 6))
    if t == "DIMENSION":
        m = measure_dimension(e)[1]
        return (t, x.layer, x.dimtype & 0x0F, round(x.get("angle", 0.0) % 180, 6),
                rp(x.defpoint2) if x.hasattr("defpoint2") else rp(x.defpoint),
                rp(x.defpoint3) if x.hasattr("defpoint3") else rp(x.defpoint4), None if m is None else round(m / q))
    return None


XDATA_LIMIT = 16 * 1024


def xdata_issues(doc: Drawing, e) -> list[dict[str, Any]]:
    """AutoCAD 2027 discards the *entire* drawing on DXFIN when an entity carries XDATA
    of an unregistered APPID or more than 16 KB of XDATA (research/autocad, exp_blocked_items)."""
    xd = getattr(e, "xdata", None)
    if not xd or not xd.data:
        return []
    out = []
    size = 0
    for app, tags in xd.data.items():
        if app not in doc.appids:
            out.append(issue("XDATA_APPID_UNREGISTERED", "error",
                             f"XDATA uses APPID {app!r} that is not in the APPID table; AutoCAD rejects the whole file",
                             [e.dxf.handle], appid=app))
        size += len(app) + sum(len(str(t.value).encode("utf-8")) + 2 for t in tags)
    if size > XDATA_LIMIT:
        out.append(issue("XDATA_TOO_LARGE", "error", f"XDATA of {size} bytes exceeds AutoCAD's 16 KB per entity; "
                         "AutoCAD rejects the whole file", [e.dxf.handle], bytes=size))
    return out


def run_generic_checks(doc: Drawing, feats: Features, *, bounds: list | None = None,
                       tolerance: float = 1e-6, contour_layers: list[str] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    msp = doc.modelspace()
    ins = doc.header.get("$INSUNITS", 0)
    if unit_from_insunits(ins) is None:
        out.append(issue("UNITS_UNDEFINED", "warning", f"$INSUNITS={ins} is not a supported explicit length unit"))

    seen: dict[tuple, str] = {}
    for e in msp:
        t = e.dxftype()
        h = e.dxf.handle
        x = e.dxf
        # degenerate / invalid geometry
        if t == "LINE":
            if not _finite(x.start.x, x.start.y, x.end.x, x.end.y):
                out.append(issue("INVALID_COORDINATE", "error", "Non-finite coordinate", [h]))
            elif (x.end - x.start).magnitude < tolerance:
                out.append(issue("DEGENERATE_GEOMETRY", "error", "Zero-length line", [h]))
        elif t in ("CIRCLE", "ARC"):
            if not _finite(x.center.x, x.center.y, x.radius):
                out.append(issue("INVALID_COORDINATE", "error", "Non-finite coordinate/radius", [h]))
            elif x.radius <= tolerance:
                out.append(issue("DEGENERATE_GEOMETRY", "error", f"Radius {x.radius} <= 0", [h]))
        elif t == "LWPOLYLINE":
            pts = e.get_points("xy")
            if len({(round(p[0], 9), round(p[1], 9)) for p in pts}) < 2:
                out.append(issue("DEGENERATE_GEOMETRY", "error", "Polyline has fewer than 2 distinct vertices", [h]))
        elif t == "INSERT" and x.name not in doc.blocks:
            out.append(issue("UNDEFINED_BLOCK", "error", f"Block {x.name!r} is not defined", [h]))
        if x.layer not in doc.layers:
            out.append(issue("UNDEFINED_LAYER", "warning", f"Layer {x.layer!r} has no layer table entry", [h]))
        if t == "ARC" and not (0 <= x.start_angle < 360 and 0 <= x.end_angle < 360):
            out.append(issue("ARC_ANGLE_NOT_NORMALIZED", "warning",
                             f"Arc angles {x.start_angle}/{x.end_angle} outside [0, 360): AutoCAD AUDIT reports them", [h]))
        out.extend(xdata_issues(doc, e))
        # duplicates
        k = geometry_key(e, max(tolerance, 1e-9))
        if k is not None:
            if k in seen:
                out.append(issue("DUPLICATE_ENTITY", "error", f"{t} {h} duplicates {seen[k]}", [seen[k], h]))
            else:
                seen[k] = h

    # dimensions: stored text / measurement consistent with definition points
    for d in feats.dimensions:
        if d["measurement"] is None:
            out.append(issue("DIMENSION_UNMEASURABLE", "warning", "Dimension type cannot be re-measured", [d["id"]]))
            continue
        txt = (d["text"] or "").strip()
        if txt and "<>" not in txt:
            nums = [float(n) for n in NUM_RE.findall(txt)]
            if nums and not any(abs(n - d["measurement"]) <= max(tolerance, 0.005 * max(1, abs(n))) for n in nums):
                out.append(issue("DIMENSION_TEXT_MISMATCH", "error",
                                 f"Dimension text {txt!r} disagrees with measured value {d['measurement']:.6g}",
                                 [d["id"]], expected=d["measurement"], actual_text=txt))
        stored = d.get("stored")
        if stored is not None and d["kind"] in ("angular", "angular3p"):
            stored = math.degrees(stored)  # group 42 holds radians for angular dimensions
        if stored is not None and abs(stored - d["measurement"]) > max(tolerance, 1e-6):
            out.append(issue("DIMENSION_STALE", "warning",
                             f"Stored measurement {stored:.6g} != re-measured {d['measurement']:.6g}", [d["id"]]))
        snap = max(tolerance, 1e-6) * 10
        for a in d["anchors"]:
            on_point = any(G.dist(a, p) <= snap for p, _ in feats.points)
            on_curve = any(abs(G.dist(a, c) - r) <= snap for c, r, _ in feats.curves)
            if not (on_point or on_curve):
                out.append(issue("DIMENSION_NOT_ATTACHED", "warning",
                                 f"Dimension anchor {list(map(lambda v: round(v, 6), a))} is not on any geometry point",
                                 [d["id"]]))
                break

    # contours that should be closed
    for layer in contour_layers or []:
        for chain in feats.open_chains:
            ents = [doc.entitydb[h] for h in chain]
            if ents and ents[0].dxf.layer == layer:
                out.append(issue("OPEN_CONTOUR", "error", f"Open contour on layer {layer!r}", chain))

    # bounds
    if bounds:
        (bx0, by0), (bx1, by1) = bounds
        for e in msp:
            try:
                ext = bbox.extents([e], fast=True)
            except Exception:
                continue
            if not ext.has_data:
                continue
            if ext.extmin.x < bx0 - tolerance or ext.extmin.y < by0 - tolerance or \
               ext.extmax.x > bx1 + tolerance or ext.extmax.y > by1 + tolerance:
                out.append(issue("OUT_OF_BOUNDS", "error",
                                 f"{e.dxftype()} {e.dxf.handle} extends outside the drawing bounds",
                                 [e.dxf.handle], bounds=bounds,
                                 extents=[[round(ext.extmin.x, 6), round(ext.extmin.y, 6)],
                                          [round(ext.extmax.x, 6), round(ext.extmax.y, 6)]],
                                 tag=get_tag(e)))
    return out
