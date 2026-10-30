"""Industry libraries: data behind the library ops (ops/library.py).

- P&ID symbols in the style of ISO 10628 / ISA-5.1, drawn in a unit box and scaled on insertion.
- GD&T characteristic symbols (ISO 1101 / ASME Y14.5), drawn in a unit cell of the feature control frame.
- ISO metric fasteners, deep groove ball bearings and hole sizes. Values are the nominal dimensions of the
  cited standards (nut heights: the maximum), which is what a drawing shows.

Geometry primitives (unit coordinates):
    ("line", p, q)  ("poly", [p...], closed)  ("circle", c, r)  ("arc", c, r, a0, a1)
    ("ellipse", c, rx, ry, a0, a1)  ("fill", [p...])  ("disc", c, r)
A primitive may end with a dict of extra DXF attributes (e.g. {"linetype": "DASHED"}).
"""
from __future__ import annotations

import math
from typing import Any

# --- metric threads and holes (ISO 261 coarse pitch, ISO 273 clearance, ISO 2306 tap drills) -----------------
PITCH = {"M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75, "M14": 2.0,
         "M16": 2.0, "M20": 2.5, "M24": 3.0}
CLEARANCE = {  # ISO 273: fine, medium, coarse
    "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0),
    "M8": (8.4, 9.0, 10.0), "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M14": (15.0, 15.5, 16.5),
    "M16": (17.0, 17.5, 18.5), "M20": (21.0, 22.0, 24.0), "M24": (25.0, 26.0, 28.0)}
TAP_DRILL = {"M3": 2.5, "M4": 3.3, "M5": 4.2, "M6": 5.0, "M8": 6.8, "M10": 8.5, "M12": 10.2, "M14": 12.0,
             "M16": 14.0, "M20": 17.5, "M24": 21.0}  # ISO 2306
COUNTERBORE = {  # for ISO 4762 cap screws (DIN 974-1 row 1): diameter, depth
    "M3": (6.5, 3.4), "M4": (8.0, 4.4), "M5": (10.0, 5.4), "M6": (11.0, 6.4), "M8": (15.0, 8.6),
    "M10": (18.0, 10.6), "M12": (20.0, 12.6), "M14": (24.0, 14.6), "M16": (26.0, 16.6), "M20": (33.0, 20.6),
    "M24": (40.0, 24.8)}
FITS = ("fine", "medium", "coarse")

# --- fasteners ---------------------------------------------------------------------------------------------
HEX_S = {"M3": 5.5, "M4": 7.0, "M5": 8.0, "M6": 10.0, "M8": 13.0, "M10": 16.0, "M12": 18.0, "M14": 21.0,
         "M16": 24.0, "M20": 30.0, "M24": 36.0}  # width across flats (ISO 4014/4017/4032)
BOLT_K = {"M3": 2.0, "M4": 2.8, "M5": 3.5, "M6": 4.0, "M8": 5.3, "M10": 6.4, "M12": 7.5, "M14": 8.8,
          "M16": 10.0, "M20": 12.5, "M24": 15.0}  # hex head height k, nominal (ISO 4014/4017)
NUT_M = {"M3": 2.4, "M4": 3.2, "M5": 4.7, "M6": 5.2, "M8": 6.8, "M10": 8.4, "M12": 10.8, "M14": 12.8,
         "M16": 14.8, "M20": 18.0, "M24": 21.5}  # nut height (ISO 4032)
WASHER = {"M3": (3.2, 7.0, 0.5), "M4": (4.3, 9.0, 0.8), "M5": (5.3, 10.0, 1.0), "M6": (6.4, 12.0, 1.6),
          "M8": (8.4, 16.0, 1.6), "M10": (10.5, 20.0, 2.0), "M12": (13.0, 24.0, 2.5), "M14": (15.0, 28.0, 2.5),
          "M16": (17.0, 30.0, 3.0), "M20": (21.0, 37.0, 3.0), "M24": (25.0, 44.0, 4.0)}  # ISO 7089: d1, d2, h
SHCS = {"M3": (5.5, 3.0, 2.5), "M4": (7.0, 4.0, 3.0), "M5": (8.5, 5.0, 4.0), "M6": (10.0, 6.0, 5.0),
        "M8": (13.0, 8.0, 6.0), "M10": (16.0, 10.0, 8.0), "M12": (18.0, 12.0, 10.0), "M14": (21.0, 14.0, 12.0),
        "M16": (24.0, 16.0, 14.0), "M20": (30.0, 20.0, 17.0), "M24": (36.0, 24.0, 19.0)}  # ISO 4762: dk, k, s
