"""FreeCAD side of the 3D part backend. Runs inside FreeCAD's own Python (``python.exe -I _fc_runner.py <job>``),
never imported by agentcad: it may only import FreeCAD modules and the standard library.

The job folder holds ``job.json`` ({"action", "input", "output", "ops", ...}); the result goes to ``result.json``
as {"ok": true, ...} or {"ok": false, "error": {code, category, message, op_index, op, hint, details}}.

Model contract (what CADBench's grader accepts as an editable part): one PartDesign::Body producing one solid, built
only from native PartDesign features. Every feature records the op that made it (``AgentCADOp``) so ``modify_feature``
can re-apply it, and references to faces or edges are stored as geometric selectors (``AgentCADRef``), re-resolved
after every edit. FreeCAD's own element names do not survive a sketch change (probed on 1.1.4: a parameter edit left
a fillet on "?Edge2"), so FreeCAD only ever holds links to origin planes, sketches and features.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
from pathlib import Path

for _lib in filter(None, os.environ.get("AGENTCAD_FREECAD_LIB", "").split(os.pathsep)):
    sys.path.insert(0, _lib)  # FREECAD_LIB installs: FreeCAD's module is imported by a plain interpreter

import FreeCAD as App  # noqa: N813, E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

V = App.Vector
TOL = 1e-6
ALLOWED_TYPES = {
    "Sketcher::SketchObject", "PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution",
    "PartDesign::Groove", "PartDesign::Hole", "PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Draft",
    "PartDesign::Thickness", "PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
    "PartDesign::Scaled", "PartDesign::MultiTransform", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
    "PartDesign::CoordinateSystem", "App::Origin", "App::Plane", "App::Line", "App::Point",
    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft", "PartDesign::AdditivePipe",
    "PartDesign::SubtractivePipe", "PartDesign::AdditiveHelix", "PartDesign::SubtractiveHelix",
} | {f"PartDesign::{k}{p}" for k in ("Additive", "Subtractive")
     for p in ("Box", "Cylinder", "Cone", "Sphere", "Ellipsoid", "Torus", "Prism", "Wedge")}
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
_LEN = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([a-zA-Z]*)\s*$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OpError(Exception):
    def __init__(self, code, message, category="input", hint=None, details=None, entities=None):
        super().__init__(message)
        self.code, self.message, self.category = code, message, category
        self.hint, self.details, self.entities = hint, details or {}, entities or []
        self.op_index = None
        self.op = None

    def to_dict(self):
        d = {"code": self.code, "category": self.category, "message": self.message, "entities": self.entities}
        for k in ("op_index", "op", "hint"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.details:
            d["details"] = self.details
        return d


# --- values ----------------------------------------------------------------------------------------------------

class Dim:
    """A length or number: a value in mm, plus the expression that drives it (``"=Params.w * 2"``), if any."""

    def __init__(self, value, expr=None):
        self.value, self.expr = value, expr


def dim(v, name, unit_mm=1.0, *, length=True, positive=False, allow_zero=True):
    if isinstance(v, Dim):
        return v
    if isinstance(v, bool) or v is None:
        raise OpError("INVALID_NUMBER", f"{name}: expected a number, got {v!r}")
    if isinstance(v, (int, float)):
        val = float(v) * (unit_mm if length else 1.0)
        expr = None
    elif isinstance(v, str) and v.strip().startswith("="):
        expr = v.strip()[1:].strip()
        if not expr:
            raise OpError("INVALID_EXPRESSION", f"{name}: empty expression")
        val = None
    elif isinstance(v, str):
        m = _LEN.match(v)
        if not m:
            raise OpError("INVALID_LENGTH", f"{name}: cannot parse {v!r}",
                          hint="A number, a string with a unit ('8mm', '0.5in'), or an expression '=Params.w'")
        u = m.group(2).lower()
        if u and u not in UNIT_MM:
            raise OpError("UNKNOWN_UNIT", f"{name}: unknown unit {u!r}", hint=f"Use one of {sorted(UNIT_MM)}")
        val = float(m.group(1)) * (UNIT_MM[u] if u else (unit_mm if length else 1.0))
        expr = None
    else:
        raise OpError("INVALID_NUMBER", f"{name}: expected a number, unit string or '=expression', got {v!r}")
    if val is not None:
        if not math.isfinite(val):
            raise OpError("INVALID_NUMBER", f"{name}: must be finite")
        if positive and (val < 0 or (val == 0 and not allow_zero)):
            raise OpError("OUT_OF_RANGE", f"{name}: must be > 0, got {val:g}")
    return Dim(val, expr)


def num(v, name, unit_mm=1.0, **kw):
    """A plain value (no expression) in mm."""
    d = dim(v, name, unit_mm, **kw)
    if d.expr is not None:
        raise OpError("EXPRESSION_NOT_SUPPORTED", f"{name}: expressions are not supported here",
                      hint="Give a number; expressions drive circle diameters, rectangle sizes and feature "
                           "lengths, depths, radii, angles and counts")
    return d.value


def vec(v, name, unit_mm=1.0, n=3):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise OpError("INVALID_POINT", f"{name}: expected {n} numbers, got {v!r}")
    return [num(c, f"{name}[{i}]", unit_mm) for i, c in enumerate(v)]


def set_dim(obj, prop, d: Dim, scale=1.0):
    """Set a property from a Dim: the expression (if any) drives it, otherwise the value is set and any old
    expression is cleared."""
    if d.expr is not None:
        obj.setExpression(prop, d.expr)
    else:
        if obj.getExpression(prop) if hasattr(obj, "getExpression") else None:
            obj.setExpression(prop, None)
        _clear_expr(obj, prop)
        setattr(obj, prop, d.value * scale)


def _clear_expr(obj, prop):
    for path, _ in list(getattr(obj, "ExpressionEngine", []) or []):
        if path.lstrip(".") == prop:
            obj.setExpression(path, None)


def r6(x):
    return round(float(x), 6) + 0.0


def v3(p):
    return [r6(p.x), r6(p.y), r6(p.z)]


# --- document context ------------------------------------------------------------------------------------------

class Ctx:
    def __init__(self, doc):
        self.doc = doc
        self.refs = {}          # batch index -> object name
        self.op_of = {}         # object name -> batch index (created or modified there)
        self.created, self.modified, self.deleted = [], [], []
        meta = doc.Meta if hasattr(doc, "Meta") else {}
        self.unit = meta.get("agentcad_units", "mm") or "mm"
        self.unit_mm = UNIT_MM.get(self.unit, 1.0)

    # references
    def obj(self, ref, what="feature"):
        if isinstance(ref, App.DocumentObject):
            return ref
        if not isinstance(ref, str) or not ref:
            raise OpError("BAD_REFERENCE", f"{what}: expected a feature reference, got {ref!r}",
                          hint="'tag:<name>', '$<op index>' or an object name such as 'Pad001'")
        if ref.startswith("$"):
            try:
                name = self.refs[int(ref[1:])]
            except (ValueError, KeyError):
                raise OpError("BAD_REFERENCE", f"{what}: {ref} does not name an earlier op of this batch "
                                               "that created a feature")
            return self.doc.getObject(name)
        if ref.startswith("tag:"):
            tag = ref[4:]
            hits = [o for o in self.doc.Objects if getattr(o, "AgentCADTag", None) == tag]
            if not hits:
                raise OpError("TAG_NOT_FOUND", f"{what}: no feature tagged {tag!r}",
                              hint=f"Tags: {sorted(t for t in (getattr(o, 'AgentCADTag', '') for o in self.doc.Objects) if t)}")
            return hits[0]
        o = self.doc.getObject(ref) or next(iter(self.doc.getObjectsByLabel(ref)), None)
        if o is None:
            raise OpError("FEATURE_NOT_FOUND", f"{what}: no object {ref!r}",
                          hint=f"Features: {[x.Name for x in features(self.doc)]}")
        return o

    def body(self, ref=None, create=True):
        if ref:
            b = self.obj(ref, "body")
            if b.TypeId != "PartDesign::Body":
                raise OpError("NOT_A_BODY", f"{b.Name} is a {b.TypeId}, not a PartDesign::Body")
            return b
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        if len(bodies) == 1:
            return bodies[0]
        if not bodies:
            if not create:
                raise OpError("NO_BODY", "The part has no body yet", hint="Add a sketch and a pad first")
            b = self.doc.addObject("PartDesign::Body", "Body")
            self.created.append(b.Name)
            return b
        raise OpError("AMBIGUOUS_BODY", f"The part has {len(bodies)} bodies; name one with 'body'",
                      hint=f"Bodies: {[b.Name for b in bodies]}")

    def origin(self, body):
        return {o.Role: o for o in body.Origin.OriginFeatures}

    def sketch(self, ref, what="sketch"):
        s = self.obj(ref, what)
        if s.TypeId != "Sketcher::SketchObject":
            raise OpError("NOT_A_SKETCH", f"{what}: {s.Name} is a {s.TypeId}, not a sketch")
        return s


def features(doc):
    out = []
    for b in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
        out += list(b.Group)
    return out


def tag(obj, t):
    if not hasattr(obj, "AgentCADTag"):
        obj.addProperty("App::PropertyString", "AgentCADTag", "AgentCAD", "Semantic tag")
    obj.AgentCADTag = t or ""
    if t:
        obj.Label = t


def store_json(obj, prop, data):
    if not hasattr(obj, prop):
        obj.addProperty("App::PropertyString", prop, "AgentCAD", "Recorded by AgentCAD")
    setattr(obj, prop, json.dumps(data, sort_keys=True))


def load_json(obj, prop):
    v = getattr(obj, prop, "")
    return json.loads(v) if v else None


# --- placement -------------------------------------------------------------------------------------------------

PLANES = {"XY": ("XY_Plane", V(0, 0, 1)), "XZ": ("XZ_Plane", V(0, -1, 0)), "YZ": ("YZ_Plane", V(1, 0, 0))}


def rotation_from(normal, xdir=None):
    n = V(*normal) if not isinstance(normal, App.Vector) else V(normal)
    if n.Length < TOL:
        raise OpError("INVALID_VECTOR", "normal must not be zero")
    n.normalize()
    if xdir is None:
        x = V(1, 0, 0) - n * n.x  # global X projected into the plane
        if x.Length < 1e-3:
            x = V(0, 1, 0) - n * n.y
    else:
        x = V(*xdir) if not isinstance(xdir, App.Vector) else V(xdir)
        x = x - n * x.dot(n)
        if x.Length < TOL:
            raise OpError("INVALID_VECTOR", "x_dir is parallel to the normal")
    x.normalize()
    y = n.cross(x)
    return App.Rotation(x, y, n, "ZXY")


# --- selectors -------------------------------------------------------------------------------------------------

AXES = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}


def _dir(v, name):
    if isinstance(v, str):
        s = v.strip().lower()
        sign = -1.0 if s.startswith("-") else 1.0
        key = s.lstrip("+-")
        if key not in AXES:
            raise OpError("BAD_SELECTOR", f"{name}: direction {v!r} is not x, y, z (optionally signed) or [x, y, z]")
        return AXES[key] * sign
    if isinstance(v, (list, tuple)) and len(v) == 3:
        d = V(*[float(c) for c in v])
        if d.Length < TOL:
            raise OpError("BAD_SELECTOR", f"{name}: zero vector")
        d.normalize()
        return d
    raise OpError("BAD_SELECTOR", f"{name}: expected 'x'|'y'|'z' (signed) or [x, y, z], got {v!r}")


def _curve_kind(e):
    if e.Degenerated:  # e.g. a sphere's or cone's pole: no curve, and e.Curve raises "undefined curve type"
        return "degenerate"
    c = e.Curve
    n = type(c).__name__
    return {"Line": "line", "LineSegment": "line", "Circle": "circle", "ArcOfCircle": "circle",
            "Ellipse": "ellipse", "BSplineCurve": "bspline", "BezierCurve": "bezier"}.get(n, n.lower())


def _surface_kind(f):
    n = type(f.Surface).__name__
    return {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere", "Toroid": "torus",
            "BSplineSurface": "bspline", "SurfaceOfRevolution": "revolution",
            "SurfaceOfExtrusion": "extrusion"}.get(n, n.lower())


def _is_seam(shape, e):
    fs = shape.ancestorsOfType(e, Part.Face)
    return len(fs) == 2 and fs[0].isSame(fs[1]) or len(fs) < 2 and _curve_kind(e) == "line" and \
        any(_surface_kind(f) in ("cylinder", "cone") for f in fs)


def _face_normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def describe_edge(shape, i, e):
    d = {"name": f"Edge{i + 1}", "type": _curve_kind(e), "length": r6(e.Length)}
    if d["type"] == "line":
        d["start"], d["end"] = v3(e.Vertexes[0].Point), v3(e.Vertexes[-1].Point)
    elif d["type"] == "circle":
        d["center"], d["radius"], d["axis"] = v3(e.Curve.Center), r6(e.Curve.Radius), v3(e.Curve.Axis)
        d["closed"] = e.isClosed()
    else:
        bb = e.BoundBox
        d["bbox"] = [[r6(bb.XMin), r6(bb.YMin), r6(bb.ZMin)], [r6(bb.XMax), r6(bb.YMax), r6(bb.ZMax)]]
    return d


def describe_face(shape, i, f):
    d = {"name": f"Face{i + 1}", "type": _surface_kind(f), "area": r6(f.Area), "center": v3(f.CenterOfMass)}
    k = d["type"]
    if k == "plane":
        d["normal"] = v3(_face_normal(f))
    elif k in ("cylinder", "cone"):
        s = f.Surface
        d["axis"], d["radius"] = v3(s.Axis), r6(getattr(s, "Radius", 0.0))
        d["inner"] = _is_inner_cyl(f)
    elif k == "sphere":
        d["radius"] = r6(f.Surface.Radius)
    bb = f.BoundBox
    d["bbox"] = [[r6(bb.XMin), r6(bb.YMin), r6(bb.ZMin)], [r6(bb.XMax), r6(bb.YMax), r6(bb.ZMax)]]
    return d


def _is_inner_cyl(f):
    """A cylindrical face whose material is outside it (a hole or bore), judged by the face normal."""
    s = f.Surface
    u0, u1, v0, v1 = f.ParameterRange
    u, v = (u0 + u1) / 2, (v0 + v1) / 2
    p = f.valueAt(u, v)
    n = f.normalAt(u, v)
    ax = s.Axis
    c = s.Center
    w = p - c
    radial = w - ax * w.dot(ax)
    return radial.dot(n) < 0


def _num_match(actual, want, name, tol):
    if want is None:
        return True
    return abs(actual - float(want)) <= tol


def _coord_filter(sel, pts, tol):
    for k, idx in (("x", 0), ("y", 1), ("z", 2)):
        if k in sel and sel[k] is not None:
            if not all(abs(p[idx] - float(sel[k])) <= tol for p in pts):
                return False
    if "box" in sel and sel["box"] is not None:
        (x0, y0, z0), (x1, y1, z1) = sel["box"]
        lo, hi = (min(x0, x1), min(y0, y1), min(z0, z1)), (max(x0, x1), max(y0, y1), max(z0, z1))
        if not all(lo[i] - tol <= p[i] <= hi[i] + tol for p in pts for i in range(3)):
            return False
    return True


SELECTOR_KEYS_EDGE = {"all", "type", "direction", "axis", "radius", "diameter", "x", "y", "z", "box", "near",
                      "count", "face", "length", "tol"}
SELECTOR_KEYS_FACE = {"all", "type", "normal", "extreme", "axis", "radius", "diameter", "x", "y", "z", "box",
                      "near", "count", "inner", "tol"}


def select_edges(shape, sel, name="edges"):
    """Resolve an edge selector (or a list of them, united) to sorted 'EdgeN' names."""
    if isinstance(sel, list):
        out = []
        for i, s in enumerate(sel):
            out += [n for n in select_edges(shape, s, f"{name}[{i}]") if n not in out]
        return sorted(out, key=lambda n: int(n[4:]))
    if isinstance(sel, str):
        if re.fullmatch(r"Edge\d+", sel):
            if int(sel[4:]) > len(shape.Edges):
                raise OpError("SELECTOR_EMPTY", f"{name}: {sel} does not exist ({len(shape.Edges)} edges)")
            return [sel]
        if sel == "all":
            sel = {"all": True}
        else:
            raise OpError("BAD_SELECTOR", f"{name}: {sel!r} is not an edge selector")
    if not isinstance(sel, dict) or not sel:
        raise OpError("BAD_SELECTOR", f"{name}: expected a selector object such as "
                                      "{\"type\": \"line\", \"direction\": \"z\"}")
    unknown = set(sel) - SELECTOR_KEYS_EDGE
    if unknown:
        raise OpError("BAD_SELECTOR", f"{name}: unknown selector keys {sorted(unknown)}",
                      hint=f"Edge selector keys: {sorted(SELECTOR_KEYS_EDGE)}")
    tol = float(sel.get("tol", 1e-4))
    face_edges = None
    if sel.get("face") is not None:
        face_edges = []
        for fn in select_faces(shape, sel["face"], name + ".face"):
            for e in shape.getElement(fn).Edges:
                face_edges.append(e)
    hits = []
    for i, e in enumerate(shape.Edges):
        if e.Degenerated or _is_seam(shape, e):
            continue
        if face_edges is not None and not any(e.isSame(x) for x in face_edges):
            continue
        k = _curve_kind(e)
        if sel.get("type") and sel["type"] != "any" and k != sel["type"]:
            continue
        if sel.get("direction") is not None:
            if k != "line":
                continue
            t = e.Vertexes[-1].Point - e.Vertexes[0].Point
            if t.Length < TOL or abs(abs(t.normalize().dot(_dir(sel["direction"], name + ".direction"))) - 1) > 1e-6:
                continue
        if sel.get("axis") is not None:
            if k != "circle" or abs(abs(e.Curve.Axis.dot(_dir(sel["axis"], name + ".axis"))) - 1) > 1e-6:
                continue
        r = sel.get("radius")
        if r is None and sel.get("diameter") is not None:
            r = float(sel["diameter"]) / 2
        if r is not None and (k != "circle" or abs(e.Curve.Radius - float(r)) > tol):
            continue
        if sel.get("length") is not None and abs(e.Length - float(sel["length"])) > tol:
            continue
        pts = [(p.x, p.y, p.z) for p in (e.discretize(5) if k != "line" else [v.Point for v in e.Vertexes])]
        if not _coord_filter(sel, pts, tol):
            continue
        hits.append((i, e))
    hits = _near(hits, sel, name, lambda e: e)
    if not hits:
        raise OpError("SELECTOR_EMPTY", f"{name}: no edge matches {json.dumps(sel)}", category="geometry",
                      hint="List candidate edges with inspect_entities(filter={\"kind\": \"edges\"}) on the part")
    return [f"Edge{i + 1}" for i, _ in hits]


def _near(hits, sel, name, geo):
    if sel.get("near") is None:
        if sel.get("count") is not None:
            raise OpError("BAD_SELECTOR", f"{name}: 'count' needs 'near'")
        return hits
    p = V(*[float(c) for c in sel["near"]])
    hits = sorted(hits, key=lambda h: geo(h[1]).distToShape(Part.Vertex(p))[0])
    return hits[:int(sel.get("count", 1))]


def select_faces(shape, sel, name="faces"):
    if isinstance(sel, list):
        out = []
        for i, s in enumerate(sel):
            out += [n for n in select_faces(shape, s, f"{name}[{i}]") if n not in out]
        return sorted(out, key=lambda n: int(n[4:]))
    if isinstance(sel, str):
        if re.fullmatch(r"Face\d+", sel):
            if int(sel[4:]) > len(shape.Faces):
                raise OpError("SELECTOR_EMPTY", f"{name}: {sel} does not exist ({len(shape.Faces)} faces)")
            return [sel]
        named = {"top": {"normal": "+z", "extreme": "max"}, "bottom": {"normal": "-z", "extreme": "max"},
                 "front": {"normal": "-y", "extreme": "max"}, "back": {"normal": "+y", "extreme": "max"},
                 "left": {"normal": "-x", "extreme": "max"}, "right": {"normal": "+x", "extreme": "max"}}
        if sel not in named:
            raise OpError("BAD_SELECTOR", f"{name}: {sel!r} is not a face selector",
                          hint="'top', 'bottom', 'front', 'back', 'left', 'right', 'FaceN' or a selector object")
        sel = named[sel]
    if not isinstance(sel, dict) or not sel:
        raise OpError("BAD_SELECTOR", f"{name}: expected a selector object such as {{\"normal\": \"+z\", "
                                      "\"extreme\": \"max\"}}")
    unknown = set(sel) - SELECTOR_KEYS_FACE
    if unknown:
        raise OpError("BAD_SELECTOR", f"{name}: unknown selector keys {sorted(unknown)}",
                      hint=f"Face selector keys: {sorted(SELECTOR_KEYS_FACE)}")
    tol = float(sel.get("tol", 1e-4))
    hits = []
    for i, f in enumerate(shape.Faces):
        k = _surface_kind(f)
        if sel.get("type") and sel["type"] != "any" and k != sel["type"]:
            continue
        if sel.get("normal") is not None:
            if k != "plane" or _face_normal(f).dot(_dir(sel["normal"], name + ".normal")) < 1 - 1e-6:
                continue
        if sel.get("axis") is not None:
            if k not in ("cylinder", "cone") or abs(abs(f.Surface.Axis.dot(_dir(sel["axis"], name + ".axis"))) - 1) > 1e-6:
                continue
        r = sel.get("radius")
        if r is None and sel.get("diameter") is not None:
            r = float(sel["diameter"]) / 2
        if r is not None and (k not in ("cylinder", "sphere") or abs(f.Surface.Radius - float(r)) > tol):
            continue
        if sel.get("inner") is not None and (k != "cylinder" or _is_inner_cyl(f) != bool(sel["inner"])):
            continue
        bb = f.BoundBox
        pts = [(bb.XMin, bb.YMin, bb.ZMin), (bb.XMax, bb.YMax, bb.ZMax)]
        if not _coord_filter(sel, pts, tol):
            continue
        hits.append((i, f))
    if sel.get("extreme") is not None and hits:
        d = _dir(sel.get("normal") or sel.get("axis") or "z", name + ".normal")
        key = lambda h: h[1].CenterOfMass.dot(d)  # noqa: E731
        best = (max if sel["extreme"] == "max" else min)(key(h) for h in hits)
        hits = [h for h in hits if abs(key(h) - best) <= tol]
    hits = _near(hits, sel, name, lambda f: f)
    if not hits:
        raise OpError("SELECTOR_EMPTY", f"{name}: no face matches {json.dumps(sel)}", category="geometry",
                      hint="List candidate faces with inspect_entities(filter={\"kind\": \"faces\"}) on the part")
    return [f"Face{i + 1}" for i, _ in hits]


# --- sketches --------------------------------------------------------------------------------------------------

def _bulge_arc(p1, p2, b):
    """Arc from p1 to p2 with DXF bulge b (tan of a quarter of the included angle, + = counter-clockwise)."""
    chord = p2 - p1
    left = V(-chord.y, chord.x, 0)
    left.normalize()
    # The sagitta is b times half the chord, on the right of p1 -> p2 for a counter-clockwise arc (b > 0) and on
    # the left for a clockwise one; |b| > 1 (more than half a turn) is the same formula.
    pm = (p1 + p2) * 0.5 - left * (b * chord.Length / 2)
    # A three-point arc takes its axis from the points' turning sense, and a sketch keeps arcs counter-clockwise
    # about +Z: a clockwise one would come out as the other arc of its circle. So a clockwise bulge is built from
    # p2 back to p1 (the sketch joins arcs by their end points, not their direction).
    return Part.Arc(p1, pm, p2) if b > 0 else Part.Arc(p2, pm, p1)


class SketchBuilder:
    def __init__(self, sk, unit_mm, name):
        self.sk, self.unit_mm, self.name = sk, unit_mm, name
        self.geo = []           # (geo id, construction)
        self.named = {}         # constraint name -> index

    def p2(self, v, name):
        x, y = vec(v, name, self.unit_mm, 2)
        return V(x, y, 0)

    def add(self, g, construction):
        gid = self.sk.addGeometry(g, bool(construction))
        self.geo.append(gid)
        return gid

    def con(self, c, name=None, d=None):
        i = self.sk.addConstraint(c)
        if name:
            if name in self.named or name in [x.Name for x in self.sk.Constraints if x.Name and x is not c]:
                raise OpError("DUPLICATE_NAME", f"{self.name}: two dimensions named {name!r}")
            self.sk.renameConstraint(i, name)
            self.named[name] = i
        if d is not None and d.expr is not None:
            self.sk.setExpression(f".Constraints.{name}" if name else f"Constraints[{i}]", d.expr)
        return i

    def lock_point(self, gid, pos, p):
        if abs(p.x) < TOL and abs(p.y) < TOL:
            self.con(Sketcher.Constraint("Coincident", gid, pos, -1, 1))
            return
        if abs(p.x) < TOL:
            self.con(Sketcher.Constraint("PointOnObject", gid, pos, -2))
        else:
            self.con(Sketcher.Constraint("DistanceX", -1, 1, gid, pos, p.x))
        if abs(p.y) < TOL:
            self.con(Sketcher.Constraint("PointOnObject", gid, pos, -1))
        else:
            self.con(Sketcher.Constraint("DistanceY", -1, 1, gid, pos, p.y))

    def chain(self, gids, construction):
        """Coincident constraints between touching end points of the given geometry, then lock every distinct
        vertex once; arcs also get their radius, or a half circle its centre: fully constrained without redundancy."""
        ends = []
        for g in gids:
            geom = self.sk.Geometry[g]
            if not hasattr(geom, "StartPoint"):
                continue
            ends += [(g, 1, geom.StartPoint), (g, 2, geom.EndPoint)]
        groups = []
        for e in ends:
            for grp in groups:
                if (grp[0][2] - e[2]).Length < 1e-7:
                    grp.append(e)
                    break
            else:
                groups.append([e])
        for grp in groups:
            for a, b in zip(grp, grp[1:]):
                self.con(Sketcher.Constraint("Coincident", a[0], a[1], b[0], b[1]))
            g, pos, p = grp[0]
            self.lock_point(g, pos, p)
        for g in gids:
            geom = self.sk.Geometry[g]
            if type(geom).__name__ != "ArcOfCircle":
                continue
            chord = geom.EndPoint - geom.StartPoint
            if abs(chord.Length - 2 * geom.Radius) > 1e-7 * max(1.0, geom.Radius):
                self.con(Sketcher.Constraint("Radius", g, geom.Radius))
                continue
            # A half circle: its locked end points already fix the radius (chord = 2r), so a Radius constraint is
            # redundant and the solver rejects the sketch. What is still free is where the centre sits on the
            # chord's perpendicular bisector: lock the centre's coordinate along the axis closest to it.
            c = geom.Center
            if abs(chord.x) > abs(chord.y):  # bisector closer to Y
                self.con(Sketcher.Constraint("PointOnObject", g, 3, -1) if abs(c.y) < TOL else
                         Sketcher.Constraint("DistanceY", -1, 1, g, 3, c.y))
            else:
                self.con(Sketcher.Constraint("PointOnObject", g, 3, -2) if abs(c.x) < TOL else
                         Sketcher.Constraint("DistanceX", -1, 1, g, 3, c.x))

    def shape(self, s, i):
        nm = f"{self.name}.shapes[{i}]"
        if not isinstance(s, dict) or "type" not in s:
            raise OpError("BAD_SHAPE", f"{nm}: expected an object with 'type'",
                          hint="rectangle | circle | polygon | polyline | regular_polygon | slot | line | arc | point")
        t = s["type"]
        allowed = {"rectangle": {"corner", "center", "width", "height", "name"},
                   "circle": {"center", "diameter", "radius", "name"},
                   "polygon": {"points"}, "polyline": {"points", "closed"},
                   "regular_polygon": {"center", "sides", "circumradius", "across_flats", "rotation"},
                   "slot": {"start", "end", "width"}, "line": {"start", "end"},
                   "arc": {"center", "radius", "start_angle", "end_angle"}, "point": {"at"}}
        if t not in allowed:
            raise OpError("BAD_SHAPE", f"{nm}: unknown shape type {t!r}", hint=f"Types: {sorted(allowed)}")
        unknown = set(s) - allowed[t] - {"type", "construction"}
        if unknown:
            raise OpError("BAD_SHAPE", f"{nm}: unknown keys {sorted(unknown)} for {t}",
                          hint=f"{t} takes {sorted(allowed[t])} (+ construction)")
        cons = bool(s.get("construction", False))
        um = self.unit_mm

        def req(k):
            if s.get(k) is None:
                raise OpError("BAD_SHAPE", f"{nm}: {t} needs {k!r}")
            return s[k]

        if t == "rectangle":
            w = dim(req("width"), nm + ".width", um, positive=True, allow_zero=False)
            h = dim(req("height"), nm + ".height", um, positive=True, allow_zero=False)
            wv = w.value if w.value is not None else self._evaluate(w.expr, nm + ".width")
            hv = h.value if h.value is not None else self._evaluate(h.expr, nm + ".height")
            if (s.get("corner") is None) == (s.get("center") is None):
                raise OpError("BAD_SHAPE", f"{nm}: give exactly one of 'corner' (lower left) or 'center'")
            if s.get("center") is not None:
                c = self.p2(s["center"], nm + ".center")
                x0, y0 = c.x - wv / 2, c.y - hv / 2
            else:
                c0 = self.p2(s["corner"], nm + ".corner")
                x0, y0 = c0.x, c0.y
            pts = [V(x0, y0, 0), V(x0 + wv, y0, 0), V(x0 + wv, y0 + hv, 0), V(x0, y0 + hv, 0)]
            g = [self.add(Part.LineSegment(pts[k], pts[(k + 1) % 4]), cons) for k in range(4)]
            for k in range(4):
                self.con(Sketcher.Constraint("Coincident", g[k], 2, g[(k + 1) % 4], 1))
            self.con(Sketcher.Constraint("Horizontal", g[0]))
            self.con(Sketcher.Constraint("Horizontal", g[2]))
            self.con(Sketcher.Constraint("Vertical", g[1]))
            self.con(Sketcher.Constraint("Vertical", g[3]))
            base = s.get("name") or f"r{i}"
            self.con(Sketcher.Constraint("DistanceX", g[0], 1, g[0], 2, wv), f"{base}_width", w)
            self.con(Sketcher.Constraint("DistanceY", g[1], 1, g[1], 2, hv), f"{base}_height", h)
            if s.get("center") is not None:  # keep it centred when the size changes
                cp = self.add(Part.Point(c), True)
                self.con(Sketcher.Constraint("Symmetric", g[0], 1, g[1], 2, cp, 1))
                self.lock_point(cp, 1, c)
            else:
                self.lock_point(g[0], 1, pts[0])
            return g
        if t == "circle":
            c = self.p2(req("center"), nm + ".center")
            if (s.get("diameter") is None) == (s.get("radius") is None):
                raise OpError("BAD_SHAPE", f"{nm}: give exactly one of 'diameter' or 'radius'")
            if s.get("diameter") is not None:
                d = dim(s["diameter"], nm + ".diameter", um, positive=True, allow_zero=False)
                r = (d.value if d.value is not None else self._evaluate(d.expr, nm + ".diameter")) / 2
                kind = "Diameter"
            else:
                d = dim(s["radius"], nm + ".radius", um, positive=True, allow_zero=False)
                r = d.value if d.value is not None else self._evaluate(d.expr, nm + ".radius")
                kind = "Radius"
            g = self.add(Part.Circle(c, V(0, 0, 1), r), cons)
            self.lock_point(g, 3, c)
            self.con(Sketcher.Constraint(kind, g, 2 * r if kind == "Diameter" else r),
                     s.get("name") or f"c{i}_{kind.lower()}", d)
            return [g]
        if t == "point":
            p = self.p2(req("at"), nm + ".at")
            g = self.add(Part.Point(p), True)
            self.lock_point(g, 1, p)
            return [g]
        if t in ("polygon", "polyline"):
            pts = req("points")
            if not isinstance(pts, list) or len(pts) < 2:
                raise OpError("BAD_SHAPE", f"{nm}: points needs at least 2 entries")
            closed = t == "polygon" or bool(s.get("closed", False))
            return self._poly(pts, closed, cons, nm)
        if t == "regular_polygon":
            c = self.p2(req("center"), nm + ".center")
            n = int(req("sides"))
            if n < 3:
                raise OpError("BAD_SHAPE", f"{nm}: sides must be >= 3")
            if (s.get("circumradius") is None) == (s.get("across_flats") is None):
                raise OpError("BAD_SHAPE", f"{nm}: give exactly one of 'circumradius' or 'across_flats'")
            R = num(s["circumradius"], nm + ".circumradius", um) if s.get("circumradius") is not None else \
                num(s["across_flats"], nm + ".across_flats", um) / 2 / math.cos(math.pi / n)
            a0 = math.radians(float(s.get("rotation", 0)))
            pts = [[c.x + R * math.cos(a0 + 2 * math.pi * k / n), c.y + R * math.sin(a0 + 2 * math.pi * k / n)]
                   for k in range(n)]
            return self._poly(pts, True, cons, nm, raw_mm=True)
        if t == "slot":
            a, b = self.p2(req("start"), nm + ".start"), self.p2(req("end"), nm + ".end")
            w = num(req("width"), nm + ".width", um, positive=True, allow_zero=False)
            d = b - a
            if d.Length < TOL:
                raise OpError("BAD_SHAPE", f"{nm}: start and end coincide; use a circle")
            nrm = V(-d.y, d.x, 0)
            nrm.normalize()
            o = nrm * (w / 2)
            q = [a - o, b - o, b + o, a + o]
            pts = [[q[0].x, q[0].y], [q[1].x, q[1].y, 1.0], [q[2].x, q[2].y], [q[3].x, q[3].y, 1.0]]
            return self._poly(pts, True, cons, nm, raw_mm=True)
        if t == "line":
            return self._poly([req("start"), req("end")], False, cons, nm)
        if t == "arc":
            c = self.p2(req("center"), nm + ".center")
            r = num(req("radius"), nm + ".radius", um, positive=True, allow_zero=False)
            a1, a2 = math.radians(float(req("start_angle"))), math.radians(float(req("end_angle")))
            while a2 <= a1:
                a2 += 2 * math.pi
            g = self.add(Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), r), a1, a2), cons)
            self.chain([g], cons)
            return [g]
        raise AssertionError(t)

    def _poly(self, pts, closed, cons, nm, raw_mm=False):
        P = []
        for k, q in enumerate(pts):
            if not isinstance(q, (list, tuple)) or len(q) not in (2, 3):
                raise OpError("BAD_SHAPE", f"{nm}.points[{k}]: expected [x, y] or [x, y, bulge]")
            if raw_mm:
                P.append((V(float(q[0]), float(q[1]), 0), float(q[2]) if len(q) == 3 else 0.0))
            else:
                p = self.p2(q[:2], f"{nm}.points[{k}]")
                P.append((p, float(q[2]) if len(q) == 3 else 0.0))
        if closed and (P[0][0] - P[-1][0]).Length < 1e-9:
            P = P[:-1]
        segs = len(P) if closed else len(P) - 1
        gids = []
        for k in range(segs):
            p1, b = P[k]
            p2 = P[(k + 1) % len(P)][0]
            if (p2 - p1).Length < 1e-9:
                raise OpError("BAD_SHAPE", f"{nm}: points {k} and {(k + 1) % len(P)} coincide")
            g = Part.LineSegment(p1, p2) if abs(b) < 1e-12 else _bulge_arc(p1, p2, b)
            gids.append(self.add(g, cons))
        self.chain(gids, cons)
        return gids

    def _evaluate(self, expr, name):
        try:
            q = self.sk.evalExpression(expr)
        except Exception as exc:
            raise OpError("INVALID_EXPRESSION", f"{name}: cannot evaluate {expr!r}: {exc}",
                          hint="Expressions reference parameters as Params.<name> (set_parameters creates them)")
        return float(getattr(q, "Value", q))


def build_sketch(ctx, sk, p, name):
    sk.deleteAllGeometry()
    for k in range(len(sk.Constraints) - 1, -1, -1):
        sk.delConstraint(k)
    for path, _ in list(getattr(sk, "ExpressionEngine", []) or []):
        if "Constraints" in path:
            sk.setExpression(path, None)
    b = SketchBuilder(sk, ctx.unit_mm, name)
    shapes = p.get("shapes") or []
    if not isinstance(shapes, list):
        raise OpError("BAD_SHAPE", f"{name}.shapes must be a list")
    for i, s in enumerate(shapes):
        b.shape(s, i)
    sk.recompute()
    bad = {k: list(getattr(sk, k)) for k in ("ConflictingConstraints", "RedundantConstraints",
                                             "MalformedConstraints") if list(getattr(sk, k))}
    if bad:
        raise OpError("SKETCH_OVERCONSTRAINED", f"{name}: the sketch's constraints are inconsistent ({bad})",
                      category="geometry", details=bad,
                      hint="Shapes that share an end point are joined automatically; do not repeat an edge")


def place_sketch(ctx, body, sk, p, name):
    """Attach to an origin plane with an offset. 'on_face' resolves a face of the current tip once and stores the
    selector, so the sketch follows the face on the next edit (see regenerate)."""
    org = ctx.origin(body)
    keys = [k for k in ("plane", "on_face", "origin") if p.get(k) is not None]
    if len(keys) > 1:
        raise OpError("BAD_PLACEMENT", f"{name}: give only one of plane, on_face, origin/normal")
    if p.get("on_face") is not None:
        tip = body.Tip
        if tip is None or tip.Shape.isNull():
            raise OpError("NO_SOLID_YET", f"{name}: on_face needs a solid to sketch on", hint="Pad a base first")
        fn = select_faces(tip.Shape, p["on_face"], name + ".on_face")
        if len(fn) != 1:
            raise OpError("AMBIGUOUS_SELECTOR", f"{name}.on_face matches {len(fn)} faces ({fn}); it must match one",
                          hint="Add 'extreme': 'max' or 'near': [x, y, z]")
        f = tip.Shape.getElement(fn[0])
        if _surface_kind(f) != "plane":
            raise OpError("NOT_PLANAR", f"{name}.on_face: {fn[0]} is a {_surface_kind(f)}, not a plane")
        n = _face_normal(f)
        rot = rotation_from(n)
        origin = V(0, 0, 0) + n * f.CenterOfMass.dot(n)  # the global origin projected onto the face
        store_json(sk, "AgentCADRef", {"on_face": p["on_face"]})
        attach_abs(sk, org, App.Placement(origin, rot))
        return
    if p.get("origin") is not None or p.get("normal") is not None:
        o = vec(p.get("origin") or [0, 0, 0], name + ".origin", ctx.unit_mm)
        n = vec(p.get("normal") or [0, 0, 1], name + ".normal", 1.0)
        xd = vec(p["x_dir"], name + ".x_dir", 1.0) if p.get("x_dir") is not None else None
        attach_abs(sk, org, App.Placement(V(*o), rotation_from(n, xd)))
        return
    plane = (p.get("plane") or "XY").upper()
    if plane not in PLANES:
        raise OpError("BAD_PLACEMENT", f"{name}.plane must be XY, XZ or YZ")
    sk.AttachmentSupport = [(org[PLANES[plane][0]], "")]
    sk.MapMode = "FlatFace"
    off = dim(p.get("offset") or 0, name + ".offset", ctx.unit_mm)
    sk.AttachmentOffset = App.Placement(V(0, 0, off.value or 0), App.Rotation())
    _clear_expr(sk, "AttachmentOffset.Base.z")
    if off.expr:
        sk.setExpression(".AttachmentOffset.Base.z", off.expr)


def attach_abs(sk, org, plc):
    sk.AttachmentSupport = [(org["XY_Plane"], "")]
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = plc


# --- operations ------------------------------------------------------------------------------------------------

def _need(p, k, op):
    if p.get(k) is None:
        raise OpError("MISSING_PARAM", f"{op}: missing required parameter {k!r}")
    return p[k]


def _axis_link(ctx, body, ax, name, sketch=None):
    """'X'|'Y'|'Z' -> origin axis; 'V'|'H' -> the sketch's own axes; 'sketch_edge:N' -> a sketch line."""
    if isinstance(ax, str):
        a = ax.upper()
        if a in ("X", "Y", "Z"):
            return (ctx.origin(body)[f"{a}_Axis"], [""])
        if a in ("V", "H"):
            if sketch is None:
                raise OpError("BAD_AXIS", f"{name}: 'V'/'H' (sketch axes) need a sketch")
            return (sketch, [f"{a}_Axis"])
        m = re.fullmatch(r"SKETCH_EDGE:(\d+)", a)
        if m and sketch is not None:
            return (sketch, [f"Edge{int(m.group(1)) + 1}"])
    raise OpError("BAD_AXIS", f"{name}: axis must be 'X', 'Y', 'Z', 'V' or 'H' (sketch axes), "
                              f"or 'sketch_edge:<index>', got {ax!r}")


