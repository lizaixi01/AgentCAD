"""Neutral grader for the trial tasks: plain ezdxf only, no AgentCAD code, so neither arm is favoured.

    python examples/trials/grade.py <task> <file.dxf>          one drawing -> JSON
    python examples/trials/grade.py --compare A_root B_root    both arms, all tasks -> table + grades.json

Geometry is checked by sampling: key points must (or must not) lie on the visible geometry, whatever entities
were used to draw it (polyline, lines, arcs, blocks). Centre lines are geometry drawn with a CENTER/DASHDOT
linetype or on an AXIS/CENTER layer. A required dimension counts as
  "dim"        a DIMENSION entity measuring that value,
  "text-only"  no such DIMENSION, but some text shows the number (lines + text drawn to look like a dimension),
  "missing"    neither.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import ezdxf
import numpy as np
from ezdxf import path as ezpath

TOL = 0.05
SKIP = {"DIMENSION", "TEXT", "MTEXT", "ATTRIB", "ATTDEF", "HATCH", "LEADER", "MULTILEADER", "MLEADER", "POINT",
        "SOLID", "WIPEOUT", "VIEWPORT"}


def polar(r, deg, c=(0.0, 0.0)):
    return (c[0] + r * math.cos(math.radians(deg)), c[1] + r * math.sin(math.radians(deg)))


class Drawing:
    def __init__(self, path: Path):
        self.doc = ezdxf.readfile(str(path))
        self.msp = self.doc.modelspace()
        vis, cen = [], []
        for e, layer_name in self._flat(self.msp, depth=0):
            segs = self._segments(e)
            if segs is None:
                continue
            (cen if self._is_center(e, layer_name) else vis).append(segs)
        self.vis = np.concatenate(vis) if vis else np.zeros((0, 4))
        self.cen = np.concatenate(cen) if cen else np.zeros((0, 4))
        self.texts = self._texts()
        self.dims = self._dims()

    def _flat(self, layout, depth):
        for e in layout:
            if e.dxftype() == "INSERT" and depth < 4:
                try:
                    yield from self._flat(list(e.virtual_entities()), depth + 1)
                except Exception:
                    continue
            elif e.dxftype() not in SKIP:
                yield e, e.dxf.get("layer", "0")

    def _linetype(self, e, layer_name):
        lt = (e.dxf.get("linetype") or "BYLAYER").upper()
        if lt in ("BYLAYER", "BYBLOCK") and layer_name in self.doc.layers:
            lt = (self.doc.layers.get(layer_name).dxf.get("linetype") or "").upper()
        return lt

    def _is_center(self, e, layer_name):
        lt = self._linetype(e, layer_name)
        return any(k in lt for k in ("CENTER", "DASHDOT", "CHAIN")) or layer_name.upper() in ("AXIS", "CENTER", "CENTERLINE")

    @staticmethod
    def _segments(e):
        try:
            pts = [(v.x, v.y) for v in ezpath.make_path(e).flattening(0.005)]
        except Exception:
            return None
        if len(pts) < 2:
            return None
        a = np.array(pts, dtype=float)
        return np.hstack([a[:-1], a[1:]])

    def _texts(self):
        out = []
        for e in self.msp.query("TEXT MTEXT"):
            t = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
            out.append((t, (e.dxf.insert.x, e.dxf.insert.y)))
        for ins in self.msp.query("INSERT"):
            for a in ins.attribs:
                out.append((a.dxf.text, (a.dxf.insert.x, a.dxf.insert.y)))
            try:
                for v in ins.virtual_entities():
                    if v.dxftype() in ("TEXT", "MTEXT"):
                        t = v.plain_text() if v.dxftype() == "MTEXT" else v.dxf.text
                        out.append((t, (v.dxf.insert.x, v.dxf.insert.y)))
            except Exception:
                pass
        return out

    def _dims(self):
        out = []
        for d in self.msp.query("DIMENSION"):
            try:
                m = d.get_measurement()
                m = float(m) if not hasattr(m, "x") else None
            except Exception:
                m = None
            kind = d.dimtype & 0x0F
            if kind in (2, 5) and m is not None:  # angular: ezdxf returns radians
                m = math.degrees(m)
            out.append({"value": m, "kind": kind, "text": d.dxf.get("text", "") or ""})
        return out

    @staticmethod
    def _near(segs, p, tol):
        if len(segs) == 0:
            return False
        a, b = segs[:, 0:2], segs[:, 2:4]
        ab = b - a
        L2 = (ab ** 2).sum(1)
        t = np.clip(((np.array(p) - a) * ab).sum(1) / np.where(L2 == 0, 1, L2), 0, 1)
        d = np.sqrt((((a + ab * t[:, None]) - np.array(p)) ** 2).sum(1))
        return bool((d <= tol).any())

    def on(self, p, tol=TOL):
        return self._near(self.vis, p, tol)

    def on_center(self, p, tol=TOL):
        return self._near(self.cen, p, tol)

    def circle(self, c, r):
        return all(self.on(polar(r, a, c)) for a in range(0, 360, 45))

    def dim(self, value, text_has=None):
        """'dim' / 'text-only' / 'missing' for a required dimension value."""
        for d in self.dims:
            if d["value"] is not None and abs(d["value"] - value) <= 0.01:
                if text_has is None or all(re.search(t, d["text"] or "") for t in text_has):
                    return "dim"
        num = re.compile(rf"(?<![\d.]){re.escape(f'{value:g}')}(?![\d.])")
        texts = [t for t, _ in self.texts] + [d["text"] for d in self.dims]
        if any(num.search(t or "") and (text_has is None or all(re.search(x, t) for x in text_has)) for t in texts):
            return "text-only"
        return "missing"

    def text(self, s):
        return any(s in (t or "") for t, _ in self.texts)

    def text_at(self, s):
        return [p for t, p in self.texts if s in (t or "")]


def check(cond, name, cat):
    return {"check": name, "cat": cat, "ok": bool(cond)}


def grade_T1(g: Drawing):
    r = [check(g.circle((0, 0), 75), "outer circle Ø150", "geometry"),
         check(g.circle((0, 0), 30), "bore Ø60", "geometry")]
    holes = [polar(55, 90 + 60 * k) for k in range(6)]
    r.append(check(all(g.circle(c, 6) for c in holes), "6×Ø12 on PCD 110, first on top", "geometry"))
    r.append(check(all(g.on_center(polar(55, a)) for a in (0, 45, 135, 180, 225, 315)), "PCD Ø110 as centre line", "geometry"))
    r.append(check(all(g.on_center(p) for p in ((-70, 0), (70, 0), (0, 70), (0, -70))), "horizontal + vertical centre lines", "geometry"))
    dims = {"Ø150": g.dim(150), "Ø60": g.dim(60), "Ø110": g.dim(110), "6×Ø12": g.dim(12, [r"6\s*[×xX]"])}
    return r, dims


def grade_T2(g: Drawing):
    r = [check(all(g.on(p) for p in ((80, 0), (80, 100), (0, 50), (160, 50))), "outline 160×100", "geometry")]
    k = 8 - 8 / math.sqrt(2)
    corners = ((k, k), (160 - k, k), (k, 100 - k), (160 - k, 100 - k))
    r.append(check(all(g.on(p) for p in corners) and not any(g.on(p) for p in ((0, 0), (160, 0), (0, 100), (160, 100))),
                   "four R8 corners", "geometry"))
    for cx in (40, 120):
        pts = [(cx - 10, 55), (cx + 10, 55), (cx - 10, 45), (cx + 10, 45), (cx - 15, 50), (cx + 15, 50),
               polar(5, 135, (cx - 10, 50)), polar(5, 45, (cx + 10, 50))]
        r.append(check(all(g.on(p) for p in pts) and not g.on((cx - 15, 55)), f"slot 30×10 at ({cx},50)", "geometry"))
    r.append(check(g.circle((80, 50), 10), "Ø20 hole at centre", "geometry"))
    dims = {"160": g.dim(160), "100": g.dim(100), "R8": g.dim(8), "30": g.dim(30), "10": g.dim(10),
            "80": g.dim(80), "Ø20": g.dim(20)}
    return r, dims


def grade_T3(g: Drawing):
    r = [check(all(g.on(p) for p in ((25, 15), (25, -15), (165, 15), (165, -15))), "Ø30 sections", "geometry"),
         check(all(g.on(p) for p in ((90, 20), (90, -20))), "Ø40 section", "geometry"),
         check(all(g.on(p) for p in ((50, 17.5), (50, -17.5), (130, 17.5), (130, -17.5))), "shoulders at 50 / 130", "geometry"),
         check(all(g.on(p) for p in ((1, 14), (1, -14), (199, 14), (199, -14))) and not g.on((0, 15)) and not g.on((200, 15)),
               "C2 chamfers both ends", "geometry"),
         check(all(g.on(p) for p in ((0, 6), (0, -6), (200, 6), (200, -6))), "end faces", "geometry"),
         check(g.on_center((10, 0)) and g.on_center((190, 0)), "axis as centre line", "geometry"),
         check(all(g.on(p) for p in ((2, 8), (50, 8), (130, 8), (198, 8))), "visible edge lines across the diameter",
               "convention")]
    dims = {"Ø30": g.dim(30), "Ø40": g.dim(40), "50": g.dim(50), "80": g.dim(80), "70": g.dim(70), "200": g.dim(200)}
    return r, dims


def grade_T4(g: Drawing):
    r = [check(all(g.on(p) for p in ((210, 0), (210, 297), (0, 150), (420, 150))), "outer frame 420×297", "geometry"),
         check(all(g.on(p) for p in ((25, 150), (410, 150), (200, 10), (200, 287))), "inner frame 25/10/10/10", "geometry")]
    for s in ("法兰盘", "FL-001", "Q235", "1:1"):
        r.append(check(g.text(s), f"title block text {s}", "annotation"))
    for s in ("序号", "名称", "数量", "材料", "螺栓", "M10", "8.8"):
        r.append(check(g.text(s), f"BOM text {s}", "annotation"))
    fl = g.text_at("FL-001")
    xu = g.text_at("序号")
    r.append(check(any(230 <= x <= 410 and 10 <= y <= 70 for x, y in fl), "title block at lower-right of inner frame", "convention"))
    r.append(check(bool(fl) and any(230 <= x <= 410 and min(y for _, y in fl) < y < 200 for x, y in xu),
                   "BOM directly above title block", "convention"))
    return r, {}


def grade_T5(g: Drawing):
    r = [check(all(g.on_center(p) for p in ((1000, 0), (5000, 0), (1000, 4000), (5000, 4000), (0, 2000), (6000, 2000))),
               "axes 6000×4000 as centre lines", "geometry"),
         check(all(g.on(p) for p in ((1000, -120), (5000, -120), (1000, 4120), (5000, 4120), (-120, 2000), (6120, 2000))),
               "outer wall lines (axis +120)", "geometry"),
         check(all(g.on(p) for p in ((1000, 120), (5000, 120), (1000, 3880), (5000, 3880), (120, 2000), (5880, 2000))),
               "inner wall lines (axis -120)", "geometry"),
         check(not g.on((3000, -120)) and not g.on((3000, 120)) and g.on((2550, -60)) and g.on((3450, -60)),
               "door opening 900, centred, jambs closed", "geometry"),
         check(g.on((2250, 3940)) and g.on((3750, 3940)), "window opening 1500, centred, jambs closed", "geometry")]
    ys = sorted({round(y, 1) for y in np.linspace(3870, 4130, 2601) if g.on((3000, y), tol=0.05)})
    lines = [y for i, y in enumerate(ys) if i == 0 or y - ys[i - 1] > 1]
    r.append(check(len(lines) >= 4, f"window as 4 parallel lines (found {len(lines)})", "geometry"))
    dims = {"6000": g.dim(6000), "4000": g.dim(4000), "900": g.dim(900), "1500": g.dim(1500)}
    return r, dims


def grade_T6(g: Drawing):
    r = [check(g.circle((0, 0), 75) and g.circle((0, 0), 30), "Ø150 / Ø60 kept", "geometry"),
         check(all(g.circle(polar(57.5, 90 + 45 * k), 6) for k in range(8)), "8×Ø12 on PCD 115, first on top", "geometry"),
         check(not any(g.circle(polar(55, 90 + 60 * k), 6) for k in range(6)), "old 6 holes removed", "geometry"),
         check(all(g.on_center(polar(57.5, a)) for a in (22.5, 67.5, 112.5, 157.5)) and not g.on_center(polar(55, 22.5)),
               "PCD centre line now Ø115", "geometry")]
    dims = {"8×Ø12": g.dim(12, [r"8\s*[×xX]"]), "Ø115": g.dim(115), "Ø150": g.dim(150), "Ø60": g.dim(60)}
    stale = [d for d in g.dims if re.search(r"6\s*[×xX]", d["text"])] + \
        [d for d in g.dims if d["value"] is not None and abs(d["value"] - 110) < 0.01]
    r.append(check(not stale, "no stale 6×Ø12 / Ø110 dimension left", "annotation"))
    return r, dims


GRADERS = {"T1": grade_T1, "T2": grade_T2, "T3": grade_T3, "T4": grade_T4, "T5": grade_T5, "T6": grade_T6}
OUTPUT = {"T1": "flange.dxf", "T2": "slot_plate.dxf", "T3": "shaft.dxf", "T4": "frame_a3.dxf", "T5": "room.dxf",
          "T6": "flange.dxf"}


def grade(task: str, path: Path) -> dict:
    if not path.is_file():
        return {"file": str(path), "exists": False}
    try:
        g = Drawing(path)
    except Exception as exc:
        return {"file": str(path), "exists": True, "readable": False, "error": str(exc)[:200]}
    checks, dims = GRADERS[task[:2]](g)
    aud = g.doc.audit()
    return {"file": str(path), "exists": True, "readable": True,
            "insunits": g.doc.header.get("$INSUNITS", 0), "ezdxf_audit_errors": len(aud.errors),
            "checks": checks, "dims": dims,
            "geometry": f"{sum(c['ok'] for c in checks if c['cat'] == 'geometry')}/{sum(c['cat'] == 'geometry' for c in checks)}",
            "other": f"{sum(c['ok'] for c in checks if c['cat'] != 'geometry')}/{sum(c['cat'] != 'geometry' for c in checks)}",
            "dim_summary": {k: sum(v == k for v in dims.values()) for k in ("dim", "text-only", "missing")}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "--compare":
        roots = {"A_agentcad": Path(sys.argv[2]), "B_code": Path(sys.argv[3])}
        tasks = ["T1_flange", "T2_slot_plate", "T3_shaft", "T4_frame", "T5_room", "T6_flange_revise"]
        out = {arm: {t: grade(t, root / t / OUTPUT[t[:2]]) for t in tasks} for arm, root in roots.items()}
        out_name = sys.argv[4] if len(sys.argv) > 4 else "grades.json"   # e.g. grades_cc.json for Claude Code
        Path(__file__).with_name(out_name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        for t in tasks:
            for arm in roots:
                r = out[arm][t]
                if not r.get("readable"):
                    print(f"{t:18} {arm:11} NOT READABLE {r}")
                    continue
                fails = [c["check"] for c in r["checks"] if not c["ok"]]
                print(f"{t:18} {arm:11} geom {r['geometry']:5} other {r['other']:5} dims {r['dim_summary']} "
                      f"units={r['insunits']} audit={r['ezdxf_audit_errors']} fails={fails} "
                      f"dimdetail={ {k: v for k, v in r['dims'].items() if v != 'dim'} }")
        return
    print(json.dumps(grade(sys.argv[1], Path(sys.argv[2])), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
