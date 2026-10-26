"""Check explicit requirements against geometry recognised from the file.

Requirement types (all lengths in drawing units, positions relative to the
lower-left corner of the recognised outline unless ``frame: "world"``)::

  {"type": "outline", "width": 100, "height": 60, "layer": "OUTLINE"}
  {"type": "hole", "diameter": 8, "center": [10, 10]}
  {"type": "hole_count", "count": 4, "diameter": 8}
  {"type": "dimension", "kind": "linear", "value": 100}
  {"type": "entity_count", "entity_type": "CIRCLE", "count": 4, "layer": "HOLES"}
  {"type": "text", "contains": "Q235"}
  {"type": "within_bounds", "min": [0, 0], "max": [297, 210]}

Each result reports expected, actual, deviation and tolerance.
"""
from __future__ import annotations

from typing import Any

from .. import geom as G
from .features import Features, holes_in, pick_outline

DEFAULT_TOL = 1e-3
COMMON = {"id", "type", "tolerance", "source"}
FIELDS = {
    "outline": {"width", "height", "layer"},
    "hole": {"diameter", "center", "frame", "outline_layer", "layer", "tag"},
    "hole_count": {"count", "diameter", "outline_layer", "layer"},
    "dimension": {"value", "kind", "tag", "layer"},
    "entity_count": {"entity_type", "count", "layer"},
    "text": {"contains"},
    "within_bounds": {"min", "max", "outline_layer"},
}


def _res(req: dict[str, Any], ok: bool, *, expected: Any, actual: Any, deviation: float | None,
         tol: float, entities: list[str] | None = None, message: str = "") -> dict[str, Any]:
    r = {"id": req.get("id"), "type": req["type"], "status": "pass" if ok else "fail", "expected": expected,
         "actual": actual, "deviation": None if deviation is None else round(deviation, 9), "tolerance": tol,
         "entities": entities or [], "message": message}
    if "source" in req:
        r["source"] = req["source"]
    return r