def _plane_link(ctx, body, pl, name):
    m = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}
    if isinstance(pl, str) and pl.upper() in m:
        return (ctx.origin(body)[m[pl.upper()]], [""])
    raise OpError("BAD_PLANE", f"{name}: plane must be 'XY', 'XZ' or 'YZ', got {pl!r}")


def _new_feature(ctx, body, type_id, base_name):
    tip = body.Tip
    obj = body.newObject(type_id, base_name)
    if type_id != "Sketcher::SketchObject":
        # transform features are not made Tip by newObject when scripted; the next feature would go before them
        body.Tip = obj
        if tip is not None and getattr(obj, "BaseFeature", None) is None and tip.TypeId != "Sketcher::SketchObject":
            pass
    return obj


def op_set_parameters(ctx, p, i):
    params = _need(p, "params", "set_parameters")
    if not isinstance(params, dict) or not params:
        raise OpError("INVALID_OBJECT", "set_parameters.params must be a non-empty object {name: value}")
    ss = ctx.doc.getObject("Params")
    if ss is None:
        ss = ctx.doc.addObject("Spreadsheet::Sheet", "Params")
        ctx.created.append(ss.Name)
    elif ss.Name not in ctx.created and ss.Name not in ctx.modified:
        ctx.modified.append(ss.Name)
    for name, val in params.items():
        if not _IDENT.match(name):
            raise OpError("BAD_PARAMETER_NAME", f"Parameter name {name!r} is not an identifier")
        cell = ss.getCellFromAlias(name)
        if cell is None:
            row = 1
            while ss.getContents(f"A{row}") or ss.getContents(f"B{row}"):
                row += 1
            ss.set(f"A{row}", name)
            cell = f"B{row}"
            try:
                ss.setAlias(cell, name)
            except ValueError:
                ss.set(f"A{row}", "")
                raise OpError("BAD_PARAMETER_NAME", f"FreeCAD rejects {name!r} as a parameter name",
                              hint="It is a reserved word or unit (e.g. t, m, mm, deg, pi); use a longer name "
                                   "such as thickness")
        if isinstance(val, str) and val.strip().startswith("="):
            ss.set(cell, "=" + val.strip()[1:].strip())
        elif isinstance(val, bool) or not isinstance(val, (int, float, str)):
            raise OpError("INVALID_NUMBER", f"set_parameters.{name}: expected a number, unit string or '=expr'")
        elif isinstance(val, str):
            ss.set(cell, f"={num(val, 'set_parameters.' + name, ctx.unit_mm)}")
        else:
            ss.set(cell, repr(float(val) * ctx.unit_mm) if ctx.unit_mm != 1 else repr(val))
    ss.recompute()
    return ss, {"parameters": sorted(params)}


