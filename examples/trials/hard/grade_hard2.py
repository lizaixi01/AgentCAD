"""Neutral graders for H4-H6 (plain ezdxf), used by grade_hard.py. Each returns {"ok", "checks", "fails"}."""
from __future__ import annotations

import math
import re
import tempfile
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox

from bases2 import (H4_DIMS, H4_HOLES, H4_JUNK_LAYERS, H4_LAYERS, H4_TEXTS, H5_HOLE_R, H5_HOLES, H5_OUTLINE,
                    H5_SLOT, make_h6_base)
from grade import Drawing, check

NUM = re.compile(r"\d+(?:\.\d+)?")


def _result(checks: list[dict]) -> dict:
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "fails": [c["check"] for c in checks if not c["ok"]]}


def _load(ws: Path):
    p = ws / "part.dxf"
    if not p.is_file():
        return None, {"ok": False, "error": "part.dxf missing", "checks": [], "fails": ["part.dxf missing"]}
    try:
        return ezdxf.readfile(p), None
    except Exception as exc:
        return None, {"ok": False, "error": f"unreadable: {exc}", "checks": [], "fails": ["unreadable"]}


def _measure(d) -> float | None:
    try:
        m = d.get_measurement()
        m = None if hasattr(m, "x") else float(m)
    except Exception:
        return None
    if m is not None and (d.dimtype & 0x0F) in (2, 5):
        m = math.degrees(m)
    return m


def _texts(layout) -> list[tuple[str, tuple[float, float]]]:
    out = []
    for e in layout:
        t = e.dxftype()
        try:
            if t in ("TEXT", "MTEXT"):
                out.append((e.plain_text() if t == "MTEXT" else e.dxf.text, (e.dxf.insert.x, e.dxf.insert.y)))
            elif t == "INSERT":
                for a in e.attribs:
                    out.append((a.dxf.text, (a.dxf.insert.x, a.dxf.insert.y)))
                for v in e.virtual_entities():
                    if v.dxftype() in ("TEXT", "MTEXT"):
                        out.append((v.plain_text() if v.dxftype() == "MTEXT" else v.dxf.text,
                                    (v.dxf.insert.x, v.dxf.insert.y)))
            elif t == "TABLE" or t == "ACAD_TABLE":
                for v in e.virtual_entities():
                    if v.dxftype() in ("TEXT", "MTEXT"):
                        out.append((v.plain_text() if v.dxftype() == "MTEXT" else v.dxf.text,
                                    (v.dxf.insert.x, v.dxf.insert.y)))
        except Exception:
            continue
    return out