def check_requirements(feats: Features, reqs: list[dict[str, Any]],
                       counts: list[tuple[str, str, str]] | None = None) -> list[dict[str, Any]]:
    """``counts``: (type, layer, handle) of every modelspace entity, for entity_count."""
    out = []
    outline_cache: dict[Any, Any] = {}

    def outline(layer):
        if layer not in outline_cache:
            outline_cache[layer] = pick_outline(feats, layer)
        return outline_cache[layer]

    for i, req in enumerate(reqs):
        req = {"id": req.get("id", f"R{i + 1}"), **req}
        t = req.get("type")
        tol = float(req.get("tolerance", DEFAULT_TOL))
        layer = req.get("outline_layer", req.get("layer") if t == "outline" else None)
        n_before = len(out)
        try:
            if t == "outline":
                o = outline(layer)
                if o is None:
                    out.append(_res(req, False, expected={"width": req.get("width"), "height": req.get("height")},
                                    actual=None, deviation=None, tol=tol, message="No closed outline contour found"))
                    continue
                w, h = o.size
                dev = max(abs(w - req["width"]), abs(h - req["height"]))
                out.append(_res(req, dev <= tol, expected={"width": req["width"], "height": req["height"]},
                                actual={"width": round(w, 9), "height": round(h, 9)}, deviation=dev, tol=tol,
                                entities=o.entities))
            elif t == "hole":
                o = outline(req.get("outline_layer"))
                origin = (0.0, 0.0)
                if req.get("frame", "outline") == "outline":
                    if o is None:
                        out.append(_res(req, False, expected=req, actual=None, deviation=None, tol=tol,
                                        message="No outline to measure hole position from"))
                        continue
                    origin = (o.bbox[0], o.bbox[1])
                cands = holes_in(feats, o, req.get("layer")) if o is not None else feats.circles
                if req.get("tag"):
                    cands = [c for c in cands if c.tag == req["tag"]]
                want = G.add(origin, tuple(req["center"]))
                if not cands:
                    out.append(_res(req, False, expected={"center": req["center"], "diameter": req["diameter"]},
                                    actual=None, deviation=None, tol=tol, message="No holes found"))
                    continue
                best = min(cands, key=lambda c: G.dist(c.center, want))
                pos_dev = G.dist(best.center, want)
                dia_dev = abs(best.diameter - req["diameter"])
                rel = G.sub(best.center, origin)
                out.append(_res(req, pos_dev <= tol and dia_dev <= tol,
                                expected={"center": req["center"], "diameter": req["diameter"]},
                                actual={"center": [round(rel[0], 9), round(rel[1], 9)], "diameter": round(best.diameter, 9)},
                                deviation=max(pos_dev, dia_dev), tol=tol, entities=[best.id],
                                message="" if pos_dev <= tol and dia_dev <= tol else
                                f"nearest hole off by position {pos_dev:.6g}, diameter {dia_dev:.6g}"))
            elif t == "hole_count":
                o = outline(req.get("outline_layer"))
                cands = holes_in(feats, o, req.get("layer")) if o is not None else feats.circles
                if req.get("diameter") is not None:
                    cands = [c for c in cands if abs(c.diameter - req["diameter"]) <= tol]
                n = len(cands)
                out.append(_res(req, n == req["count"], expected=req["count"], actual=n,
                                deviation=float(abs(n - req["count"])), tol=0, entities=[c.id for c in cands]))
            elif t == "dimension":
                kinds = {"linear": {"linear", "aligned"}, "aligned": {"linear", "aligned"}, "diameter": {"diameter"},
                         "radius": {"radius"}, "angular": {"angular", "angular3p"}}.get(req.get("kind", "linear"))
                cands = [d for d in feats.dimensions if (kinds is None or d["kind"] in kinds) and d["measurement"] is not None
                         and (not req.get("tag") or d["tag"] == req["tag"])
                         and (not req.get("layer") or d["layer"] == req["layer"])]
                if not cands:
                    out.append(_res(req, False, expected=req["value"], actual=None, deviation=None, tol=tol,
                                    message=f"No {req.get('kind', 'linear')} dimension in the drawing"))
                    continue
                best = min(cands, key=lambda d: abs(d["measurement"] - req["value"]))
                dev = abs(best["measurement"] - req["value"])
                out.append(_res(req, dev <= tol, expected=req["value"], actual=round(best["measurement"], 9),
                                deviation=dev, tol=tol, entities=[best["id"]],
                                message="" if dev <= tol else f"No {req.get('kind', 'linear')} dimension measures {req['value']}"))
            elif t == "entity_count":
                et, ly = req["entity_type"].upper(), req.get("layer")
                ids = [h for (typ, lay, h) in (counts or []) if typ == et and (ly is None or lay == ly)]
                n = len(ids)
                out.append(_res(req, n == req["count"], expected=req["count"], actual=n,
                                deviation=float(abs(n - req["count"])), tol=0, entities=ids))
            elif t == "text":
                hits = [h for txt, h in feats.texts if req["contains"] in txt]
                out.append(_res(req, bool(hits), expected=req["contains"], actual=len(hits), deviation=None, tol=0,
                                entities=hits))
            elif t == "within_bounds":
                o = outline(req.get("outline_layer"))
                pts = [p for c in feats.contours for p in c.polygon] + [h.center for h in feats.circles]
                if not pts:
                    out.append(_res(req, True, expected=req, actual=None, deviation=0.0, tol=tol))
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                (x0, y0), (x1, y1) = req["min"], req["max"]
                dev = max(0.0, x0 - min(xs), y0 - min(ys), max(xs) - x1, max(ys) - y1)
                out.append(_res(req, dev <= tol, expected={"min": req["min"], "max": req["max"]},
                                actual={"min": [round(min(xs), 9), round(min(ys), 9)], "max": [round(max(xs), 9), round(max(ys), 9)]},
                                deviation=dev, tol=tol))
            else:
                out.append({"id": req["id"], "type": t, "status": "error", "message": f"Unknown requirement type {t!r}"})
        except KeyError as exc:
            out.append({"id": req["id"], "type": t, "status": "error",
                        "message": f"Requirement is missing field {exc}", "source": req.get("source")})
        unknown = sorted(set(req) - COMMON - FIELDS.get(t, set()))
        if unknown and t in FIELDS and len(out) > n_before:
            # surface instead of silently ignoring: the caller may believe they are being checked
            out[-1]["warnings"] = [f"ignored unknown field(s) {unknown}; valid: {sorted(FIELDS[t])}"]
    return out