def op_add_sketch(ctx, p, i, obj=None):
    body = ctx.body(p.get("body"))
    sk = obj or _new_feature(ctx, body, "Sketcher::SketchObject", "Sketch")
    place_sketch(ctx, body, sk, p, "add_sketch")
    build_sketch(ctx, sk, p, "add_sketch")
    sk.solve()
    return sk, {"geometry": len(sk.Geometry), "dof": int(getattr(sk, "DoF", 0) or 0)}


def _profile(ctx, p, op):
    return ctx.sketch(_need(p, "sketch", op), f"{op}.sketch")


def op_pad(ctx, p, i, obj=None, pocket=False):
    name = "pocket" if pocket else "pad"
    sk = _profile(ctx, p, name)
    body = ctx.body(p.get("body"))
    f = obj or _new_feature(ctx, body, "PartDesign::Pocket" if pocket else "PartDesign::Pad",
                            "Pocket" if pocket else "Pad")
    f.Profile = sk
    through = bool(p.get("through_all"))
    if through and not pocket:
        raise OpError("BAD_VALUE", "pad has no through_all; give a length")
    if through:
        f.Type = "ThroughAll"
    else:
        f.Type = "Length"
        key = "depth" if pocket else "length"
        set_dim(f, "Length", dim(_need(p, key, name), f"{name}.{key}", ctx.unit_mm, positive=True, allow_zero=False))
    f.Midplane = bool(p.get("symmetric", False))
    f.Reversed = bool(p.get("reversed", False))
    return f, {}


