"""FreeCAD side of the live viewer's 3D view. Runs inside FreeCAD's own Python (``python.exe -I _fc_view.py <job>``),
never imported by agentcad: it may only import FreeCAD modules, numpy and the standard library.

AgentCAD does not build 3D parts; agents write the model with their own code (CadQuery, build123d, FreeCAD) and save
it in the workspace. This only reads such a file (.FCStd, .step/.stp, .brep, .stl) and returns what the viewer shows:
triangles and edges for three.js, a shaded picture, or a few numbers to compare two versions.

The job folder holds ``job.json`` ({"action", "input", "output", ...}); the result goes to ``result.json`` as
{"ok": true, ...} or {"ok": false, "error": {code, category, message, hint}}.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

for _lib in filter(None, os.environ.get("AGENTCAD_FREECAD_LIB", "").split(os.pathsep)):
    sys.path.insert(0, _lib)  # FREECAD_LIB installs: FreeCAD's module is imported by a plain interpreter

import FreeCAD as App  # noqa: N813, E402
import Part  # noqa: E402

FACE_RGB = (176, 188, 206)
EDGE_RGB = (35, 38, 45)
ISO = (1.0, -1.0, 1.0)
# objects that are construction aids, not the part: sketches, datums, origins
AIDS = ("Sketcher::", "App::Origin", "App::Plane", "App::Line", "App::Point", "PartDesign::Plane",
        "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem", "Part::Part2DObject")


class ViewError(Exception):
    def __init__(self, code, message, category="geometry", hint=None):
        super().__init__(message)
        self.code, self.message, self.category, self.hint = code, message, category, hint

    def to_dict(self):
        d = {"code": self.code, "category": self.category, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


# --- loading -------------------------------------------------------------------------------------------------------
def _document_shape(path):
    """The part in a FreeCAD document: every Body, else every visible top-level shape that is not a construction
    aid (a Part workbench model, or a script's result added with Part.show)."""
    doc = App.openDocument(path)
    doc.recompute()
    objs = [o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
    if not objs:
        objs = [o for o in doc.Objects if hasattr(o, "Shape") and not o.Shape.isNull()
                and not o.TypeId.startswith(AIDS) and not any(hasattr(p, "Shape") for p in o.InList)
                and getattr(o, "Visibility", True)]
    shapes = [o.Shape for o in objs if o.Shape.Faces]
    if not shapes:
        raise ViewError("NO_SOLID", "Nothing to show: the document has no solid or surface",
                        hint="Save the part's shape in the document (a Body, or Part.show(shape)), or export a STEP")
    return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)


def load(path):
    """("brep", shape) or ("mesh", (points, triangles)) for the file at ``path``."""
    ext = Path(path).suffix.lower()
    if ext == ".fcstd":
        return "brep", _document_shape(path)
    if ext in (".step", ".stp", ".brep", ".brp", ".iges", ".igs"):
        sh = Part.Shape()
        sh.read(path)
        if sh.isNull() or not sh.Faces:
            raise ViewError("NO_SOLID", "Nothing to show: the file holds no surface")
        return "brep", sh
    if ext == ".stl":
        import Mesh
        m = Mesh.Mesh(path)
        if not m.CountFacets:
            raise ViewError("NO_SOLID", "Nothing to show: the STL has no triangles")
        pts, tris = m.Topology
        return "mesh", ([(p.x, p.y, p.z) for p in pts], [tuple(t) for t in tris])
    raise ViewError("BAD_FILE", f"Not a 3D file the viewer reads: {ext}", category="input")


def tight_box(sh):
    """Shape.BoundBox follows B-spline control points and can be far too wide; this is the geometry's own box."""
    try:
        bb = sh.optimalBoundingBox(False, False)
    except Exception:  # nothing to bound (a degenerate shape): the plain box
        bb = None
    return bb if bb is not None and bb.isValid() else sh.BoundBox


def tessellate(sh, deflection):
    """Points and triangles of every face. Shape.tessellate silently leaves out a face OCC's mesher failed on, so
    faces are collected one by one and a face left without triangles is meshed again on its own, finer."""
    sh.tessellate(deflection)  # one pass over the whole shape: neighbouring faces share their edges' points
    pts, tris, missing = [], [], []
    for i, f in enumerate(sh.Faces, 1):
        p, t = f.tessellate(deflection)
        if not t:
            p, t = f.copy().tessellate(deflection / 4)  # a copy carries no triangulation: meshed from scratch
        if not t:
            missing.append(f"Face{i}")
        base = len(pts)
        pts += [(q.x, q.y, q.z) for q in p]
        tris += [(a + base, b + base, c + base) for a, b, c in t]
    return pts, tris, missing


def _is_seam(shape, e):
    """A cylinder's or cone's parametric seam, which nobody would draw as an edge."""
    fs = shape.ancestorsOfType(e, Part.Face)
    if len(fs) == 2 and fs[0].isSame(fs[1]):
        return True
    return len(fs) < 2 and isinstance(getattr(e, "Curve", None), Part.Line) and \
        any(type(f.Surface).__name__ in ("Cylinder", "Cone") for f in fs)


def geometry(kind, data):
    """(points, triangles, edge polylines, faces left out, span) for either kind of file."""
    if kind == "mesh":
        pts, tris = data
        xs, ys, zs = zip(*pts)
        span = max(((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2) ** 0.5, 1e-9)
        return pts, tris, [], [], span
    sh = data
    span = max(tight_box(sh).DiagonalLength, 1e-9)
    pts, tris, missing = tessellate(sh, span / 600)
    edges = []
    for e in sh.Edges:
        if not (e.Degenerated or _is_seam(sh, e)):
            edges.append([(q.x, q.y, q.z) for q in e.discretize(Deflection=span / 1000)])
    return pts, tris, edges, missing, span


# --- actions -------------------------------------------------------------------------------------------------------
def action_mesh(job):
    """Triangles and edges as JSON in ``output``, for three.js in the viewer page."""
    pts, tris, edges, missing, _ = geometry(*load(job["input"]))
    data = {"positions": [round(c, 5) for p in pts for c in p], "indices": [i for t in tris for i in t],
            "edges": [[round(c, 5) for q in line for c in q] for line in edges], "missing_faces": missing}
    Path(job["output"]).write_text(json.dumps(data, separators=(",", ":")), "utf-8")
    return {"triangles": len(tris), "edges": len(edges), "missing_faces": missing}


def action_summary(job):
    """A few numbers that show what changed between two versions: size, volume, area and counts."""
    kind, data = load(job["input"])
    if kind == "mesh":
        pts, tris = data
        xs, ys, zs = zip(*pts)
        return {"summary": {"size": [round(max(a) - min(a), 3) for a in (xs, ys, zs)], "triangles": len(tris)}}
    sh = data
    bb = tight_box(sh)
    out = {"size": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)],
           "solids": len(sh.Solids), "faces": len(sh.Faces)}
    if sh.Solids:
        out["volume"] = round(sum(s.Volume for s in sh.Solids), 3)
    out["area"] = round(sh.Area, 3)
    return {"summary": out}