# --- H4 ---------------------------------------------------------------------------------------------
def grade_h4(ws: Path) -> dict:
    doc, err = _load(ws)
    if err:
        return err
    msp = doc.modelspace()
    r = []
    lay_ok = []
    for name, (color, lt, lw) in H4_LAYERS.items():
        L = doc.layers.get(name) if name in doc.layers else None
        lay_ok.append(L is not None and L.color == color and (L.dxf.get("linetype") or "").upper() == lt
                      and L.dxf.get("lineweight") == lw)
    r.append(check(all(lay_ok), "standard layers with colour/linetype/lineweight", "layers"))
    r.append(check(not any(n in doc.layers for n in H4_JUNK_LAYERS), "empty junk layers deleted", "layers"))
    ents = list(msp)
    bylayer = all(e.dxf.get("color", 256) == 256 and (e.dxf.get("linetype") or "BYLAYER").upper() == "BYLAYER"
                  and e.dxf.get("lineweight", -1) == -1 for e in ents)
    r.append(check(bylayer, "every object colour/linetype/lineweight ByLayer", "bylayer"))
    by = Counter(e.dxftype() for e in ents)
    polys = [e for e in ents if e.dxftype() == "LWPOLYLINE"]
    r.append(check(len(polys) == 1 and polys[0].dxf.layer == "OUTLINE" and polys[0].closed
                   and sorted((round(x), round(y)) for x, y in polys[0].get_points("xy"))
                   == [(0, 0), (0, 100), (200, 0), (200, 100)], "outline polyline kept, on OUTLINE", "objects"))
    circles = [e for e in ents if e.dxftype() == "CIRCLE"]
    want = sorted((c, r_) for c, r_ in H4_HOLES)
    got = sorted(((round(e.dxf.center.x, 3), round(e.dxf.center.y, 3)), round(e.dxf.radius, 3)) for e in circles)
    r.append(check(got == [((float(x), float(y)), float(rr)) for (x, y), rr in want]
                   and all(e.dxf.layer == "OUTLINE" for e in circles), "5 holes (duplicate removed), on OUTLINE",
                   "objects"))
    lines = [e for e in ents if e.dxftype() == "LINE"]
    zero = [e for e in lines if (e.dxf.end - e.dxf.start).magnitude < 1e-6]
    r.append(check(len(lines) == 10 and not zero and all(e.dxf.layer == "CENTER" for e in lines),
                   "10 centre lines on CENTER; edge duplicates and zero-length lines removed", "objects"))
    dims = [e for e in ents if e.dxftype() == "DIMENSION"]
    vals = sorted(round(_measure(d) or -1, 2) for d in dims)
    r.append(check(vals == sorted(H4_DIMS) and all(d.dxf.layer == "DIM" for d in dims),
                   "4 dimensions kept (200/100/160/Ø40), on DIM", "objects"))
    texts = [e for e in ents if e.dxftype() in ("TEXT", "MTEXT")]
    tx = " ".join(e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text for e in texts)
    r.append(check(len(texts) == 2 and all(t in tx for t in H4_TEXTS) and "C1" in tx
                   and all(e.dxf.layer == "TEXT" for e in texts), "2 texts kept, on TEXT", "objects"))
    r.append(check(set(by) <= {"LWPOLYLINE", "CIRCLE", "LINE", "DIMENSION", "TEXT", "MTEXT"},
                   "no other objects added", "objects"))
    return _result(r)


# --- H5 ---------------------------------------------------------------------------------------------
def _orient(d) -> str:
    kind = d.dimtype & 0x0F
    if kind == 0:
        a = d.dxf.get("angle", 0) % 180
    elif kind == 1:
        v = d.dxf.defpoint3 - d.dxf.defpoint2
        a = math.degrees(math.atan2(v.y, v.x)) % 180
    else:
        return {2: "ang", 5: "ang", 3: "dia", 4: "rad"}.get(kind, "other")
    return "H" if min(a, 180 - a) < 1 else "V" if abs(a - 90) < 1 else "skew"