def op_revolve(ctx, p, i, obj=None, groove=False):
    name = "groove" if groove else "revolve"
    sk = _profile(ctx, p, name)
    body = ctx.body(p.get("body"))
    f = obj or _new_feature(ctx, body, "PartDesign::Groove" if groove else "PartDesign::Revolution",
                            "Groove" if groove else "Revolution")
    f.Profile = sk
    f.ReferenceAxis = _axis_link(ctx, body, p.get("axis") or "V", name + ".axis", sk)
    set_dim(f, "Angle", dim(p.get("angle", 360), name + ".angle", length=False, positive=True, allow_zero=False))
    f.Midplane = bool(p.get("symmetric", False))
    f.Reversed = bool(p.get("reversed", False))
    return f, {}


def op_hole(ctx, p, i, obj=None):
    sk = _profile(ctx, p, "hole")
    if not any(type(g).__name__ == "Circle" for g in sk.Geometry):
        raise OpError("NO_CIRCLES", "hole: the sketch has no circles; each circle centre becomes a hole")
    body = ctx.body(p.get("body"))
    f = obj or _new_feature(ctx, body, "PartDesign::Hole", "Hole")
    f.Profile = sk
    f.Threaded = False
    thread = p.get("thread")
    if thread:
        size = str(thread).upper()
        f.ThreadType = "ISOMetricProfile"
        if size not in f.getEnumerationsOfProperty("ThreadSize"):
            raise OpError("BAD_THREAD", f"hole.thread {thread!r} is not an ISO metric size",
                          hint=f"Sizes: {f.getEnumerationsOfProperty('ThreadSize')[:20]}...")
        f.ThreadSize = size
        f.Threaded = bool(p.get("model_thread", False))
        f.ModelThread = bool(p.get("model_thread", False))
    else:
        f.ThreadType = "None"
        set_dim(f, "Diameter", dim(_need(p, "diameter", "hole"), "hole.diameter", ctx.unit_mm, positive=True,
                                   allow_zero=False))
    if p.get("through_all"):
        f.DepthType = "ThroughAll"
    else:
        f.DepthType = "Dimension"
        set_dim(f, "Depth", dim(_need(p, "depth", "hole"), "hole.depth", ctx.unit_mm, positive=True, allow_zero=False))
    f.DrillPoint = "Angled" if p.get("drill_point") == "angled" else "Flat"
    cb, cs = p.get("counterbore"), p.get("countersink")
    if cb and cs:
        raise OpError("BAD_VALUE", "hole: counterbore and countersink are exclusive")
    if cb:
        f.HoleCutType = "Counterbore"
        f.HoleCutCustomValues = True
        set_dim(f, "HoleCutDiameter", dim(_need(cb, "diameter", "hole.counterbore"), "hole.counterbore.diameter",
                                          ctx.unit_mm, positive=True))
        set_dim(f, "HoleCutDepth", dim(_need(cb, "depth", "hole.counterbore"), "hole.counterbore.depth", ctx.unit_mm,
                                       positive=True))
    elif cs:
        f.HoleCutType = "Countersink"
        f.HoleCutCustomValues = True
        set_dim(f, "HoleCutDiameter", dim(_need(cs, "diameter", "hole.countersink"), "hole.countersink.diameter",
                                          ctx.unit_mm, positive=True))
        f.HoleCutCountersinkAngle = float(cs.get("angle", 90))
    else:
        f.HoleCutType = "None"
    f.Reversed = bool(p.get("reversed", False))
    return f, {"holes": sum(1 for g in sk.Geometry if type(g).__name__ == "Circle")}


def _base_shape(ctx, body, f, op):
    base = f.BaseFeature if f is not None and getattr(f, "BaseFeature", None) is not None else body.Tip
    if base is None or base.Shape.isNull():
        raise OpError("NO_SOLID_YET", f"{op}: there is no solid to work on yet")
    return base


