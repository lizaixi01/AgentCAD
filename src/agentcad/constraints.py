"""Geometric constraints.

Two clearly separated capabilities:

* ``check_constraints`` — evaluates every supported constraint type against
  actual geometry and reports expected / actual / error / tolerance.
* ``enforce_constraints`` — *sequential direct enforcement* for a subset of
  types: each constraint is satisfied in turn by moving the second operand
  (``b``) or editing the single operand. This is NOT a simultaneous constraint
  solver; enforcing a later constraint can break an earlier one, so every
  constraint is re-checked afterwards and violations are reported.

Point references: ``"<selector>@<point>"`` where point is start | end | mid |
center | insert | location | v<N> (polyline vertex N), e.g. ``"tag:l1@end"``.
"""
from __future__ import annotations

import math
from typing import Any

from ezdxf.document import Drawing

from . import geom as G
from .errors import input_error
from .model import circle_wcs, lwpoly_wcs, select

CHECK_TYPES = {"coincident", "parallel", "perpendicular", "horizontal", "vertical", "tangent", "concentric",
               "distance", "length", "angle", "symmetric", "equal", "radius", "diameter", "fixed"}
ENFORCE_TYPES = {"coincident", "horizontal", "vertical", "concentric", "length", "distance", "radius",
                 "diameter", "fixed", "parallel", "perpendicular", "equal"}


def _one(doc, sel, refs=None, field="a"):
    ents = select(doc, sel, refs, field=field)
    if len(ents) != 1:
        raise input_error("TARGET_NOT_UNIQUE", f"{field}: constraint operand must be exactly one entity",
                          entities=[e.dxf.handle for e in ents])
    return ents[0]


def _pref(doc, ref: str, refs=None):
    if not isinstance(ref, str) or "@" not in ref:
        raise input_error("BAD_POINT_REF", f"Point reference {ref!r} must look like '<selector>@<point>'")
    sel, name = ref.rsplit("@", 1)
    return _one(doc, sel, refs, field=ref), name


def get_point(e, name: str) -> G.Vec:
    t = e.dxftype()
    x = e.dxf
    if name in ("start", "end") and t == "LINE":
        p = x.get(name)
        return (p.x, p.y)
    if name == "mid" and t == "LINE":
        return ((x.start.x + x.end.x) / 2, (x.start.y + x.end.y) / 2)
    if name in ("start", "end") and t == "ARC":
        c, rad, s, en = circle_wcs(e)
        return G.polar(c, rad, s if name == "start" else en)
    if name == "center" and t in ("CIRCLE", "ARC"):
        return circle_wcs(e)[0]
    if name == "center" and t == "ELLIPSE":
        return (x.center.x, x.center.y)
    if name in ("insert", "location") and x.hasattr(name):
        p = x.get(name)
        return (p.x, p.y)
    if name.startswith("v") and t == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in lwpoly_wcs(e)]
        i = int(name[1:])
        if not -len(pts) <= i < len(pts):
            raise input_error("BAD_POINT_REF", f"Vertex {i} out of range ({len(pts)} vertices)", entities=[x.handle])
        return tuple(pts[i])  # type: ignore[return-value]
    raise input_error("BAD_POINT_REF", f"{t} has no point {name!r}", entities=[x.handle])


def set_point(e, name: str, p: G.Vec) -> None:
    t = e.dxftype()
    if t == "LINE" and name in ("start", "end"):
        e.dxf.set(name, (p[0], p[1], 0))
    elif name in ("center", "insert", "location"):
        cur = get_point(e, name)
        e.translate(p[0] - cur[0], p[1] - cur[1], 0)
    elif t == "LWPOLYLINE" and name.startswith("v"):
        pts = list(e.get_points("xyseb"))
        i = int(name[1:])
        x, y, s, en, b = pts[i]
        pts[i] = (p[0], p[1], s, en, b)
        closed = e.closed
        e.set_points(pts, format="xyseb")
        e.closed = closed
    else:
        raise input_error("UNSUPPORTED_ENFORCEMENT", f"Cannot move point {name!r} of {t}", entities=[e.dxf.handle])


def _dir(e) -> G.Vec:
    if e.dxftype() != "LINE":
        raise input_error("UNSUPPORTED_ENTITY", f"Expected a LINE, got {e.dxftype()}", entities=[e.dxf.handle])
    return (e.dxf.end.x - e.dxf.start.x, e.dxf.end.y - e.dxf.start.y)


def _angle_between(u: G.Vec, v: G.Vec) -> float:
    """Unsigned angle between line directions in [0, 90]... as lines (not rays): [0, 180)."""
    a = math.degrees(math.atan2(G.cross(u, v), G.dot(u, v))) % 180.0
    return a