BEARINGS = {  # ISO 15 deep groove ball bearings: d, D, B
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10), "6004": (20, 42, 12),
    "6005": (25, 47, 12), "6006": (30, 55, 13), "6007": (35, 62, 14), "6008": (40, 68, 15), "6009": (45, 75, 16),
    "6010": (50, 80, 16),
    "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12), "6204": (20, 47, 14),
    "6205": (25, 52, 15), "6206": (30, 62, 16), "6207": (35, 72, 17), "6208": (40, 80, 18), "6209": (45, 85, 19),
    "6210": (50, 90, 20),
    "6300": (10, 35, 11), "6301": (12, 37, 12), "6302": (15, 42, 13), "6303": (17, 47, 14), "6304": (20, 52, 15),
    "6305": (25, 62, 17), "6306": (30, 72, 19), "6307": (35, 80, 21), "6308": (40, 90, 23), "6309": (45, 100, 25),
    "6310": (50, 110, 27)}

PARTS = {
    "hex_bolt": {"standard": "ISO 4014 / ISO 4017", "sizes": list(HEX_S), "needs_length": True,
                 "describe": "Hex head bolt; fully threaded (ISO 4017) when the length is within the thread length"},
    "hex_nut": {"standard": "ISO 4032", "sizes": list(NUT_M), "needs_length": False, "describe": "Hex nut"},
    "washer": {"standard": "ISO 7089", "sizes": list(WASHER), "needs_length": False, "describe": "Plain washer"},
    "socket_head_cap_screw": {"standard": "ISO 4762", "sizes": list(SHCS), "needs_length": True,
                              "describe": "Hexagon socket head cap screw"},
    "ball_bearing": {"standard": "ISO 15", "sizes": list(BEARINGS), "needs_length": False,
                     "describe": "Deep groove ball bearing, series 60xx / 62xx / 63xx"},
}
HOLE_KINDS = ("clearance", "tapped", "counterbore")


def thread_length(d: float, length: float) -> float:
    """Thread length b of ISO 4014 / ISO 4762 (ISO 888)."""
    b = 2 * d + 6 if length <= 125 else (2 * d + 12 if length <= 200 else 2 * d + 25)
    return min(b, length)


def part_dims(part: str, size: str, length: float | None = None) -> dict[str, Any]:
    """Dimensions used to draw a standard part (mm). Raises KeyError for an unknown part/size."""
    if part == "ball_bearing":
        d, D, B = BEARINGS[size]
        return {"d": d, "D": D, "B": B}
    d = float(size[1:])
    P = PITCH[size]
    out: dict[str, Any] = {"d": d, "pitch": P, "minor_diameter": round(d - 1.2269 * P, 3)}
    if part in ("hex_bolt", "hex_nut"):
        s = HEX_S[size]
        out.update(s=s, e=round(s / math.cos(math.radians(30)), 3))
        if part == "hex_bolt":
            out["k"] = BOLT_K[size]
        else:
            out["m"] = NUT_M[size]
    elif part == "washer":
        d1, d2, h = WASHER[size]
        out = {"d1": d1, "d2": d2, "h": h}
    elif part == "socket_head_cap_screw":
        dk, k, s = SHCS[size]
        out.update(dk=dk, k=k, s=s)
    if length is not None and part in ("hex_bolt", "socket_head_cap_screw"):
        out["length"] = length
        out["thread_length"] = thread_length(d, length) if part == "hex_bolt" else min(2 * d + 12, length)
        if part == "hex_bolt":
            out["standard"] = "ISO 4017" if out["thread_length"] >= length else "ISO 4014"
    return out


def hole_dims(size: str, kind: str, fit: str = "medium") -> dict[str, Any]:
    d = float(size[1:])
    if kind == "clearance":
        return {"diameter": CLEARANCE[size][FITS.index(fit)], "standard": "ISO 273", "fit": fit,
                "callout": f"%%c{CLEARANCE[size][FITS.index(fit)]:g}"}
    if kind == "tapped":
        drill = TAP_DRILL[size]
        return {"diameter": drill, "thread_diameter": d, "pitch": PITCH[size], "standard": "ISO 261 / ISO 2306",
                "callout": f"{size}-6H", "tap_drill": drill}
    cb, depth = COUNTERBORE[size]
    return {"diameter": CLEARANCE[size][1], "counterbore_diameter": cb, "counterbore_depth": depth,
            "standard": "ISO 273 / DIN 974-1",
            "callout": f"%%c{CLEARANCE[size][1]:g}, %%c{cb:g} depth {depth:g}"}