def op_dress(ctx, p, i, obj=None, kind="fillet"):
    body = ctx.body(p.get("body"))
    sel = _need(p, "faces" if kind == "thickness" else "edges", kind)
    if obj is None:
        base = _base_shape(ctx, body, None, kind)
        f = _new_feature(ctx, body, {"fillet": "PartDesign::Fillet", "chamfer": "PartDesign::Chamfer",
                                     "thickness": "PartDesign::Thickness"}[kind], kind.capitalize())
    else:
        f = obj
        base = _base_shape(ctx, body, f, kind)
    names = (select_faces if kind == "thickness" else select_edges)(base.Shape, sel, f"{kind}.{'faces' if kind == 'thickness' else 'edges'}")
    f.Base = (base, names)
    store_json(f, "AgentCADRef", {"selector": sel, "kind": "faces" if kind == "thickness" else "edges"})
    if kind == "fillet":
        set_dim(f, "Radius", dim(_need(p, "radius", "fillet"), "fillet.radius", ctx.unit_mm, positive=True,
                                 allow_zero=False))
    elif kind == "chamfer":
        if p.get("angle") is not None:
            f.ChamferType = "Distance and Angle"
            set_dim(f, "Angle", dim(p["angle"], "chamfer.angle", length=False, positive=True, allow_zero=False))
        elif p.get("size2") is not None:
            f.ChamferType = "Two distances"
            set_dim(f, "Size2", dim(p["size2"], "chamfer.size2", ctx.unit_mm, positive=True, allow_zero=False))
        else:
            f.ChamferType = "Equal distance"
        set_dim(f, "Size", dim(_need(p, "size", "chamfer"), "chamfer.size", ctx.unit_mm, positive=True,
                               allow_zero=False))
    else:
        set_dim(f, "Value", dim(_need(p, "thickness", "thickness"), "thickness.thickness", ctx.unit_mm,
                                positive=True, allow_zero=False))
        f.Reversed = not bool(p.get("outward", False))
        f.Join = "Intersection" if p.get("join") == "intersection" else "Arc"
    return f, {("faces" if kind == "thickness" else "edges"): names}


def _originals(ctx, p, op):
    feats = _need(p, "features", op)
    if not isinstance(feats, list) or not feats:
        raise OpError("BAD_VALUE", f"{op}.features must be a non-empty list of feature references")
    out = [ctx.obj(r, f"{op}.features[{k}]") for k, r in enumerate(feats)]
    for o in out:
        if o.TypeId == "Sketcher::SketchObject":
            raise OpError("BAD_VALUE", f"{op}: {o.Name} is a sketch; pattern the feature made from it")
    return out


def op_pattern(ctx, p, i, obj=None, kind="linear_pattern"):
    body = ctx.body(p.get("body"))
    origs = _originals(ctx, p, kind)
    tid = {"linear_pattern": "PartDesign::LinearPattern", "polar_pattern": "PartDesign::PolarPattern",
           "mirror": "PartDesign::Mirrored"}[kind]
    f = obj or _new_feature(ctx, body, tid, {"linear_pattern": "LinearPattern", "polar_pattern": "PolarPattern",
                                            "mirror": "Mirrored"}[kind])
    f.Originals = origs
    if kind == "mirror":
        f.MirrorPlane = _plane_link(ctx, body, _need(p, "plane", kind), "mirror.plane")
        return f, {}
    occ = dim(_need(p, "occurrences", kind), f"{kind}.occurrences", length=False, positive=True)
    if occ.value is not None and (occ.value < 2 or occ.value != int(occ.value)):
        raise OpError("OUT_OF_RANGE", f"{kind}.occurrences must be an integer >= 2")
    if occ.expr:
        f.setExpression("Occurrences", occ.expr)
    else:
        _clear_expr(f, "Occurrences")
        f.Occurrences = int(occ.value)
    if kind == "linear_pattern":
        f.Direction = _axis_link(ctx, body, p.get("direction") or "X", "linear_pattern.direction")
        if (p.get("length") is None) == (p.get("spacing") is None):
            raise OpError("BAD_VALUE", "linear_pattern: give exactly one of 'length' (first to last) or 'spacing'")
        if p.get("spacing") is not None:
            f.Mode = "Spacing"
            set_dim(f, "Offset", dim(p["spacing"], "linear_pattern.spacing", ctx.unit_mm, positive=True,
                                     allow_zero=False))
        else:
            f.Mode = "Extent"
            set_dim(f, "Length", dim(p["length"], "linear_pattern.length", ctx.unit_mm, positive=True,
                                     allow_zero=False))
    else:
        f.Axis = _axis_link(ctx, body, p.get("axis") or "Z", "polar_pattern.axis")
        f.Mode = "Extent"
        set_dim(f, "Angle", dim(p.get("angle", 360), "polar_pattern.angle", length=False, positive=True,
                                allow_zero=False))
    f.Reversed = bool(p.get("reversed", False))
    return f, {}


PRIMS = {"box": ("Box", {"length": "Length", "width": "Width", "height": "Height"}),
         "cylinder": ("Cylinder", {"radius": "Radius", "height": "Height", "angle": "Angle"}),
         "cone": ("Cone", {"radius1": "Radius1", "radius2": "Radius2", "height": "Height", "angle": "Angle"}),
         "sphere": ("Sphere", {"radius": "Radius"}),
         "torus": ("Torus", {"radius1": "Radius1", "radius2": "Radius2"}),
         "prism": ("Prism", {"sides": "Polygon", "circumradius": "Circumradius", "height": "Height"}),
         "wedge": ("Wedge", {k: k.capitalize() for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax",
                                                          "x2min", "x2max", "z2min", "z2max")})}


def op_primitive(ctx, p, i, obj=None):
    kind = _need(p, "kind", "primitive")
    if kind not in PRIMS:
        raise OpError("BAD_VALUE", f"primitive.kind must be one of {sorted(PRIMS)}")
    body = ctx.body(p.get("body"))
    cls, props = PRIMS[kind]
    sub = bool(p.get("subtractive", False))
    f = obj or _new_feature(ctx, body, f"PartDesign::{'Subtractive' if sub else 'Additive'}{cls}",
                            ("Subtractive" if sub else "Additive") + cls)
    dims = p.get("dims") or {}
    unknown = set(dims) - set(props)
    if unknown:
        raise OpError("BAD_VALUE", f"primitive.dims: unknown {sorted(unknown)} for {kind}", hint=f"Use {sorted(props)}")
    for k, v in dims.items():
        if props[k] == "Polygon":
            f.Polygon = int(v)
        elif props[k] == "Angle":
            set_dim(f, "Angle", dim(v, f"primitive.dims.{k}", length=False))
        else:
            set_dim(f, props[k], dim(v, f"primitive.dims.{k}", ctx.unit_mm))
    pos = vec(p.get("position") or [0, 0, 0], "primitive.position", ctx.unit_mm)
    n = vec(p.get("direction") or [0, 0, 1], "primitive.direction", 1.0)
    f.MapMode = "Deactivated"
    f.Placement = App.Placement(V(*pos), App.Rotation(V(0, 0, 1), V(*n)))
    return f, {}


def op_loft(ctx, p, i, obj=None):
    secs = _need(p, "sections", "loft")
    if not isinstance(secs, list) or len(secs) < 2:
        raise OpError("BAD_VALUE", "loft.sections needs at least two sketches")
    sks = [ctx.sketch(s, f"loft.sections[{k}]") for k, s in enumerate(secs)]
    body = ctx.body(p.get("body"))
    sub = bool(p.get("subtractive", False))
    f = obj or _new_feature(ctx, body, "PartDesign::SubtractiveLoft" if sub else "PartDesign::AdditiveLoft",
                            "SubtractiveLoft" if sub else "AdditiveLoft")
    f.Profile = sks[0]
    f.Sections = sks[1:]
    f.Ruled = bool(p.get("ruled", False))
    f.Closed = bool(p.get("closed", False))
    return f, {}


def op_sweep(ctx, p, i, obj=None):
    prof = ctx.sketch(_need(p, "sketch", "sweep"), "sweep.sketch")
    path = ctx.sketch(_need(p, "path", "sweep"), "sweep.path")
    body = ctx.body(p.get("body"))
    sub = bool(p.get("subtractive", False))
    f = obj or _new_feature(ctx, body, "PartDesign::SubtractivePipe" if sub else "PartDesign::AdditivePipe",
                            "SubtractivePipe" if sub else "AdditivePipe")
    f.Profile = prof
    f.Spine = (path, [])
    f.Mode = "Frenet" if p.get("frenet") else "Standard"
    return f, {}


def op_helix(ctx, p, i, obj=None):
    sk = _profile(ctx, p, "helix")
    body = ctx.body(p.get("body"))
    sub = bool(p.get("subtractive", False))
    f = obj or _new_feature(ctx, body, "PartDesign::SubtractiveHelix" if sub else "PartDesign::AdditiveHelix",
                            "SubtractiveHelix" if sub else "AdditiveHelix")
    f.Profile = sk
    f.ReferenceAxis = _axis_link(ctx, body, p.get("axis") or "V", "helix.axis", sk)
    f.Mode = "pitch-height-angle"
    set_dim(f, "Pitch", dim(_need(p, "pitch", "helix"), "helix.pitch", ctx.unit_mm, positive=True, allow_zero=False))
    set_dim(f, "Height", dim(_need(p, "height", "helix"), "helix.height", ctx.unit_mm, positive=True,
                             allow_zero=False))
    f.LeftHanded = bool(p.get("left_handed", False))
    f.Reversed = bool(p.get("reversed", False))
    return f, {}


OPS = {
    "add_sketch": op_add_sketch,
    "pad": op_pad,
    "pocket": lambda c, p, i, obj=None: op_pad(c, p, i, obj, pocket=True),
    "revolve": op_revolve,
    "groove": lambda c, p, i, obj=None: op_revolve(c, p, i, obj, groove=True),
    "hole": op_hole,
    "fillet": lambda c, p, i, obj=None: op_dress(c, p, i, obj, "fillet"),
    "chamfer": lambda c, p, i, obj=None: op_dress(c, p, i, obj, "chamfer"),
    "thickness": lambda c, p, i, obj=None: op_dress(c, p, i, obj, "thickness"),
    "linear_pattern": lambda c, p, i, obj=None: op_pattern(c, p, i, obj, "linear_pattern"),
    "polar_pattern": lambda c, p, i, obj=None: op_pattern(c, p, i, obj, "polar_pattern"),
    "mirror": lambda c, p, i, obj=None: op_pattern(c, p, i, obj, "mirror"),
    "primitive": op_primitive,
    "loft": op_loft,
    "sweep": op_sweep,
    "helix": op_helix,
}
EDITABLE = set(OPS)


def op_modify_feature(ctx, p, i):
    f = ctx.obj(_need(p, "feature", "modify_feature"), "modify_feature.feature")
    rec = load_json(f, "AgentCADOp")
    if rec is None:
        raise OpError("NOT_EDITABLE", f"{f.Name} was not made by AgentCAD, so its op cannot be re-applied",
                      hint="Delete it and add a new feature, or edit parameters it references")
    changes = _need(p, "set", "modify_feature")
    if not isinstance(changes, dict) or not changes:
        raise OpError("INVALID_OBJECT", "modify_feature.set must be a non-empty object of op parameters")
    for k in ("op", "body", "tag"):
        if k in changes:
            raise OpError("BAD_VALUE", f"modify_feature cannot change {k!r}")
    params = {**rec, **changes}
    params = {k: v for k, v in params.items() if v is not None}
    ctx.op_of[f.Name] = i
    _, info = OPS[rec["op"]](ctx, params, i, obj=f)
    store_json(f, "AgentCADOp", freeze_refs(ctx, params))
    if f.Name not in ctx.modified and f.Name not in ctx.created:
        ctx.modified.append(f.Name)
    return f, info


def _uses(u, f):
    """Whether feature u depends on f other than as the next step of the body's chain (BaseFeature, and a
    dress-up's Base, which re-resolves against the new BaseFeature)."""
    for prop in ("Profile", "Spine", "ReferenceAxis", "Direction", "Axis", "MirrorPlane"):
        v = getattr(u, prop, None) if prop in u.PropertiesList else None
        if isinstance(v, tuple) and v and v[0] is f or v is f:
            return True
    for prop in ("Originals", "Sections"):
        if prop in u.PropertiesList and any(x is f for x in (getattr(u, prop) or [])):
            return True
    return False


def op_delete_feature(ctx, p, i):
    f = ctx.obj(_need(p, "feature", "delete_feature"), "delete_feature.feature")
    if f.TypeId in ("PartDesign::Body", "Spreadsheet::Sheet", "App::Origin"):
        raise OpError("NOT_A_FEATURE", f"{f.Name} is a {f.TypeId}; delete_feature removes features and sketches")
    order, seen = [], set()

    def collect(o):
        if o.Name in seen:
            return
        seen.add(o.Name)
        for u in o.InList:
            if _uses(u, o):
                collect(u)
        order.append(o)

    collect(f)
    users = [o.Name for o in order if o is not f]
    if users and not p.get("cascade"):
        raise OpError("FEATURE_IN_USE", f"{f.Name} is used by {users}", entities=users,
                      hint="Delete those first, or pass cascade=true to delete them too")
    gone = []
    for o in order:  # dependents first
        name = o.Name
        body = next((b for b in o.InList if b.TypeId == "PartDesign::Body"), None)
        if body is not None:
            body.removeObject(o)
        ctx.doc.removeObject(name)
        gone.append(name)
    for n in gone:
        if n in ctx.created:
            ctx.created.remove(n)
        else:
            ctx.deleted.append(n)
    return None, {"deleted": gone}