def _measure(doc: Drawing, c: dict[str, Any], refs=None) -> tuple[Any, Any, float, list[str]]:
    """Returns (expected, actual, error, entities)."""
    t = c.get("type")
    if t not in CHECK_TYPES:
        raise input_error("UNKNOWN_CONSTRAINT", f"Unknown constraint type {t!r}", hint=f"Types: {sorted(CHECK_TYPES)}")
    if t in ("coincident", "distance"):
        ea, na = _pref(doc, c["a"], refs)
        eb, nb = _pref(doc, c["b"], refs)
        d = G.dist(get_point(ea, na), get_point(eb, nb))
        exp = 0.0 if t == "coincident" else float(c["value"])
        return exp, d, abs(d - exp), [ea.dxf.handle, eb.dxf.handle]
    if t == "fixed":
        ea, na = _pref(doc, c["a"], refs)
        p = get_point(ea, na)
        return list(c["value"]), [p[0], p[1]], G.dist(p, tuple(c["value"])), [ea.dxf.handle]
    if t in ("parallel", "perpendicular", "angle"):
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        a = _angle_between(_dir(ea), _dir(eb))
        if t == "parallel":
            return 0.0, a, min(a, 180 - a), [ea.dxf.handle, eb.dxf.handle]
        if t == "perpendicular":
            return 90.0, a, abs(a - 90), [ea.dxf.handle, eb.dxf.handle]
        exp = float(c["value"]) % 180
        return exp, a, min(abs(a - exp), 180 - abs(a - exp)), [ea.dxf.handle, eb.dxf.handle]
    if t in ("horizontal", "vertical"):
        ea = _one(doc, c["a"], refs)
        a = G.angle_of(_dir(ea)) % 180
        exp = 0.0 if t == "horizontal" else 90.0
        return exp, a, min(abs(a - exp), 180 - abs(a - exp)), [ea.dxf.handle]
    if t == "length":
        ea = _one(doc, c["a"], refs)
        L = G.norm(_dir(ea))
        return float(c["value"]), L, abs(L - float(c["value"])), [ea.dxf.handle]
    if t in ("radius", "diameter"):
        ea = _one(doc, c["a"], refs)
        if ea.dxftype() not in ("CIRCLE", "ARC"):
            raise input_error("UNSUPPORTED_ENTITY", "radius/diameter need a CIRCLE or ARC", entities=[ea.dxf.handle])
        v = ea.dxf.radius * (2 if t == "diameter" else 1)
        return float(c["value"]), v, abs(v - float(c["value"])), [ea.dxf.handle]
    if t == "concentric":
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        d = G.dist(get_point(ea, "center"), get_point(eb, "center"))
        return 0.0, d, d, [ea.dxf.handle, eb.dxf.handle]
    if t == "equal":
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        va, vb = _size(ea), _size(eb)
        return va, vb, abs(va - vb), [ea.dxf.handle, eb.dxf.handle]
    if t == "tangent":
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        return 0.0, *_tangent_error(ea, eb), [ea.dxf.handle, eb.dxf.handle]
    if t == "symmetric":
        ea, na = _pref(doc, c["a"], refs)
        eb, nb = _pref(doc, c["b"], refs)
        ax = _one(doc, c["axis"], refs, "axis")
        pa, pb = get_point(ea, na), get_point(eb, nb)
        s = (ax.dxf.start.x, ax.dxf.start.y)
        u = G.unit(_dir(ax))
        # reflect pa across the axis and compare to pb
        v = G.sub(pa, s)
        proj = G.mul(u, G.dot(v, u))
        refl = G.add(s, G.sub(G.mul(proj, 2), v))
        d = G.dist(refl, pb)
        return 0.0, d, d, [ea.dxf.handle, eb.dxf.handle, ax.dxf.handle]
    raise AssertionError(t)


def _size(e) -> float:
    if e.dxftype() == "LINE":
        return G.norm(_dir(e))
    if e.dxftype() in ("CIRCLE", "ARC"):
        return e.dxf.radius
    raise input_error("UNSUPPORTED_ENTITY", "equal needs LINEs or CIRCLE/ARCs", entities=[e.dxf.handle])


def _tangent_error(a, b) -> tuple[float, float]:
    if a.dxftype() not in ("CIRCLE", "ARC"):
        a, b = b, a
    if a.dxftype() not in ("CIRCLE", "ARC"):
        raise input_error("UNSUPPORTED_ENTITY", "tangent needs at least one CIRCLE/ARC")
    c, r, _, _ = circle_wcs(a)
    if b.dxftype() == "LINE":
        s = (b.dxf.start.x, b.dxf.start.y)
        u = G.unit(_dir(b))
        d = abs(G.cross(u, G.sub(c, s)))
        return d, abs(d - r)
    if b.dxftype() in ("CIRCLE", "ARC"):
        c2, r2, _, _ = circle_wcs(b)
        d = G.dist(c, c2)
        return d, min(abs(d - (r + r2)), abs(d - abs(r - r2)))
    raise input_error("UNSUPPORTED_ENTITY", f"tangent does not support {b.dxftype()}")