def grade_h5(ws: Path) -> dict:
    doc, err = _load(ws)
    if err:
        return err
    g = Drawing(ws / "part.dxf")
    r = []
    pts = H5_OUTLINE + [H5_OUTLINE[0]]
    mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:])]
    (x1, y), (x2, _), sr = H5_SLOT
    geom = (all(g.on(p) for p in mids) and all(g.circle(c, H5_HOLE_R) for c in H5_HOLES)
            and all(g.on(p) for p in ((x1 - sr, y), (x2 + sr, y), ((x1 + x2) / 2, y - sr), ((x1 + x2) / 2, y + sr))))
    r.append(check(geom and g.text("SB-160"), "part geometry and text unchanged", "preserve"))
    dims = list(doc.modelspace().query("DIMENSION"))
    info = []
    for d in dims:
        m = _measure(d)
        info.append({"o": _orient(d), "v": None if m is None else round(m, 2), "text": d.dxf.get("text", "") or "",
                     "layer": d.dxf.layer, "e": d})
    r.append(check(dims and all(i["layer"] == "DIM" for i in info), "all dimensions are DIMENSION objects on DIM",
                   "dimension"))
    H = {i["v"] for i in info if i["o"] == "H"}
    V = {i["v"] for i in info if i["o"] == "V"}
    dia = {i["v"] for i in info if i["o"] == "dia"}
    rad = {i["v"] for i in info if i["o"] == "rad"}
    alltext = " ".join(i["text"] for i in info) + " " + " ".join(t for t, _ in g.texts)
    r.append(check(160 in H, "total length 160", "required"))
    r.append(check(90 in V, "total height 90", "required"))
    r.append(check(14 in dia, "hole diameter Ø14", "required"))
    r.append(check((110 in H or 135 in H) and (25 in H or 135 in H), "hole spacing / x position", "required"))
    r.append(check(25 in V or 65 in V, "hole y position", "required"))
    r.append(check(12 in V or 6 in rad, "slot width 12 (or R6)", "required"))
    r.append(check(40 in H or 28 in H, "slot length 40 (or centre distance 28)", "required"))
    r.append(check(bool(H & {60, 66, 80, 94, 100}), "slot x position", "required"))
    r.append(check(bool(V & {62, 56, 68, 28, 22, 34}), "slot y position", "required"))
    r.append(check(10 in H or 10 in V or re.search(r"C\s*10|10\s*[×xX*]\s*45", alltext) is not None,
                   "chamfer 10 (C10 / 10×45°)", "required"))
    # overridden text must show the measured value
    bad = []
    for i in info:
        t = i["text"]
        if t and "<>" not in t and t.strip() != "" and i["v"] is not None:
            nums = [float(n) for n in NUM.findall(t)]
            if not any(abs(n - i["v"]) < 0.01 for n in nums):
                bad.append(t)
    r.append(check(not bad, "dimension text matches the geometry" + (f" (bad: {bad})" if bad else ""), "dimension"))
    seen, dup = set(), []
    for i in info:
        e = i["e"]
        key = (i["o"], i["v"], tuple(sorted((round(p.x, 1), round(p.y, 1)) for p in
                                            (e.dxf.get("defpoint2"), e.dxf.get("defpoint3")) if p is not None)))
        if key in seen:
            dup.append(i["v"])
        seen.add(key)
    r.append(check(not dup, "no duplicated dimensions" + (f" ({dup})" if dup else ""), "dimension"))
    on_lines = []
    for i in info:
        p = i["e"].dxf.get("text_midpoint")
        if p is not None and g._near(g.vis, (p.x, p.y), 1.2):
            on_lines.append(i["v"])
    r.append(check(not on_lines, "dimension text clear of part lines" + (f" ({on_lines})" if on_lines else ""),
                   "layout"))
    out = _result(r)
    out["dim_count"] = len(dims)
    return out


# --- H6 ---------------------------------------------------------------------------------------------
def _model_signature(doc) -> tuple:
    msp = doc.modelspace()
    hist = Counter(e.dxftype() for e in msp)
    vals = sorted(round(_measure(d) or -1, 2) for d in msp.query("DIMENSION"))
    return tuple(sorted(hist.items())), tuple(vals)


def _segs_near(layout, p, tol=0.5) -> bool:
    import numpy as np
    from ezdxf import path as ezpath
    segs = []
    for e in layout:
        if e.dxftype() in ("VIEWPORT", "TEXT", "MTEXT", "DIMENSION", "HATCH", "POINT"):
            continue
        srcs = list(e.virtual_entities()) if e.dxftype() == "INSERT" else [e]
        for s in srcs:
            try:
                pts = [(v.x, v.y) for v in ezpath.make_path(s).flattening(0.01)]
            except Exception:
                continue
            if len(pts) >= 2:
                a = np.array(pts, dtype=float)
                segs.append(np.hstack([a[:-1], a[1:]]))
    if not segs:
        return False
    return Drawing._near(np.concatenate(segs), p, tol)