REF_KEYS = ("sketch", "path", "features", "sections", "body")


def freeze_refs(ctx, p):
    """Replace batch references ('$3') in a recorded op with object names, which stay valid in later batches."""
    def one(r):
        return ctx.refs.get(int(r[1:]), r) if isinstance(r, str) and re.fullmatch(r"\$\d+", r) else r
    out = dict(p)
    for k in REF_KEYS:
        if isinstance(out.get(k), list):
            out[k] = [one(r) for r in out[k]]
        elif k in out:
            out[k] = one(out[k])
    return out


META_OPS = {"set_parameters": op_set_parameters, "modify_feature": op_modify_feature,
            "delete_feature": op_delete_feature}


# --- regenerate / recompute ------------------------------------------------------------------------------------

def regenerate(ctx):
    """Recompute in feature order, re-resolving stored selectors against each feature's (new) base shape."""
    ctx.doc.recompute()
    for b in [o for o in ctx.doc.Objects if o.TypeId == "PartDesign::Body"]:
        for f in list(b.Group):
            ref = load_json(f, "AgentCADRef")
            if not ref:
                continue
            if f.TypeId == "Sketcher::SketchObject" and ref.get("on_face") is not None:
                prev = _prev_solid(b, f)
                if prev is None:
                    continue
                fn = select_faces(prev.Shape, ref["on_face"], f"{f.Name}.on_face")
                face = prev.Shape.getElement(fn[0])
                n = _face_normal(face)
                plc = App.Placement(V(0, 0, 0) + n * face.CenterOfMass.dot(n), rotation_from(n))
                if not plc.isSame(f.AttachmentOffset, 1e-9):
                    f.AttachmentOffset = plc
                    ctx.doc.recompute()
            elif ref.get("selector") is not None and getattr(f, "BaseFeature", None) is not None:
                base = f.BaseFeature
                if base.Shape.isNull():
                    continue
                fn = (select_faces if ref["kind"] == "faces" else select_edges)(base.Shape, ref["selector"],
                                                                                f"{f.Name}.{ref['kind']}")
                cur = [s.split(".")[-1].lstrip("?") for s in f.Base[1]]
                stale = "Invalid" in f.State or "Error" in f.State  # same short names, old internal mapping
                if f.Base[0] is not base or cur != fn or stale or any(s.startswith("?") for s in f.Base[1]):
                    f.Base = (base, [])  # drop the old mapping, then select afresh
                    f.Base = (base, fn)
                    ctx.doc.recompute()


def _prev_solid(body, f):
    grp = list(body.Group)
    for o in reversed(grp[:grp.index(f)]):
        if o.TypeId != "Sketcher::SketchObject" and hasattr(o, "Shape") and not o.Shape.isNull() and \
                o.TypeId.startswith("PartDesign::"):
            return o
    return None


def broken(doc):
    out = []
    for o in doc.Objects:
        st = o.State
        if "Invalid" in st or "Error" in st:
            msg = o.getStatusString() if hasattr(o, "getStatusString") else ""
            out.append({"feature": o.Name, "tag": getattr(o, "AgentCADTag", "") or None, "type": o.TypeId,
                        "message": msg, "state": st})
    return out


def hint_for(msg):
    m = (msg or "").lower()
    if "not closed" in m or "wire" in m and "closed" in m or "open" in m:
        return "The sketch profile must be closed loops (polygon or polyline closed=true)"
    if "multiple solids" in m or "not a solid" in m or "result has multiple" in m:
        return "The feature does not touch the body (or splits it); a Body must stay one solid"
    if "brep_api" in m or "command not done" in m or "fillet" in m or "chamfer" in m:
        return "Fillet/chamfer too large for the selected edges, or the edges do not suit it; reduce the size"
    if "intersect" in m or "does not intersect" in m or "nothing" in m:
        return "The feature does not cut or touch the solid; check its sketch position and direction"
    if "edge link" in m or "face link" in m:
        return "A stored edge or face reference no longer resolves; modify_feature with a new selector"
    return None


# --- summaries -------------------------------------------------------------------------------------------------

def shape_summary(sh):
    if sh is None or sh.isNull():
        return None
    bb = sh.BoundBox
    out = {"valid": sh.isValid(), "solids": len(sh.Solids), "faces": len(sh.Faces), "edges": len(sh.Edges),
           "volume": r6(sh.Volume), "area": r6(sh.Area),
           "bbox": [[r6(bb.XMin), r6(bb.YMin), r6(bb.ZMin)], [r6(bb.XMax), r6(bb.YMax), r6(bb.ZMax)]],
           "size": [r6(bb.XLength), r6(bb.YLength), r6(bb.ZLength)]}
    try:
        out["center_of_mass"] = v3(sh.CenterOfMass if hasattr(sh, "CenterOfMass") and sh.ShapeType == "Solid"
                                   else sh.Solids[0].CenterOfMass) if sh.Solids else None
    except Exception:
        out["center_of_mass"] = None
    out["holes"] = holes(sh)
    return out


def holes(sh):
    """Inner cylindrical faces grouped by axis line and diameter: one entry per bore."""
    found = []
    for f in sh.Faces:
        if _surface_kind(f) != "cylinder" or not _is_inner_cyl(f):
            continue
        s = f.Surface
        ax = V(s.Axis)
        ax.normalize()
        c = s.Center
        c = c - ax * c.dot(ax)  # point of the axis line closest to the origin
        d = 2 * s.Radius
        for h in found:
            if abs(h["d"] - d) < 1e-6 and abs(abs(h["ax"].dot(ax)) - 1) < 1e-9 and (h["c"] - c).Length < 1e-6:
                break
        else:
            found.append({"d": d, "ax": ax, "c": c})
    out = {}
    for h in found:
        k = f"{h['d']:.6g}"
        out[k] = out.get(k, 0) + 1
    return [{"diameter": float(k), "count": n} for k, n in sorted(out.items(), key=lambda kv: float(kv[0]))]


def feature_info(o, detail=False):
    d = {"name": o.Name, "type": o.TypeId.split("::")[-1]}
    t = getattr(o, "AgentCADTag", "")
    if t:
        d["tag"] = t
    if "Invalid" in o.State or "Error" in o.State:
        d["error"] = o.getStatusString()
    rec = load_json(o, "AgentCADOp")
    if rec and detail:
        d["op"] = rec
    elif rec:
        d["op"] = rec.get("op")
    if o.TypeId == "Sketcher::SketchObject":
        d["geometry"] = len(o.Geometry)
        d["dof"] = int(getattr(o, "DoF", 0) or 0)
        named = [c.Name for c in o.Constraints if c.Name]
        if named:
            d["dimensions"] = {c.Name: r6(c.Value) for c in o.Constraints if c.Name}
        pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
        d["plane"] = {"origin": v3(pl.Base), "normal": v3(pl.Rotation.multVec(V(0, 0, 1))),
                      "x_dir": v3(pl.Rotation.multVec(V(1, 0, 0)))}
    exprs = {path.lstrip("."): e for path, e in (getattr(o, "ExpressionEngine", []) or [])}
    if exprs:
        d["expressions"] = exprs
    return d


def parameters(doc):
    """Parameter values in the part's unit (FreeCAD holds them in mm)."""
    ss = doc.getObject("Params")
    if ss is None:
        return {}
    k = UNIT_MM.get((doc.Meta or {}).get("agentcad_units", "mm"), 1.0)
    out = {}
    row = 1
    while row < 1000:
        name = ss.getContents(f"A{row}")
        if not name and not ss.getContents(f"B{row}"):
            break
        alias = ss.getAlias(f"B{row}")
        if alias:
            v = ss.get(alias)
            out[alias] = {"value": r6(getattr(v, "Value", v) / k) if not isinstance(v, str) else v,
                          **({"formula": ss.getContents(f"B{row}")} if ss.getContents(f"B{row}").startswith("=")
                             and not _is_literal(ss.getContents(f"B{row}")) else {})}
        row += 1
    return out


def _is_literal(c):
    try:
        float(c.lstrip("="))
        return True
    except ValueError:
        return False


def summary(doc, detail=False):
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    out = {"units": (doc.Meta or {}).get("agentcad_units", "mm"), "bodies": [], "parameters": parameters(doc)}
    for b in bodies:
        grp = list(b.Group)
        tip = b.Tip
        after = grp[grp.index(tip) + 1:] if tip in grp else []
        out["bodies"].append({"name": b.Name, "tip": tip.Name if tip else None,
                              "features": [feature_info(o, detail) for o in grp],
                              **({"after_tip": [o.Name for o in after]} if after else {}),
                              "shape": shape_summary(b.Shape)})
    others = [o for o in doc.Objects if o.TypeId not in ("PartDesign::Body", "Spreadsheet::Sheet", "App::Origin",
                                                         "App::Plane", "App::Line", "App::Point")
              and not any(b.hasObject(o) for b in bodies)]
    if others:
        out["outside_bodies"] = [{"name": o.Name, "type": o.TypeId} for o in others]
    return out


# --- validation ------------------------------------------------------------------------------------------------

def issue(code, sev, msg, hint=None, **kw):
    d = {"code": code, "severity": sev, "message": msg}
    if hint:
        d["hint"] = hint
    d.update(kw)
    return d


def check_doc(doc):
    issues = []
    for b in broken(doc):
        issues.append(issue("FEATURE_ERROR", "error", f"{b['feature']} ({b['type']}): {b['message'] or 'invalid'}",
                            hint_for(b["message"]), entities=[b["feature"]]))
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    nonempty = [b for b in bodies if not b.Shape.isNull() and b.Shape.Volume > 0]
    if not bodies:
        issues.append(issue("NO_BODY", "error", "The document has no PartDesign Body",
                            "Build the part with add_sketch + pad (CADBench requires one Body)"))
    elif not nonempty:
        issues.append(issue("EMPTY_BODY", "error", "No Body has a solid with volume"))
    elif len(nonempty) > 1:
        issues.append(issue("MULTIPLE_BODIES", "error", f"{len(nonempty)} Bodies carry geometry; a part must be "
                            "one Body", "Model everything in one Body", entities=[b.Name for b in nonempty]))
    for b in nonempty:
        sh = b.Shape
        if len(sh.Solids) != 1:
            issues.append(issue("NOT_SINGLE_SOLID", "error", f"{b.Name} produces {len(sh.Solids)} solids",
                                "Every feature must touch the existing solid", entities=[b.Name]))
        if not sh.isValid():
            issues.append(issue("INVALID_SHAPE", "error", f"{b.Name}: the B-rep shape is not valid",
                                entities=[b.Name]))
        bad = _non_partdesign(b)
        if bad:
            issues.append(issue("NON_PARAMETRIC_GEOMETRY", "error", f"{b.Name} contains non-PartDesign geometry "
                                f"{bad}", "Use only PartDesign features (CADBench rejects baked shapes)",
                                entities=bad))
        grp = list(b.Group)
        if b.Tip in grp and grp.index(b.Tip) < len(grp) - 1:
            after = [o.Name for o in grp[grp.index(b.Tip) + 1:] if o.TypeId != "Sketcher::SketchObject"]
            if after:
                issues.append(issue("FEATURES_AFTER_TIP", "warning", f"{after} come after the Body's Tip and are "
                                    "not part of the solid", entities=after))
    for o in doc.Objects:
        if o.TypeId == "Sketcher::SketchObject":
            for k in ("ConflictingConstraints", "RedundantConstraints", "MalformedConstraints"):
                if list(getattr(o, k, []) or []):
                    issues.append(issue("SKETCH_CONSTRAINTS", "error" if k != "RedundantConstraints" else "warning",
                                        f"{o.Name}: {k} {list(getattr(o, k))}", entities=[o.Name]))
    return issues


def _non_partdesign(body):
    bad = []
    for o in body.Group:
        if o.TypeId in ALLOWED_TYPES:
            continue
        sh = getattr(o, "Shape", None)
        if sh is not None and not sh.isNull() and len(sh.Faces) > 0:
            bad.append(o.Name)
    return bad