# --- P&ID symbols ----------------------------------------------------------------------------------------------
_BOW = ("poly", [(-0.5, 0.3), (0.5, -0.3), (0.5, 0.3), (-0.5, -0.3)], True)


def _zig(x0: float, x1: float, y: float, amp: float, n: int) -> list:
    pts = [(x0, y)]
    for i in range(1, n):
        pts.append((x0 + (x1 - x0) * i / n, y + (amp if i % 2 else -amp)))
    return pts + [(x1, y)]


PID: dict[str, dict[str, Any]] = {
    "gate_valve": {"prims": [_BOW], "inline": True, "describe": "Gate valve"},
    "globe_valve": {"prims": [_BOW, ("disc", (0, 0), 0.1)], "inline": True, "describe": "Globe valve"},
    "ball_valve": {"prims": [_BOW, ("circle", (0, 0), 0.15)], "inline": True, "describe": "Ball valve"},
    "check_valve": {"prims": [_BOW, ("fill", [(0, 0), (0.5, 0.3), (0.5, -0.3)])], "inline": True,
                    "describe": "Check valve (flow +x)"},
    "butterfly_valve": {"prims": [("line", (-0.5, -0.3), (-0.5, 0.3)), ("line", (0.5, -0.3), (0.5, 0.3)),
                                  ("circle", (0, 0), 0.15), ("line", (-0.3, -0.3), (0.3, 0.3))],
                        "inline": True, "describe": "Butterfly valve"},
    "three_way_valve": {"prims": [_BOW, ("poly", [(0, 0), (-0.3, -0.5), (0.3, -0.5)], True)], "inline": True,
                        "describe": "Three-way valve (third port down)"},
    "control_valve": {"prims": [_BOW, ("line", (0, 0), (0, 0.6)), ("arc", (0, 0.6), 0.3, 0, 180),
                                ("line", (-0.3, 0.6), (0.3, 0.6))], "inline": True,
                      "describe": "Control valve with diaphragm actuator"},
    "relief_valve": {"prims": [("poly", [(0, 0), (-0.3, -0.5), (0.3, -0.5)], True),
                               ("poly", [(0, 0), (0.5, 0.3), (0.5, -0.3)], True),
                               ("poly", [(0, 0), (0, 0.12)] + [(x, y) for y, x in zip((0.2, 0.3, 0.4, 0.5),
                                                                                    (-0.15, 0.15, -0.15, 0.15))]
                                + [(0, 0.56)], False)],
                     "inline": False, "tag_y": -0.8, "describe": "Pressure relief / safety valve (inlet down, outlet +x)"},
    "reducer": {"prims": [("poly", [(-0.5, 0.3), (0.5, 0.15), (0.5, -0.15), (-0.5, -0.3)], True)], "inline": True,
                "describe": "Concentric reducer"},
    "flange": {"prims": [("line", (-0.08, -0.3), (-0.08, 0.3)), ("line", (0.08, -0.3), (0.08, 0.3))],
               "inline": True, "span": 0.08, "describe": "Flange pair"},
    "orifice_plate": {"prims": [("line", (-0.06, -0.35), (-0.06, 0.35)), ("line", (0.06, -0.35), (0.06, 0.35))],
                      "inline": True, "span": 0.06, "describe": "Orifice plate"},
    "blind_flange": {"prims": [("line", (0, -0.3), (0, 0.3)), ("fill", [(0, -0.3), (0.1, -0.3), (0.1, 0.3),
                                                                        (0, 0.3)])],
                     "inline": False, "describe": "Blind flange (pipe end at the insertion point)"},
    "strainer": {"prims": [("poly", [(-0.5, -0.3), (0.5, -0.3), (0.5, 0.3), (-0.5, 0.3)], True),
                           ("line", (0, -0.3), (0, 0.3), {"linetype": "DASHED"})],
                 "inline": True, "describe": "Strainer / filter"},
    "centrifugal_pump": {"prims": [("circle", (0, 0), 0.5), ("line", (0, 0.5), (0.65, 0.5)),
                                   ("poly", [(-0.35, -0.36), (-0.5, -0.65), (0.5, -0.65), (0.35, -0.36)], False)],
                         "inline": False, "tag_y": -0.9, "describe": "Centrifugal pump (suction -x, discharge top)"},
    "compressor": {"prims": [("circle", (0, 0), 0.5), ("line", (-0.43, 0.25), (0.43, 0.12)),
                             ("line", (-0.43, -0.25), (0.43, -0.12))],
                   "inline": False, "tag_y": -0.8, "describe": "Compressor"},
    "heat_exchanger": {"prims": [("circle", (0, 0), 0.5), ("poly", _zig(-0.5, 0.5, 0, 0.25, 4), False)],
                       "inline": False, "tag_y": -0.8, "describe": "Heat exchanger"},
    "vessel_vertical": {"prims": [("line", (-0.5, -0.75), (-0.5, 0.75)), ("line", (0.5, -0.75), (0.5, 0.75)),
                                  ("ellipse", (0, 0.75), 0.5, 0.25, 0, 180),
                                  ("ellipse", (0, -0.75), 0.5, 0.25, 180, 360)],
                        "inline": False, "tag_y": -1.3, "describe": "Vertical vessel / column"},
    "vessel_horizontal": {"prims": [("line", (-0.75, -0.5), (0.75, -0.5)), ("line", (-0.75, 0.5), (0.75, 0.5)),
                                    ("ellipse", (0.75, 0), 0.25, 0.5, -90, 90),
                                    ("ellipse", (-0.75, 0), 0.25, 0.5, 90, 270)],
                          "inline": False, "tag_y": -0.85, "describe": "Horizontal vessel / drum"},
    "tank": {"prims": [("poly", [(-0.75, -0.6), (0.75, -0.6), (0.75, 0.6), (-0.75, 0.6)], True),
                       ("poly", [(-0.75, 0.6), (0, 0.85), (0.75, 0.6)], False)],
             "inline": False, "tag_y": -0.95, "describe": "Atmospheric storage tank (cone roof)"},
    "instrument_field": {"prims": [("circle", (0, 0), 0.5)], "inline": False, "instrument": True,
                         "describe": "Instrument, field mounted (ISA bubble)"},
    "instrument_panel": {"prims": [("circle", (0, 0), 0.5), ("line", (-0.5, 0), (0.5, 0))], "inline": False,
                         "instrument": True, "describe": "Instrument, main panel mounted"},
    "instrument_dcs": {"prims": [("circle", (0, 0), 0.5),
                                 ("poly", [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], True),
                                 ("line", (-0.5, 0), (0.5, 0))], "inline": False, "instrument": True,
                       "describe": "Shared display / DCS function"},
    "instrument_plc": {"prims": [("poly", [(0, 0.5), (0.5, 0), (0, -0.5), (-0.5, 0)], True),
                                 ("poly", [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], True),
                                 ("line", (-0.5, 0), (0.5, 0))], "inline": False, "instrument": True,
                       "describe": "PLC / programmable logic function"},
    "flow_arrow": {"prims": [("fill", [(-0.5, 0.25), (0.5, 0), (-0.5, -0.25)])], "inline": False,
                   "no_tag": True, "default_size": 4.0, "describe": "Flow direction arrow (+x)"},
}
PID_DEFAULT_SIZE = 10.0  # mm on paper (symbol width), times the annotation scale