def _camera(d):
    import numpy as np
    d = np.array(d, float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.99 else np.array([0.0, 1.0, 0.0])
    right = np.cross(up, d)
    right /= np.linalg.norm(right)
    return right, np.cross(d, right), d  # screen x, screen y, towards the camera


def _scanline(x, y, z, n):
    """Pixels (row, column, depth) whose centres a screen-space triangle covers, row by row."""
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
    A = np.array([[x[0], y[0], 1.0], [x[1], y[1], 1.0], [x[2], y[2], 1.0]])
    a, b, c = np.linalg.solve(A, z)  # depth is linear in screen x and y over the triangle (parallel projection)
    return rows, cols, a * (cols + 0.5) + b * (rows + 0.5) + c


def render(pts, tris, edges, size, direction=ISO, ss=2):
    """A shaded parallel view (z-buffer in numpy, flat shading, edges on top), ``size`` pixels square."""
    import numpy as np
    right, up, fwd = _camera(direction)
    P = np.array(pts, float)
    T = np.array(tris, int).reshape(-1, 3)
    centre = (P.min(axis=0) + P.max(axis=0)) / 2
    q = (P - centre) @ np.stack([right, up]).T
    span = float(max(np.ptp(q[:, 0]), np.ptp(q[:, 1]), 1e-9))
    n = size * ss
    k = n * 0.9 / span

    def project(Q):
        R = Q - centre
        return R @ right * k + n / 2, n / 2 - R @ up * k, R @ fwd

    X, Y, Z = project(P)
    img = np.full((n, n, 3), 255.0)
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
    for line in edges:
        pe = np.array(line, float)
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
            img[ly[vis], lx[vis]] = EDGE_RGB
    return img.reshape(size, ss, size, ss, 3).mean(axis=(1, 3))


def _save_png(arr, path):
    import struct
    import zlib
    import numpy as np
    a = np.clip(arr, 0, 255).astype("uint8")
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def action_render(job):
    """One shaded iso picture in ``output`` (PNG): the file list's thumbnail, and the page's view without WebGL."""
    size = int(job.get("size") or 512)
    if not 64 <= size <= 2048:
        raise ViewError("OUT_OF_RANGE", "size must be 64..2048 pixels", category="input")
    pts, tris, edges, _, _ = geometry(*load(job["input"]))
    if not tris:
        raise ViewError("NO_SOLID", "Nothing to show: no triangles")
    _save_png(render(pts, tris, edges, size), job["output"])
    return {"size": size}


ACTIONS = {"mesh": action_mesh, "summary": action_summary, "render": action_render}


def main():
    # bundled python: the job folder is argv[1]; freecadcmd passes no script arguments, so it comes by environment
    job_dir = Path(sys.argv[1] if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir() else os.environ["AGENTCAD_FC_JOB"])
    job = json.loads((job_dir / "job.json").read_text("utf-8"))
    try:
        res = {"ok": True, **ACTIONS[job["action"]](job)}
    except ViewError as exc:
        res = {"ok": False, "error": exc.to_dict()}
    except Exception as exc:
        res = {"ok": False, "error": {"code": "FREECAD_ERROR", "category": "internal",
                                      "message": f"{type(exc).__name__}: {exc}",
                                      "details": {"traceback": traceback.format_exc(limit=6)}}}
    (job_dir / "result.json").write_text(json.dumps(res, default=str), "utf-8")


if __name__ == "__main__" or os.environ.get("AGENTCAD_FC_JOB"):
    main()