REQ_KEYS = {
    "bbox": {"size", "min", "max", "tolerance", "any_orientation"}, "volume": {"value", "tolerance", "rel_tolerance"},
    "area": {"value", "tolerance", "rel_tolerance"}, "hole": {"diameter", "count", "tolerance"},
    "hole_count": {"count"}, "solid_count": {"count"}, "parameter": {"name", "value", "tolerance"},
    "center_of_mass": {"value", "tolerance"}, "feature_count": {"feature_type", "count", "min"},
}


REQ_NEEDS = {"bbox": [("size", "min", "max")], "volume": [("value",)], "area": [("value",)],
             "hole": [("diameter",)], "hole_count": [("count",)], "solid_count": [("count",)],
             "parameter": [("name",)], "center_of_mass": [("value",)], "feature_count": [("count", "min")]}


def check_requirements(doc, reqs):
    res, warns = [], []
    b = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()
              and o.Shape.Volume > 0), None)
    s = shape_summary(b.Shape) if b is not None else None
    params = parameters(doc)
    for k, r in enumerate(reqs or []):
        t = r.get("type")
        if t not in REQ_KEYS:
            res.append({"index": k, "type": t, "passed": False, "message": f"unknown requirement type {t!r}",
                        "hint": f"Types: {sorted(REQ_KEYS)}"})
            continue
        unknown = set(r) - REQ_KEYS[t] - {"type", "id", "source"}
        if unknown:
            warns.append(f"requirements[{k}] ({t}): unknown fields {sorted(unknown)} ignored")
        out = {"index": k, "type": t, **({"id": r["id"]} if r.get("id") else {})}
        missing = [alts for alts in REQ_NEEDS.get(t, []) if not any(r.get(a) is not None for a in alts)]
        if missing:
            out.update(passed=False, message=f"{t} needs {' and '.join(' or '.join(a) for a in missing)}",
                       hint=f"{t} fields: {sorted(REQ_KEYS[t])}")
            res.append(out)
            continue
        if s is None and t not in ("parameter",):
            out.update(passed=False, message="no solid to measure")
            res.append(out)
            continue
        tol = float(r.get("tolerance", 1e-3))
        if t == "bbox":
            ok = True
            if r.get("size") is not None:
                want = [float(x) for x in r["size"]]
                act = s["size"]
                if r.get("any_orientation"):  # compare sizes regardless of which axis carries which
                    want, act = sorted(want), sorted(act)
                dev = [abs(a - w) for a, w in zip(act, want)]
                ok = all(d <= tol for d in dev)
                out.update(expected=want, actual=act, deviation=[r6(d) for d in dev])
            for key, idx in (("min", 0), ("max", 1)):
                if r.get(key) is not None:
                    act = s["bbox"][idx]
                    dev = [abs(a - float(w)) for a, w in zip(act, r[key])]
                    ok = ok and all(d <= tol for d in dev)
                    out[f"actual_{key}"] = act
            out["passed"] = ok
        elif t in ("volume", "area"):
            act = s[t]
            want = float(r["value"])
            lim = float(r["rel_tolerance"]) * abs(want) if r.get("rel_tolerance") is not None else tol
            out.update(expected=want, actual=act, deviation=r6(act - want), passed=abs(act - want) <= lim)
        elif t == "hole":
            d = float(r["diameter"])
            n = sum(h["count"] for h in s["holes"] if abs(h["diameter"] - d) <= tol)
            want = int(r.get("count", 1))
            out.update(expected={"diameter": d, "count": want}, actual=n, passed=n == want,
                       found=s["holes"])
        elif t == "hole_count":
            n = sum(h["count"] for h in s["holes"])
            out.update(expected=int(r["count"]), actual=n, passed=n == int(r["count"]))
        elif t == "solid_count":
            out.update(expected=int(r["count"]), actual=s["solids"], passed=s["solids"] == int(r["count"]))
        elif t == "parameter":
            v = params.get(r.get("name"))
            act = None if v is None else v["value"]
            want = r.get("value")
            ok = act is not None and (want is None or (isinstance(act, float) and abs(act - float(want)) <= tol))
            out.update(name=r.get("name"), expected=want, actual=act, passed=ok)
        elif t == "center_of_mass":
            act = s["center_of_mass"]
            dev = [abs(a - float(w)) for a, w in zip(act, r["value"])]
            out.update(expected=r["value"], actual=act, passed=all(x <= tol for x in dev))
        elif t == "feature_count":
            feats = [o for o in b.Group if o.TypeId.endswith("::" + str(r["feature_type"]))] \
                if r.get("feature_type") else [o for o in b.Group if o.TypeId != "Sketcher::SketchObject"]
            n = len(feats)
            ok = n >= int(r["min"]) if r.get("min") is not None else n == int(r["count"])
            out.update(actual=n, passed=ok)
        res.append(out)
    return res, warns


# --- actions ---------------------------------------------------------------------------------------------------

def open_or_new(job):
    if job.get("input"):
        doc = App.openDocument(job["input"])
    else:
        doc = App.newDocument("Part")
        meta = dict(doc.Meta or {})
        meta["agentcad_units"] = job.get("units") or "mm"
        doc.Meta = meta
    return doc


PROGRESS = {"file": None}  # job["progress"]: a file the parent polls to show which operation runs (viewer)


def report_progress(**ev):
    if not PROGRESS["file"]:
        return
    try:
        with open(PROGRESS["file"], "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
    except OSError:
        pass


def run_ops(doc, ops):
    ctx = Ctx(doc)
    results = []
    for i, raw in enumerate(ops):
        name = raw.get("op")
        report_progress(step=i, total=len(ops))
        p = {k: v for k, v in raw.items() if k not in ("op", "comment")}
        try:
            if name in META_OPS:
                obj, info = META_OPS[name](ctx, p, i)
            elif name in OPS:
                obj, info = OPS[name](ctx, p, i)
                store_json(obj, "AgentCADOp", {"op": name, **freeze_refs(ctx, p)})
                ctx.created.append(obj.Name)
            else:
                raise OpError("UNKNOWN_OP", f"Unknown part operation {name!r}", hint=f"Operations: {sorted(OPS) + sorted(META_OPS)}")
            if obj is not None:
                if name in OPS and p.get("tag"):
                    clash = [o.Name for o in doc.Objects if getattr(o, "AgentCADTag", None) == p["tag"] and o is not obj]
                    if clash:
                        raise OpError("TAG_EXISTS", f"A feature tagged {p['tag']!r} already exists", entities=clash)
                    tag(obj, p["tag"])
                ctx.refs[i] = obj.Name
                ctx.op_of[obj.Name] = i
            regenerate(ctx)
            bad = broken(doc)
            if bad:
                first = bad[0]
                raise OpError("FEATURE_FAILED", f"{first['feature']}: {first['message'] or 'recompute failed'}",
                              category="geometry", hint=hint_for(first["message"]),
                              entities=[b["feature"] for b in bad], details={"broken": bad})
            r = {"index": i, "op": name}
            if obj is not None:
                r["feature"] = obj.Name
                if getattr(obj, "AgentCADTag", ""):
                    r["tag"] = obj.AgentCADTag
            r.update(info or {})
            results.append(r)
        except OpError as exc:
            exc.op_index, exc.op = i, name
            raise
        except Exception as exc:  # FreeCAD raises plain exceptions for bad values
            e = OpError("FREECAD_ERROR", f"{type(exc).__name__}: {exc}", category="geometry",
                        details={"traceback": traceback.format_exc(limit=4)})
            e.op_index, e.op = i, name
            raise e
    return ctx, results


def action_apply(job):
    PROGRESS["file"] = job.get("progress")
    doc = open_or_new(job)
    ctx, results = run_ops(doc, job.get("ops") or [])
    report_progress(phase="checking")
    out = {"results": results, "changes": {"added": ctx.created, "modified": ctx.modified, "deleted": ctx.deleted}}
    if not job.get("output"):
        out["summary"] = summary(doc)
        return out
    doc.saveAs(job["output"])
    App.closeDocument(doc.Name)
    if job.get("validate", True):  # judge the file as saved: a fresh document read back from disk
        out.update(action_validate({"input": job["output"], "requirements": job.get("requirements")}))
    return out


def action_summary(job):
    doc = App.openDocument(job["input"])
    if job.get("recompute", True):
        doc.recompute()
    return {"summary": summary(doc, detail=bool(job.get("detail")))}


def action_validate(job):
    doc = App.openDocument(job["input"])
    doc.recompute()
    issues = check_doc(doc)
    reqs, warns = check_requirements(doc, job.get("requirements"))
    s = summary(doc)
    body = next((b for b in s["bodies"] if b["shape"] and b["shape"]["volume"] > 0), None)
    return {"report": {"readable": True, "passed": not any(i["severity"] == "error" for i in issues)
                       and all(r.get("passed") for r in reqs),
                       "issues": issues, "requirements": reqs, "warnings": warns,
                       "shape": body["shape"] if body else None,
                       "features": len(body["features"]) if body else 0, "parameters": s["parameters"]}}


def action_topology(job):
    doc = App.openDocument(job["input"])
    doc.recompute()
    ctx = Ctx(doc)
    f = job.get("filter") or {}
    if f.get("feature"):
        obj = ctx.obj(f["feature"], "filter.feature")
    else:
        obj = ctx.body(None, create=False)
    sh = obj.Shape
    kind = f.get("kind", "faces")
    sel = f.get("selector")
    if kind == "edges":
        names = select_edges(sh, sel, "filter.selector") if sel else [f"Edge{i + 1}" for i, e in enumerate(sh.Edges)
                                                                    if not _is_seam(sh, e)]
        items = [describe_edge(sh, int(n[4:]) - 1, sh.getElement(n)) for n in names]
    elif kind == "faces":
        names = select_faces(sh, sel, "filter.selector") if sel else [f"Face{i + 1}" for i in range(len(sh.Faces))]
        items = [describe_face(sh, int(n[4:]) - 1, sh.getElement(n)) for n in names]
    else:
        raise OpError("BAD_VALUE", "filter.kind must be 'faces', 'edges' or 'features'")
    return {"of": obj.Name, "kind": kind, "items": items}


def action_export(job):
    doc = App.openDocument(job["input"])
    doc.recompute()
    fmt = job["format"]
    body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()), None)
    if body is None:
        raise OpError("NO_SOLID", "Nothing to export: the part has no solid", category="geometry")
    sh = body.Shape
    if len(sh.Solids) != 1 or not sh.isValid() or broken(doc):
        # a scorer such as BenchCAD voxelises whatever it reads: a broken export would be scored, not refused
        raise OpError("NOT_EXPORTABLE", f"{body.Name} is not one valid solid ({len(sh.Solids)} solids, "
                      f"valid={sh.isValid()}, failed features: {[b['feature'] for b in broken(doc)]})",
                      category="geometry", hint="Fix the part first (validate_drawing lists the issues)",
                      details={"shape": shape_summary(sh)})
    out = job["output"]
    if fmt == "step":
        import Import
        Import.export([body], out)
    elif fmt == "iges":
        body.Shape.exportIges(out)
    elif fmt == "brep":
        body.Shape.exportBrep(out)
    elif fmt in ("stl", "obj"):
        import Mesh
        import MeshPart
        m = MeshPart.meshFromShape(Shape=body.Shape, LinearDeflection=float(job.get("deflection") or 0.05),
                                   AngularDeflection=0.3, Relative=False)
        Mesh.Mesh(m).write(out) if fmt == "stl" else m.write(out)
    else:
        raise OpError("UNSUPPORTED_FORMAT", f"Unsupported 3D export format {fmt!r}")
    res = {"format": fmt, "shape": shape_summary(sh)}
    if fmt in ("step", "iges", "brep"):
        res["readback"] = readback(out, sh)
        if not res["readback"]["matches"]:
            raise OpError("EXPORT_MISMATCH", f"The written {fmt.upper()} reads back differently from the part",
                          category="geometry", details=res)
    return res


def readback(path, ref=None):
    """Read an exported B-rep file back with Part.read and compare it with the part's shape.

    IGES comes back as faces, never a solid (also when written in BRep mode, probed on 1.1.4), so for IGES the
    solid count is not compared; validity, volume (OCC integrates the closed faces) and size still are."""
    got = Part.read(path)
    out = {k: v for k, v in shape_summary(got).items() if k in ("valid", "solids", "volume", "size", "bbox")}
    iges = Path(path).suffix.lower() in (".iges", ".igs")
    if iges:
        out["note"] = "IGES stores faces, not solids: compared by volume and size"
    if ref is not None:
        out["matches"] = bool(out["valid"] and (iges or out["solids"] == len(ref.Solids))
                              and abs(got.Volume - ref.Volume) <= 1e-6 * max(1.0, abs(ref.Volume))
                              and all(abs(a - b) <= 1e-4 for a, b in zip(out["size"], shape_summary(ref)["size"])))
    return out