LINE_KINDS = {  # P&ID line types: layer, linetype, lineweight (1/100 mm)
    "process": ("PID_PROCESS", "CONTINUOUS", 50),
    "utility": ("PID_UTILITY", "CONTINUOUS", 35),
    "signal_electric": ("PID_SIGNAL", "DASHED", 18),
    "signal_pneumatic": ("PID_SIGNAL", "CONTINUOUS", 18),
}


# --- GD&T --------------------------------------------------------------------------------------------------------
def _cyl() -> list:
    a = math.radians(60)
    d, n = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    out: list = [("circle", (0, 0), 0.22)]
    for side in (-1, 1):
        c = (side * 0.22 * n[0], side * 0.22 * n[1])
        out.append(("line", (c[0] - 0.4 * d[0], c[1] - 0.4 * d[1]), (c[0] + 0.4 * d[0], c[1] + 0.4 * d[1])))
    return out


def _arrow_line(p, q) -> list:
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    l, w = 0.16, 0.06
    b = (q[0] - l * math.cos(ang), q[1] - l * math.sin(ang))
    nx, ny = -math.sin(ang) * w, math.cos(ang) * w
    return [("line", p, b), ("fill", [q, (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny)])]


GDT: dict[str, dict[str, Any]] = {
    "straightness": {"prims": [("line", (-0.35, 0), (0.35, 0))], "group": "form"},
    "flatness": {"prims": [("poly", [(-0.38, -0.15), (0.2, -0.15), (0.38, 0.15), (-0.2, 0.15)], True)],
                 "group": "form"},
    "circularity": {"prims": [("circle", (0, 0), 0.3)], "group": "form"},
    "cylindricity": {"prims": _cyl(), "group": "form"},
    "profile_line": {"prims": [("arc", (0, -0.15), 0.32, 0, 180)], "group": "profile", "datums": "optional"},
    "profile_surface": {"prims": [("arc", (0, -0.15), 0.32, 0, 180), ("line", (-0.32, -0.15), (0.32, -0.15))],
                        "group": "profile", "datums": "optional"},
    "angularity": {"prims": [("line", (-0.35, -0.25), (0.35, -0.25)), ("line", (-0.35, -0.25), (0.3, 0.25))],
                   "group": "orientation"},
    "perpendicularity": {"prims": [("line", (-0.35, -0.25), (0.35, -0.25)), ("line", (0, -0.25), (0, 0.35))],
                         "group": "orientation"},
    "parallelism": {"prims": [("line", (-0.32, -0.25), (-0.05, 0.3)), ("line", (0.05, -0.25), (0.32, 0.3))],
                    "group": "orientation"},
    "position": {"prims": [("circle", (0, 0), 0.22), ("line", (-0.38, 0), (0.38, 0)), ("line", (0, -0.38), (0, 0.38))],
                 "group": "location", "datums": "optional"},
    "concentricity": {"prims": [("circle", (0, 0), 0.14), ("circle", (0, 0), 0.32)], "group": "location"},
    "symmetry": {"prims": [("line", (-0.35, 0), (0.35, 0)), ("line", (-0.22, 0.18), (0.22, 0.18)),
                           ("line", (-0.22, -0.18), (0.22, -0.18))], "group": "location"},
    "circular_runout": {"prims": _arrow_line((-0.22, -0.32), (0.18, 0.34)), "group": "runout"},
    "total_runout": {"prims": _arrow_line((-0.34, -0.32), (-0.02, 0.34)) + _arrow_line((0.04, -0.32), (0.36, 0.34))
                     + [("line", (-0.34, -0.32), (0.04, -0.32))], "group": "runout"},
}
DATUM_REQUIRED = {"angularity", "perpendicularity", "parallelism", "concentricity", "symmetry", "circular_runout",
                  "total_runout"}