def check_constraints(doc: Drawing, constraints: list[dict[str, Any]], *, tolerance: float = 1e-6,
                      refs=None) -> list[dict[str, Any]]:
    out = []
    for i, c in enumerate(constraints):
        cid = c.get("id", f"C{i + 1}")
        tol = float(c.get("tolerance", tolerance))
        try:
            exp, act, err, ents = _measure(doc, c, refs)
            out.append({"id": cid, "type": c.get("type"), "satisfied": err <= tol, "expected": _rnd(exp),
                        "actual": _rnd(act), "error": _rnd(err), "tolerance": tol, "entities": ents})
        except KeyError as exc:
            out.append({"id": cid, "type": c.get("type"), "satisfied": False, "status": "error",
                        "error_detail": {"code": "MISSING_PARAM", "message": f"constraint missing field {exc}"}})
        except Exception as exc:
            from .errors import AgentCADError
            if not isinstance(exc, AgentCADError):
                raise
            out.append({"id": cid, "type": c.get("type"), "satisfied": False, "status": "error",
                        "error_detail": exc.to_dict()})
    return out


def _rnd(v):
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, (list, tuple)):
        return [_rnd(x) for x in v]
    return v


def enforce_one(doc: Drawing, c: dict[str, Any], refs=None) -> list[str]:
    """Directly satisfy one constraint by editing operand b (or the single operand). Returns touched handles."""
    t = c.get("type")
    if t not in ENFORCE_TYPES:
        raise input_error("UNSUPPORTED_ENFORCEMENT", f"Constraint {t!r} can be checked but not enforced",
                          hint=f"Enforceable: {sorted(ENFORCE_TYPES)}")
    if t in ("coincident", "fixed"):
        if t == "fixed":
            ea, na = _pref(doc, c["a"], refs)
            set_point(ea, na, tuple(c["value"]))
            return [ea.dxf.handle]
        ea, na = _pref(doc, c["a"], refs)
        eb, nb = _pref(doc, c["b"], refs)
        set_point(eb, nb, get_point(ea, na))
        return [eb.dxf.handle]
    if t == "distance":
        ea, na = _pref(doc, c["a"], refs)
        eb, nb = _pref(doc, c["b"], refs)
        pa, pb = get_point(ea, na), get_point(eb, nb)
        u = G.unit(G.sub(pb, pa))
        set_point(eb, nb, G.add(pa, G.mul(u, float(c["value"]))))
        return [eb.dxf.handle]
    if t in ("horizontal", "vertical", "length"):
        e = _one(doc, c["a"], refs)
        s = (e.dxf.start.x, e.dxf.start.y)
        L = G.norm(_dir(e))
        if t == "length":
            set_point(e, "end", G.add(s, G.mul(G.unit(_dir(e)), float(c["value"]))))
        else:
            d = _dir(e)
            sign = (1 if d[0] >= 0 else -1) if t == "horizontal" else (1 if d[1] >= 0 else -1)
            set_point(e, "end", (s[0] + sign * L, s[1]) if t == "horizontal" else (s[0], s[1] + sign * L))
        return [e.dxf.handle]
    if t in ("radius", "diameter"):
        e = _one(doc, c["a"], refs)
        v = float(c["value"])
        if v <= 0:
            raise input_error("OUT_OF_RANGE", "radius/diameter must be > 0")
        e.dxf.radius = v / 2 if t == "diameter" else v
        return [e.dxf.handle]
    if t == "concentric":
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        set_point(eb, "center", get_point(ea, "center"))
        return [eb.dxf.handle]
    if t == "equal":
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        va = _size(ea)
        if eb.dxftype() == "LINE":
            s = (eb.dxf.start.x, eb.dxf.start.y)
            set_point(eb, "end", G.add(s, G.mul(G.unit(_dir(eb)), va)))
        else:
            eb.dxf.radius = va
        return [eb.dxf.handle]
    if t in ("parallel", "perpendicular"):
        ea, eb = _one(doc, c["a"], refs), _one(doc, c["b"], refs, "b")
        ua = G.unit(_dir(ea))
        if t == "perpendicular":
            ua = (-ua[1], ua[0])
        ub = _dir(eb)
        if G.dot(ua, ub) < 0:
            ua = (-ua[0], -ua[1])
        s = (eb.dxf.start.x, eb.dxf.start.y)
        set_point(eb, "end", G.add(s, G.mul(ua, G.norm(ub))))
        return [eb.dxf.handle]
    raise AssertionError(t)