def grade_h6(ws: Path) -> dict:
    doc, err = _load(ws)
    if err:
        return err
    r = []
    base = Path(tempfile.mkdtemp(prefix="h6base")) / "base.dxf"
    make_h6_base(base)
    ref = ezdxf.readfile(base)
    r.append(check(_model_signature(doc) == _model_signature(ref), "model space part and dimensions unchanged",
                   "preserve"))
    names = [l.name for l in doc.layouts]
    if "A3" not in names:
        return _result(r + [check(False, f"layout 'A3' exists (layouts: {names})", "layout")])
    lay = doc.layouts.get("A3")
    r.append(check(True, "layout 'A3' exists", "layout"))
    pw, ph = lay.dxf.get("paper_width", 0), lay.dxf.get("paper_height", 0)
    r.append(check(sorted((round(pw), round(ph))) == [297, 420], f"paper A3 ({pw:g}×{ph:g})", "layout"))
    outer = ((210, 0), (420, 148.5), (210, 297), (0, 148.5))
    inner = ((220, 5), (415, 148.5), (220, 292), (25, 148.5))
    r.append(check(all(_segs_near(lay, p) for p in outer), "outer frame 420×297 at the origin", "frame"))
    r.append(check(all(_segs_near(lay, p) for p in inner), "inner frame (25 left, 5 elsewhere)", "frame"))
    texts = _texts(lay)
    joined = " ".join(t for t, _ in texts)
    r.append(check(all(s in joined for s in ("底板", "BP-300", "1:2", "Q235")),
                   "title block texts 底板 / BP-300 / 1:2 / Q235", "title"))
    tpos = [p for t, p in texts if any(s in t for s in ("底板", "BP-300", "1:2", "Q235"))]
    r.append(check(bool(tpos) and all(p[0] > 415 - 200 and p[1] < 5 + 50 for p in tpos),
                   "title block in the lower-right corner of the inner frame", "title"))
    vps = [v for v in lay.query("VIEWPORT") if v.dxf.get("id", 0) != 1]
    if not vps:
        return _result(r + [check(False, "a viewport onto the part", "viewport")])
    ext = bbox.extents(ref.modelspace())
    best = None
    for v in vps:
        h, vh = v.dxf.height, v.dxf.get("view_height", 0) or 0
        if not vh:
            continue
        s = h / vh
        cx, cy = v.dxf.center.x, v.dxf.center.y
        w = v.dxf.width
        vc = v.dxf.view_center_point
        win = (vc.x - w / s / 2, vc.y - h / s / 2, vc.x + w / s / 2, vc.y + h / s / 2)
        shows = (win[0] <= ext.extmin.x + 1 and win[1] <= ext.extmin.y + 1 and win[2] >= ext.extmax.x - 1
                 and win[3] >= ext.extmax.y - 1)
        if best is None or shows:
            best = (v, s, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), shows, vc)
    if best is None:
        return _result(r + [check(False, "a viewport with a view height", "viewport")])
    v, s, rect, shows, vc = best
    r.append(check(abs(s - 0.5) < 0.005, f"viewport scale 1:2 (got 1:{1 / s:.3g})", "viewport"))
    r.append(check(shows, "viewport shows the whole part incl. dimensions", "viewport"))
    r.append(check(rect[0] >= 25 - 0.5 and rect[1] >= 5 - 0.5 and rect[2] <= 415 + 0.5 and rect[3] <= 292 + 0.5,
                   "viewport inside the inner frame", "viewport"))
    r.append(check(not any(rect[0] < p[0] < rect[2] and rect[1] < p[1] < rect[3] for p in tpos),
                   "viewport does not cover the title block", "viewport"))
    mid = ((ext.extmin.x + ext.extmax.x) / 2, (ext.extmin.y + ext.extmax.y) / 2)
    img = (v.dxf.center.x + (mid[0] - vc.x) * s, v.dxf.center.y + (mid[1] - vc.y) * s)
    r.append(check(abs(img[0] - 220) < 70 and abs(img[1] - 148.5) < 60,
                   f"part roughly centred in the frame (at {img[0]:.0f},{img[1]:.0f})", "viewport"))
    r.append(check(v.dxf.get("status", 1) != 0, "viewport is on", "viewport"))
    return _result(r)