FORM_ONLY = {k for k, v in GDT.items() if v["group"] == "form"}
MODIFIERS = ("M", "L", "S", "P", "F", "T", "U")


def index() -> dict[str, Any]:
    """Compact catalogue for the standard_library tool."""
    from .fits import catalog
    return {
        "iso_fits": catalog(),
        "pid_symbols": sorted(PID),
        "pid_line_kinds": sorted(LINE_KINDS),
        "gdt_characteristics": sorted(GDT),
        "standard_parts": {k: {"standard": v["standard"], "sizes": v["sizes"], "needs_length": v["needs_length"]}
                           for k, v in PARTS.items()},
        "standard_holes": {"kinds": list(HOLE_KINDS), "sizes": list(CLEARANCE), "fits": list(FITS)},
    }


def table(item: str, size: str | None = None) -> dict[str, Any]:
    """Rows of one library item (all sizes, or one)."""
    if item == "iso_fit":
        from .fits import table as fit_table
        return fit_table(size)
    if item in PARTS:
        sizes = [size] if size else PARTS[item]["sizes"]
        return {"item": item, "standard": PARTS[item]["standard"], "describe": PARTS[item]["describe"],
                "rows": {s: part_dims(item, s) for s in sizes}}
    if item in HOLE_KINDS:
        sizes = [size] if size else list(CLEARANCE)
        rows = {s: ({f: hole_dims(s, item, f) for f in FITS} if item == "clearance" else hole_dims(s, item))
                for s in sizes}
        return {"item": item, "rows": rows}
    if item in PID:
        return {"item": item, "describe": PID[item]["describe"], "inline": PID[item]["inline"],
                "attributes": ["FUNC", "LOOP"] if PID[item].get("instrument") else ([] if PID[item].get("no_tag")
                                                                                   else ["TAG"])}
    if item in GDT:
        return {"item": item, "group": GDT[item]["group"],
                "datums": "required" if item in DATUM_REQUIRED else ("none" if item in FORM_ONLY else "optional")}
    raise KeyError(item)