def action_read_shape(job):
    """Summary of a STEP/IGES/BREP file (an export, or a reference part), independent of any FCStd."""
    return {"shape": readback(job["input"])}


# --- preview rendering -----------------------------------------------------------------------------------------
# FreeCAD without its GUI cannot render offscreen, so previews are rasterised here: OCC tessellation, parallel
# projection, a z-buffer in numpy, flat shading from a light near the viewer, and the B-rep edges drawn on top.

NAMED_VIEWS = {"iso": (1, -1, 1), "front": (0, -1, 0), "back": (0, 1, 0), "right": (1, 0, 0), "left": (-1, 0, 0),
               "top": (0, 0, 1), "bottom": (0, 0, -1), "iso_back": (-1, 1, 1), "iso_bottom": (1, -1, -1)}
FACE_RGB = (176, 188, 206)
EDGE_RGB = (35, 38, 45)


def _view(v, name):
    if isinstance(v, str):
        if v not in NAMED_VIEWS:
            raise OpError("BAD_VIEW", f"{name}: unknown view {v!r}", hint=f"Views: {sorted(NAMED_VIEWS)} or [x, y, z]")
        return v, V(*NAMED_VIEWS[v])
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, (int, float)) for c in v):
        d = V(*[float(c) for c in v])
        if d.Length < TOL:
            raise OpError("BAD_VIEW", f"{name}: zero direction")
        return "[" + ",".join(f"{c:g}" for c in v) + "]", d
    raise OpError("BAD_VIEW", f"{name}: expected a view name or [x, y, z] (direction from the part to the camera)")


def _camera(d):
    import numpy as np
    d = np.array([d.x, d.y, d.z], float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.99 else np.array([0.0, 1.0, 0.0])
    right = np.cross(up, d)
    right /= np.linalg.norm(right)
    return right, np.cross(d, right), d  # screen x, screen y, towards the camera


def render_view(sh, d, size, fit, ss=2):
    import numpy as np
    right, up, fwd = _camera(d)
    bb = sh.BoundBox
    corners = np.array([[x, y, z] for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)])
    centre = corners.mean(axis=0)
    if fit == "uniform":  # the same scale in every view: the bounding box's diagonal spans the frame
        span = float(np.linalg.norm(corners.max(axis=0) - corners.min(axis=0)))
    else:  # this view's projection of the bounding box fills the frame
        q = (corners - centre) @ np.stack([right, up]).T
        span = float(max(np.ptp(q[:, 0]), np.ptp(q[:, 1])))
    n = size * ss
    k = n * 0.9 / max(span, 1e-9)

    def project(P):
        R = P - centre
        return R @ right * k + n / 2, n / 2 - R @ up * k, R @ fwd

    pts, tris = sh.tessellate(max(span, 1e-9) / 400)
    P = np.array([[p.x, p.y, p.z] for p in pts], float)
    T = np.array(tris, int).reshape(-1, 3)
    X, Y, Z = project(P)
    img = np.empty((n, n, 3), float)
    img[:] = 255
    zb = np.full((n, n), -np.inf)
    light = fwd + 0.35 * up + 0.25 * right
    light /= np.linalg.norm(light)
    nrm = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    ln = np.linalg.norm(nrm, axis=1)
    nrm = nrm / np.where(ln > 0, ln, 1)[:, None]
    shade = 0.28 + 0.72 * np.abs(nrm @ light)
    base = np.array(FACE_RGB, float)
    for t, sv in zip(T, shade):
        hit = _scanline(X[t], Y[t], Z[t], n)
        if hit is None:
            continue
        rows, cols, zz = hit
        win = zz > zb[rows, cols]
        zb[rows[win], cols[win]] = zz[win]
        img[rows[win], cols[win]] = base * sv
    eps = 2.5 * ss / k  # depth slack: an edge on a visible face is drawn, one behind the solid is not
    for e in sh.Edges:
        # a cylinder's parametric seam is not an edge anyone would draw, nor a sphere's or cone's pole
        if e.Degenerated or _is_seam(sh, e):
            continue
        pe = np.array([[q.x, q.y, q.z] for q in e.discretize(Deflection=max(span, 1e-9) / 800)], float)
        if len(pe) < 2:
            continue
        ex, ey, ez = project(pe)
        for i in range(len(pe) - 1):
            m = int(max(abs(ex[i + 1] - ex[i]), abs(ey[i + 1] - ey[i])) * 2) + 2
            tt = np.linspace(0, 1, m)
            lx = np.round(ex[i] + (ex[i + 1] - ex[i]) * tt - 0.5).astype(int)
            ly = np.round(ey[i] + (ey[i + 1] - ey[i]) * tt - 0.5).astype(int)
            lz = ez[i] + (ez[i + 1] - ez[i]) * tt
            ok = (lx >= 0) & (lx < n) & (ly >= 0) & (ly < n)
            lx, ly, lz = lx[ok], ly[ok], lz[ok]
            vis = lz >= zb[ly, lx] - eps
            for ox in range(ss):  # line width: one output pixel
                for oy in range(ss):
                    xx, yy = np.clip(lx[vis] + ox - ss // 2, 0, n - 1), np.clip(ly[vis] + oy - ss // 2, 0, n - 1)
                    img[yy, xx] = EDGE_RGB
    return img


def _scanline(x, y, z, n):
    """Pixels (row, column, depth) whose centres a screen-space triangle covers. Each row's covered span comes
    from the triangle's edges, so the cost follows the covered area, not the bounding box: tessellated planar
    faces are long thin triangles whose boxes are mostly empty."""
    import numpy as np
    area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
    if abs(area) < 1e-12:
        return None
    r0, r1 = max(int(np.ceil(y.min() - 0.5)), 0), min(int(np.floor(y.max() - 0.5)), n - 1)
    if r0 > r1:
        return None
    rr = np.arange(r0, r1 + 1)
    yc = rr + 0.5
    lo = np.full(len(rr), np.inf)
    hi = np.full(len(rr), -np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if y[i] == y[j]:
            continue
        m = (yc >= min(y[i], y[j])) & (yc <= max(y[i], y[j]))
        xi = x[i] + (yc[m] - y[i]) * (x[j] - x[i]) / (y[j] - y[i])
        lo[m] = np.minimum(lo[m], xi)
        hi[m] = np.maximum(hi[m], xi)
    ok = lo <= hi
    c0 = np.clip(np.ceil(lo[ok] - 0.5), 0, n).astype(int)
    c1 = np.clip(np.floor(hi[ok] - 0.5), -1, n - 1).astype(int)
    cnt = np.maximum(c1 - c0 + 1, 0)
    total = int(cnt.sum())
    if not total:
        return None
    rows = np.repeat(rr[ok], cnt)
    cols = np.repeat(c0, cnt) + np.arange(total) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    # depth is linear in screen x and y over the triangle (parallel projection)
    A = np.array([[x[0], y[0], 1.0], [x[1], y[1], 1.0], [x[2], y[2], 1.0]])
    a, b, c = np.linalg.solve(A, z)
    return rows, cols, a * (cols + 0.5) + b * (rows + 0.5) + c


def _downsample(img, ss):
    n = img.shape[0] // ss
    return img.reshape(n, ss, n, ss, 3).mean(axis=(1, 3))


def _save_png(arr, path, labels=None, cell=512):
    import numpy as np
    a = np.clip(arr, 0, 255).astype("uint8")
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # plain interpreters (FREECAD_LIB): write the PNG by hand, without labels
        import struct
        import zlib
        h, w = a.shape[:2]
        raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                               + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
        return
    im = Image.fromarray(a, "RGB")
    if labels:
        dr = ImageDraw.Draw(im)
        try:  # scalable default font (Pillow >= 10.1): about 1/22 of a cell
            from PIL import ImageFont
            font = ImageFont.load_default(size=max(12, cell // 22))
        except (TypeError, OSError, ImportError):
            font = None
        for (x, y), text in labels:
            dr.text((x + cell // 64 + 4, y + cell // 96 + 2), text, fill=(60, 60, 60), font=font)
    im.save(path)


def action_render(job):
    import numpy as np
    doc = App.openDocument(job["input"])
    doc.recompute()
    body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()), None)
    if body is None:
        raise OpError("NO_SOLID", "Nothing to render: the part has no solid", category="geometry")
    views = job.get("views") or ["iso"]
    if not isinstance(views, list) or not 1 <= len(views) <= 9:
        raise OpError("BAD_VIEW", "views: a list of 1 to 9 views")
    views = [_view(v, f"views[{i}]") for i, v in enumerate(views)]
    # default: 512 px for one view; 256 px per view in a grid, so a 2x2 sheet is 512 x 512, about the size of a
    # reference image an agent compares it with (a larger sheet costs more image tokens on every later turn)
    size = int(job.get("size") or (512 if len(views) == 1 else 256))
    if not 64 <= size <= 2048:
        raise OpError("OUT_OF_RANGE", "image_size must be 64..2048 pixels")
    fit = job.get("fit") or "view"
    if fit not in ("view", "uniform"):
        raise OpError("BAD_VALUE", "fit must be 'view' or 'uniform'")
    imgs = [_downsample(render_view(body.Shape, d, size, fit), 2) for _, d in views]
    names = [nm for nm, _ in views]
    if len(imgs) > 1:  # several views: one sheet, two or three per row, each cell labelled
        cols = 2 if len(imgs) <= 4 else 3
        rows = -(-len(imgs) // cols)
        sheet = np.full((rows * size, cols * size, 3), 255.0)
        labels = []
        for i, im in enumerate(imgs):
            r, c = divmod(i, cols)
            sheet[r * size:(r + 1) * size, c * size:(c + 1) * size] = im
            labels.append(((c * size, r * size), names[i]))
        sheet[:, [c * size for c in range(1, cols)]] = 200  # cell borders
        sheet[[r * size for r in range(1, rows)], :] = 200
        _save_png(sheet, job["output"], labels, size)
        grid = [rows, cols]
    else:
        _save_png(imgs[0], job["output"])
        grid = [1, 1]
    return {"views": names, "grid": grid, "cell_size": size, "fit": fit, "shape": shape_summary(body.Shape)}


def action_mesh(job):
    """Triangles and B-rep edges of the body for the live viewer (viewer.py), written as JSON to ``output``.
    Like previews, it does not require an exportable part: a broken body is shown as it is."""
    doc = App.openDocument(job["input"])
    doc.recompute()
    body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()), None)
    if body is None:
        raise OpError("NO_SOLID", "Nothing to show: the part has no solid", category="geometry")
    sh = body.Shape
    span = max(sh.BoundBox.DiagonalLength, 1e-9)
    pts, tris = sh.tessellate(span / 600)
    edges = []
    for e in sh.Edges:
        if not (e.Degenerated or _is_seam(sh, e)):  # no seams, no sphere or cone poles
            edges.append([round(c, 5) for q in e.discretize(Deflection=span / 1000) for c in (q.x, q.y, q.z)])
    data = {"positions": [round(c, 5) for p in pts for c in (p.x, p.y, p.z)],
            "indices": [i for t in tris for i in t], "edges": edges}
    Path(job["output"]).write_text(json.dumps(data, separators=(",", ":")), "utf-8")
    return {"triangles": len(tris), "edges": len(edges), "shape": shape_summary(sh), "broken": broken(doc)}


ACTIONS = {"apply": action_apply, "summary": action_summary, "validate": action_validate,
           "read_shape": action_read_shape, "render": action_render, "mesh": action_mesh,
           "topology": action_topology, "export": action_export}


def main():
    # bundled python: the job folder is argv[1]; freecadcmd passes no script arguments, so it comes by environment
    job_dir = Path(sys.argv[1] if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir() else os.environ["AGENTCAD_FC_JOB"])
    job = json.loads((job_dir / "job.json").read_text("utf-8"))
    try:
        res = {"ok": True, **ACTIONS[job["action"]](job)}
    except OpError as exc:
        res = {"ok": False, "error": exc.to_dict()}
    except Exception as exc:
        res = {"ok": False, "error": {"code": "FREECAD_ERROR", "category": "internal",
                                      "message": f"{type(exc).__name__}: {exc}",
                                      "details": {"traceback": traceback.format_exc(limit=6)}}}
    (job_dir / "result.json").write_text(json.dumps(res, default=str), "utf-8")


if __name__ == "__main__" or os.environ.get("AGENTCAD_FC_JOB"):
    main()
