"""Drawing data model: entity serialization, tags and entity selection.

Entity identity is the DXF handle (stable across save/reload). Agents may also
attach a semantic *tag* (stored as XDATA under the ``AGENTCAD`` appid) and
refer to entities by tag, which survives regeneration of geometry.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

from .errors import input_error

APPID = "AGENTCAD"
ROUND = 6

SUPPORTED_TYPES = {
    "LINE", "CIRCLE", "ARC", "LWPOLYLINE", "ELLIPSE", "SPLINE", "POINT",
    "TEXT", "MTEXT", "DIMENSION", "INSERT", "LEADER", "MULTILEADER", "HATCH",
}


def r(v: float) -> float:
    x = round(float(v), ROUND)
    return 0.0 if x == 0 else x


def pt(v: Any) -> list[float]:
    return [r(v[0]), r(v[1])]


# --- tags ------------------------------------------------------------------

def ensure_appid(doc: Drawing) -> None:
    if APPID not in doc.appids:
        doc.appids.add(APPID)


def get_tag(e: DXFGraphic) -> str | None:
    try:
        if e.has_xdata(APPID):
            for code, value in e.get_xdata(APPID):
                if code == 1000 and isinstance(value, str) and value.startswith("tag="):
                    return value[4:]
    except Exception:  # malformed xdata must never break inspection
        return None
    return None


def set_tag(doc: Drawing, e: DXFGraphic, tag: str | None) -> None:
    if tag is None:
        if e.has_xdata(APPID):
            e.discard_xdata(APPID)
        return
    ensure_appid(doc)
    e.set_xdata(APPID, [(1000, f"tag={tag}")])


def tag_index(doc: Drawing) -> dict[str, list[DXFGraphic]]:
    idx: dict[str, list[DXFGraphic]] = {}
    for e in doc.modelspace():
        t = get_tag(e)
        if t is not None:
            idx.setdefault(t, []).append(e)
    return idx


# --- serialization -----------------------------------------------------------

def entity_to_dict(e: DXFGraphic, *, detail: bool = True) -> dict[str, Any]:
    t = e.dxftype()
    d: dict[str, Any] = {"id": e.dxf.handle, "type": t, "layer": e.dxf.layer}
    tag = get_tag(e)
    if tag is not None:
        d["tag"] = tag
    if not detail:
        return d
    if e.dxf.hasattr("color"):
        d["color"] = e.dxf.color
    if e.dxf.hasattr("linetype"):
        d["linetype"] = e.dxf.linetype
    if e.dxf.hasattr("lineweight"):
        d["lineweight"] = e.dxf.lineweight
    d.update(geometry_of(e))
    return d


def flipped_ocs(e: DXFGraphic) -> bool:
    """True for extrusion (0,0,-1): AutoCAD keeps such entities as they are, so
    every reader must map OCS to WCS (x -> -x, angles a -> 180-a, bulge -> -bulge)."""
    if not e.dxf.hasattr("extrusion"):
        return False
    ex = e.dxf.extrusion
    return abs(ex[0]) < 1e-12 and abs(ex[1]) < 1e-12 and ex[2] < 0


def circle_wcs(e: DXFGraphic) -> tuple[tuple[float, float], float, float | None, float | None]:
    """(center, radius, start, end) of a CIRCLE/ARC in WCS, angles CCW in [0, 360)."""
    c = e.dxf.center
    s = e.dxf.get("start_angle") if e.dxftype() == "ARC" else None
    en = e.dxf.get("end_angle") if e.dxftype() == "ARC" else None
    if flipped_ocs(e):
        center = (-c.x, c.y)
        if s is not None:
            s, en = 180.0 - en, 180.0 - s
    else:
        center = (c.x, c.y)
    if s is not None:
        s, en = s % 360.0, en % 360.0
    return center, e.dxf.radius, s, en


def lwpoly_wcs(e: DXFGraphic) -> list[tuple[float, float, float]]:
    pts = [(px, py, b) for px, py, _s, _e, b in e.get_points("xyseb")]
    if flipped_ocs(e):
        pts = [(-px, py, -b) for px, py, b in pts]
    return pts


def geometry_of(e: DXFGraphic) -> dict[str, Any]:
    t = e.dxftype()
    x = e.dxf
    if t == "LINE":
        return {"start": pt(x.start), "end": pt(x.end), "length": r((x.end - x.start).magnitude)}
    if t == "CIRCLE":
        c, rad, _, _ = circle_wcs(e)
        return {"center": pt(c), "radius": r(rad), "diameter": r(2 * rad)}
    if t == "ARC":
        c, rad, s, en = circle_wcs(e)
        return {"center": pt(c), "radius": r(rad), "start_angle": r(s), "end_angle": r(en)}
    if t == "LWPOLYLINE":
        pts = []
        for px, py, b in lwpoly_wcs(e):
            pts.append([r(px), r(py), r(b)] if abs(b) > 1e-12 else [r(px), r(py)])
        return {"points": pts, "closed": bool(e.closed)}
    if t == "ELLIPSE":
        return {"center": pt(x.center), "major_axis": pt(x.major_axis), "ratio": r(x.ratio),
                "start_param": r(x.start_param), "end_param": r(x.end_param)}
    if t == "SPLINE":
        return {"degree": x.degree, "fit_points": [pt(p) for p in e.fit_points],
                "control_points": [pt(p) for p in e.control_points], "closed": bool(e.closed)}
    if t == "POINT":
        return {"location": pt(x.location)}
    if t == "TEXT":
        return {"text": x.text, "insert": pt(x.insert), "height": r(x.height), "rotation": r(x.rotation)}
    if t == "MTEXT":
        # width 0 and "absent" both mean "no wrapping" (AutoCAD writes 0 explicitly)
        w = x.get("width", 0.0)
        return {"text": e.text, "insert": pt(x.insert), "char_height": r(x.char_height),
                "width": r(w) if w and w > 0 else None}
    if t == "DIMENSION":
        return dimension_info(e)
    if t == "INSERT":
        attribs = {a.dxf.tag: a.dxf.text for a in e.attribs}
        return {"block": x.name, "insert": pt(x.insert), "rotation": r(x.rotation),
                "scale": [r(x.xscale), r(x.yscale)], "attributes": attribs}
    if t == "LEADER":
        return {"vertices": [pt(v) for v in e.vertices]}
    return {}


DIMTYPES = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular3p", 6: "ordinate"}


def dimension_info(e: DXFGraphic) -> dict[str, Any]:
    x = e.dxf
    kind = DIMTYPES.get(x.dimtype & 0x0F, "unknown")
    info: dict[str, Any] = {"dimtype": kind, "text_override": x.text if x.hasattr("text") else ""}
    defs = {}
    for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
        if x.hasattr(name):
            defs[name] = pt(x.get(name))
    info["defpoints"] = defs
    if kind == "linear":
        info["angle"] = r(x.get("angle", 0.0))
    m = measure_dimension(e)
    info["measurement"] = None if m is None else r(m)
    return info


def measure_dimension(e: DXFGraphic) -> float | None:
    """Recompute the dimension value from its definition points (do not trust
    the stored text or group 42)."""
    x = e.dxf
    kind = DIMTYPES.get(x.dimtype & 0x0F)
    try:
        if kind == "linear":
            p1, p2 = x.defpoint2, x.defpoint3
            a = math.radians(x.get("angle", 0.0))
            ux, uy = math.cos(a), math.sin(a)
            return abs((p2.x - p1.x) * ux + (p2.y - p1.y) * uy)
        if kind == "aligned":
            return (x.defpoint3 - x.defpoint2).magnitude
        if kind == "diameter":
            return (x.defpoint4 - x.defpoint).magnitude
        if kind == "radius":
            return (x.defpoint4 - x.defpoint).magnitude
        if kind == "angular":
            # 2-line angular: first line 13->14, second line 15->10
            v1 = x.defpoint3 - x.defpoint2
            v2 = x.defpoint - x.defpoint4
            return math.degrees(abs(math.atan2(v1.x * v2.y - v1.y * v2.x, v1.x * v2.x + v1.y * v2.y)))
        if kind == "angular3p":
            # 13 / 14 = points on the two legs, 15 = vertex; measured CCW from 13 to 14
            c = x.defpoint4
            a1 = math.degrees(math.atan2(x.defpoint2.y - c.y, x.defpoint2.x - c.x))
            a2 = math.degrees(math.atan2(x.defpoint3.y - c.y, x.defpoint3.x - c.x))
            span = (a2 - a1) % 360.0
            return 360.0 if span < 1e-12 else span
    except Exception:
        return None
    return None


# --- selection ---------------------------------------------------------------

def _match(e: DXFGraphic, flt: dict[str, Any]) -> bool:
    if "type" in flt:
        types = flt["type"] if isinstance(flt["type"], list) else [flt["type"]]
        if e.dxftype() not in {s.upper() for s in types}:
            return False
    if "layer" in flt:
        layers = flt["layer"] if isinstance(flt["layer"], list) else [flt["layer"]]
        if e.dxf.layer not in layers:
            return False
    if "tag" in flt and get_tag(e) != flt["tag"]:
        return False
    if "tag_prefix" in flt:
        t = get_tag(e)
        if t is None or not t.startswith(flt["tag_prefix"]):
            return False
    return True


def select(doc: Drawing, sel: Any, refs: dict[int, list[str]] | None = None, *,
           field: str = "target", allow_empty: bool = False) -> list[DXFGraphic]:
    """Resolve a selector to modelspace entities.

    Accepted forms: ``"1F"`` (handle), ``"tag:hole.1"``, ``"$2"`` (entities
    created by op #2 of the current batch), a list of those, or a filter dict
    ``{"type": "CIRCLE", "layer": "HOLES", "tag_prefix": "hole."}``.
    """
    msp = doc.modelspace()
    out: list[DXFGraphic] = []
    if isinstance(sel, list):
        for s in sel:
            out.extend(select(doc, s, refs, field=field))
    elif isinstance(sel, dict):
        if not sel:
            raise input_error("EMPTY_SELECTOR", f"{field}: empty filter would select everything",
                              hint='Use {"all": true} to explicitly select all entities')
        if sel.get("all") is True:
            out = list(msp)
        else:
            out = [e for e in msp if _match(e, sel)]
    elif isinstance(sel, str):
        s = sel.strip()
        if s.startswith("$"):
            try:
                i = int(s[1:])
            except ValueError:
                raise input_error("BAD_REFERENCE", f"{field}: bad batch reference {sel!r}")
            if refs is None or i not in refs:
                raise input_error("BAD_REFERENCE", f"{field}: {sel!r} refers to an op that has not produced entities",
                                  hint="Batch references must point to an earlier op in the same batch")
            out = [doc.entitydb[h] for h in refs[i] if h in doc.entitydb]
        elif s.startswith("tag:"):
            out = [e for e in msp if get_tag(e) == s[4:]]
        else:
            e = doc.entitydb.get(s.upper())
            if e is None or not e.is_alive or e.dxf.owner != msp.layout_key:
                raise input_error("ENTITY_NOT_FOUND", f"{field}: no modelspace entity with handle {sel!r}",
                                  entities=[s], hint="Use inspect_entities to list valid ids")
            out = [e]
    else:
        raise input_error("BAD_SELECTOR", f"{field}: unsupported selector {sel!r}")
    if not out and not allow_empty:
        raise input_error("ENTITY_NOT_FOUND", f"{field}: selector {sel!r} matched no entities",
                          hint="Use inspect_entities to list valid ids/tags")
    # de-duplicate, keep order
    seen: set[str] = set()
    uniq = []
    for e in out:
        if e.dxf.handle not in seen:
            seen.add(e.dxf.handle)
            uniq.append(e)
    return uniq


def handles(entities: Iterable[DXFGraphic]) -> list[str]:
    return [e.dxf.handle for e in entities]
