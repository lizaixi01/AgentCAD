"""Experiment A3: AutoCAD 2027 as an oracle for AgentCAD's edit operations.

Each case defines setup geometry, the AutoCAD command sequence (run headless
in accoreconsole) and the equivalent AgentCAD operation. AutoCAD's resulting
entities are dumped and stored in tests/golden/autocad_ops.json, which
tests/test_autocad_golden.py compares against AgentCAD without needing AutoCAD.

    python research/autocad/exp_ops_oracle.py            # run AutoCAD, refresh golden file
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
GOLDEN = ROOT / "tests" / "golden" / "autocad_ops.json"

# setup primitives: ("line", p, q) | ("circle", c, r) | ("arc", c, r, a1_deg, a2_deg)
#                   ("poly", [(x, y, bulge)...], closed) | ("text", insert, s, h)
CASES: dict[str, dict] = {
    "fillet_r10": {
        "setup": [("line", (0, 0), (50, 0)), ("line", (0, 0), (0, 50))],
        "acad": '(setvar "FILLETRAD" 10.0)(command "_.FILLET" (list E0 (list 40.0 0.0)) (list E1 (list 0.0 40.0)))',
        "ours": [{"op": "fillet", "line1": "tag:t0", "line2": "tag:t1", "radius": 10}]},
    "fillet_r0_extends_gap": {
        "setup": [("line", (0, 0), (40, 0)), ("line", (50, 10), (50, 60))],
        "acad": '(setvar "FILLETRAD" 0.0)(command "_.FILLET" (list E0 (list 10.0 0.0)) (list E1 (list 50.0 40.0)))',
        "ours": [{"op": "fillet", "line1": "tag:t0", "line2": "tag:t1", "radius": 0}]},
    "fillet_r5_obtuse": {
        "setup": [("line", (0, 0), (60, 0)), ("line", (0, 0), (-30, 40))],
        "acad": '(setvar "FILLETRAD" 5.0)(command "_.FILLET" (list E0 (list 50.0 0.0)) (list E1 (list -24.0 32.0)))',
        "ours": [{"op": "fillet", "line1": "tag:t0", "line2": "tag:t1", "radius": 5}]},
    "chamfer_5_8": {
        "setup": [("line", (100, 0), (150, 0)), ("line", (100, 0), (100, 50))],
        "acad": '(setvar "CHAMMODE" 0)(setvar "CHAMFERA" 5.0)(setvar "CHAMFERB" 8.0)'
                '(command "_.CHAMFER" (list E0 (list 140.0 0.0)) (list E1 (list 100.0 40.0)))',
        "ours": [{"op": "chamfer", "line1": "tag:t0", "line2": "tag:t1", "d1": 5, "d2": 8}]},
    "offset_line": {
        "setup": [("line", (0, 0), (10, 0))],
        "acad": '(command "_.OFFSET" 2.0 (list E0 (list 5.0 0.0)) (list 5.0 -1.0) "")',
        "ours": [{"op": "offset", "target": "tag:t0", "distance": 2, "side_point": [5, -1]}]},
    "offset_circle_inward": {
        "setup": [("circle", (0, 0), 5)],
        "acad": '(command "_.OFFSET" 1.0 (list E0 (list 5.0 0.0)) (list 0.0 0.0) "")',
        "ours": [{"op": "offset", "target": "tag:t0", "distance": 1, "side_point": [0, 0]}]},
    "offset_rect_outward": {
        "setup": [("poly", [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], True)],
        "acad": '(command "_.OFFSET" 1.0 (list E0 (list 5.0 0.0)) (list 50.0 50.0) "")',
        "ours": [{"op": "offset", "target": "tag:t0", "distance": 1, "side_point": [50, 50]}]},
    "offset_rect_inward": {
        "setup": [("poly", [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], True)],
        "acad": '(command "_.OFFSET" 1.0 (list E0 (list 5.0 0.0)) (list 5.0 5.0) "")',
        "ours": [{"op": "offset", "target": "tag:t0", "distance": 1, "side_point": [5, 5]}]},
    "trim_line_middle": {
        "setup": [("line", (0, 0), (100, 0)), ("line", (30, -10), (30, 10)), ("line", (70, -10), (70, 10))],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.TRIM" E1 E2 "" (list E0 (list 50.0 0.0)) "")',
        "ours": [{"op": "trim", "target": "tag:t0", "edges": ["tag:t1", "tag:t2"], "pick": [50, 0]}]},
    "trim_line_end": {
        "setup": [("line", (0, 0), (100, 0)), ("line", (30, -10), (30, 10))],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.TRIM" E1 "" (list E0 (list 10.0 0.0)) "")',
        "ours": [{"op": "trim", "target": "tag:t0", "edges": "tag:t1", "pick": [10, 0]}]},
    "trim_circle_to_arc": {
        "setup": [("circle", (50, 50), 10), ("line", (50, 30), (50, 70))],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.TRIM" E1 "" (list E0 (list 60.0 50.0)) "")',
        "ours": [{"op": "trim", "target": "tag:t0", "edges": "tag:t1", "pick": [60, 50]}]},
    "trim_arc_middle": {
        "setup": [("arc", (0, 0), 10, 0, 180), ("line", (-20, 5), (20, 5))],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.TRIM" E1 "" (list E0 (list 0.0 10.0)) "")',
        "ours": [{"op": "trim", "target": "tag:t0", "edges": "tag:t1", "pick": [0, 10]}]},
    "extend_line_to_circle": {
        "setup": [("line", (0, 50), (20, 50)), ("circle", (50, 50), 10)],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.EXTEND" E1 "" (list E0 (list 19.0 50.0)) "")',
        "ours": [{"op": "extend", "target": "tag:t0", "edges": "tag:t1", "end": "end"}]},
    "extend_line_to_line": {
        "setup": [("line", (0, 0), (10, 10)), ("line", (40, -50), (40, 50))],
        "acad": '(setq *tem* (getvar "TRIMEXTENDMODE"))(setvar "TRIMEXTENDMODE" 0)(command "_.EXTEND" E1 "" (list E0 (list 9.0 9.0)) "")',
        "ours": [{"op": "extend", "target": "tag:t0", "edges": "tag:t1"}]},
    "mirror_arc_poly_text": {
        "setup": [("arc", (10, 0), 5, 0, 90), ("poly", [(10, 0, 0), (20, 0, 0.5), (20, 10, 0)], False),
                  ("text", (10, 5), "T", 2.5)],
        "acad": '(setvar "MIRRTEXT" 0)(command "_.MIRROR" (ssadd E0 (ssadd E1 (ssadd E2))) "" '
                '(list 0.0 0.0) (list 0.0 1.0) "_N")',
        "ours": [{"op": "mirror", "target": ["tag:t0", "tag:t1", "tag:t2"], "p1": [0, 0], "p2": [0, 1]}]},
    "mirror_diagonal_circle_line": {
        "setup": [("circle", (10, 2), 1), ("line", (5, 0), (8, 3))],
        "acad": '(command "_.MIRROR" (ssadd E0 (ssadd E1)) "" (list 0.0 0.0) (list 1.0 1.0) "_Y")',
        "ours": [{"op": "mirror", "target": ["tag:t0", "tag:t1"], "p1": [0, 0], "p2": [1, 1],
                  "keep_original": False}]},
    "mirror_text_horizontal_axis": {
        "setup": [("text", (10, 5), "AB", 2.5)],
        "acad": '(setvar "MIRRTEXT" 0)(command "_.MIRROR" E0 "" (list 0.0 0.0) (list 1.0 0.0) "_N")',
        "ours": [{"op": "mirror", "target": "tag:t0", "p1": [0, 0], "p2": [1, 0]}]},
    "mirror_block_insert": {
        "setup": [("block", "BK", [("circle", (5, 0), 1), ("line", (0, 0), (5, 0))], (10, 10))],
        "acad": '(command "_.MIRROR" E0 "" (list 0.0 0.0) (list 0.0 1.0) "_N")',
        "ours": [{"op": "mirror", "target": "tag:t0", "p1": [0, 0], "p2": [0, 1]}]},
    "rotate_line": {
        "setup": [("line", (0, 0), (10, 0)), ("arc", (20, 0), 5, 0, 90)],
        "acad": '(command "_.ROTATE" (ssadd E0 (ssadd E1)) "" (list 0.0 0.0) 30.0)',
        "ours": [{"op": "rotate", "target": ["tag:t0", "tag:t1"], "angle": 30, "center": [0, 0]}]},
    "scale_circle_poly": {
        "setup": [("circle", (10, 0), 2), ("poly", [(0, 0, 0), (5, 0, 1), (5, 5, 0)], False)],
        "acad": '(command "_.SCALE" (ssadd E0 (ssadd E1)) "" (list 0.0 0.0) 2.5)',
        "ours": [{"op": "scale", "target": ["tag:t0", "tag:t1"], "factor": 2.5, "center": [0, 0]}]},
    "array_rect": {
        "setup": [("circle", (0, 0), 1)],
        "acad": '(command "_.-ARRAY" E0 "" "_R" 2 3 10.0 20.0)',
        "ours": [{"op": "array_rect", "target": "tag:t0", "rows": 2, "cols": 3, "row_spacing": 10, "col_spacing": 20}]},
    "array_polar_rotated": {
        "setup": [("line", (90, 0), (110, 0))],
        "acad": '(command "_.-ARRAY" E0 "" "_P" (list 0.0 0.0) 4 360.0 "_Y")',
        "ours": [{"op": "array_polar", "target": "tag:t0", "center": [0, 0], "count": 4}]},
    "array_polar_partial": {
        "setup": [("circle", (50, 0), 2)],
        "acad": '(command "_.-ARRAY" E0 "" "_P" (list 0.0 0.0) 3 90.0 "_Y")',
        "ours": [{"op": "array_polar", "target": "tag:t0", "center": [0, 0], "count": 3, "total_angle": 90}]},
    "stretch_plate": {
        "setup": [("poly", [(0, 0, 0), (100, 0, 0), (100, 60, 0), (0, 60, 0)], True), ("circle", (90, 10), 4),
                  ("circle", (10, 10), 4), ("line", (95, 30), (40, 30))],
        # crossing-window selection only sees what is inside the current view: zoom first
        "acad": '(command "_.ZOOM" "_W" (list -100.0 -100.0) (list 300.0 200.0))'
                '(command "_.STRETCH" "_C" (list 50.0 -50.0) (list 200.0 100.0) "" (list 0.0 0.0) (list 20.0 0.0))',
        "ours": [{"op": "stretch", "window": [[50, -50], [200, 100]], "delta": [20, 0]}]},
    "arc_three_point": {
        "setup": [],
        "acad": '(command "_.ARC" (list 10.0 0.0) (list 0.0 10.0) (list -10.0 0.0))',
        "ours": [{"op": "add_arc", "start": [10, 0], "mid": [0, 10], "end": [-10, 0]}]},
    "arc_three_point_cw": {
        "setup": [],
        "acad": '(command "_.ARC" (list -10.0 0.0) (list 0.0 10.0) (list 10.0 0.0))',
        "ours": [{"op": "add_arc", "start": [-10, 0], "mid": [0, 10], "end": [10, 0]}]},
    "dimensions": {
        "setup": [("circle", (50, 50), 10)],
        "acad": '(command "_.DIMLINEAR" (list 0.0 0.0) (list 100.0 0.0) (list 50.0 -10.0))'
                '(command "_.DIMLINEAR" (list 0.0 0.0) (list 30.0 40.0) (list -10.0 20.0))'
                '(command "_.DIMALIGNED" (list 0.0 0.0) (list 30.0 40.0) (list 10.0 30.0))'
                '(command "_.DIMDIAMETER" (list E0 (list 60.0 50.0)) (list 70.0 60.0))'
                '(command "_.DIMRADIUS" (list E0 (list 50.0 60.0)) (list 50.0 75.0))'
                '(command "_.DIMANGULAR" "" (list 0.0 0.0) (list 10.0 0.0) (list 0.0 10.0) (list 5.0 5.0))',
        "ours": [{"op": "add_linear_dim", "p1": [0, 0], "p2": [100, 0], "base": [50, -10]},
                 {"op": "add_linear_dim", "p1": [0, 0], "p2": [30, 40], "orientation": "vertical", "base": [-10, 20]},
                 {"op": "add_linear_dim", "p1": [0, 0], "p2": [30, 40], "orientation": "aligned", "base": [10, 30]},
                 {"op": "add_diameter_dim", "target": "tag:t0"},
                 {"op": "add_radius_dim", "target": "tag:t0"},
                 {"op": "add_angular_dim", "center": [0, 0], "p1": [10, 0], "p2": [0, 10]}]},
}

DUMP = r'''
(defun fmt (v) (cond ((= (type v) 'REAL) (rtos v 2 12)) ((= (type v) 'INT) (itoa v)) ((= (type v) 'STR) v)
  ((= (type v) 'LIST) (if (numberp (car v)) (strcat (rtos (car v) 2 12) "," (rtos (cadr v) 2 12) (if (caddr v) (strcat "," (rtos (caddr v) 2 12)) "")) "?")) (T "?")))
(setq ss (ssget "X") i 0)
(if ss (repeat (sslength ss) (setq ed (entget (ssname ss i)) s (cdr (assoc 0 ed)) i (1+ i))
  (foreach g ed (if (member (car g) (quote (1 2 10 11 13 14 15 40 41 42 43 50 51 70 72 73 210))) (setq s (strcat s "|" (itoa (car g)) ":" (fmt (cdr g))))))
  (if (= (cdr (assoc 0 ed)) "TEXT") (setq tb (textbox ed) s (strcat s "|tb:" (rtos (car (car tb)) 2 12) "," (rtos (car (cadr tb)) 2 12))))
  (out "ent" s)))
'''


def no_snap(acad: str) -> str:
    """Prefix every coordinate argument with "_non": running object snaps (the user's
    OSMODE is 4133) otherwise snap command points to nearby geometry. Entity picks
    written as (list E<n> (list x y)) are left alone."""
    return re.sub(r'(?<!E\d )\(list (-?[\d.]+) (-?[\d.]+)\)', r'"_non" (list \1 \2)', acad)


def setup_lisp(setup) -> str:
    parts = []
    for i, s in enumerate(setup):
        k = s[0]
        if k == "line":
            parts.append(f"(entmake (list '(0 . \"LINE\") (list 10 {s[1][0]:.10f} {s[1][1]:.10f} 0.0) (list 11 {s[2][0]:.10f} {s[2][1]:.10f} 0.0)))")
        elif k == "circle":
            parts.append(f"(entmake (list '(0 . \"CIRCLE\") (list 10 {s[1][0]:.10f} {s[1][1]:.10f} 0.0) (cons 40 {s[2]:.10f})))")
        elif k == "arc":  # entmake takes radians for 50/51 (DXF files store degrees)
            parts.append(f"(entmake (list '(0 . \"ARC\") (list 10 {s[1][0]:.10f} {s[1][1]:.10f} 0.0) (cons 40 {s[2]:.10f}) "
                         f"(cons 50 {math.radians(s[3]):.15f}) (cons 51 {math.radians(s[4]):.15f})))")
        elif k == "poly":
            v = " ".join(f"(list 10 {x:.10f} {y:.10f}) (cons 42 {b:.10f})" for x, y, b in s[1])
            parts.append(f"(entmake (list '(0 . \"LWPOLYLINE\") '(100 . \"AcDbEntity\") '(100 . \"AcDbPolyline\") "
                         f"(cons 90 {len(s[1])}) (cons 70 {1 if s[2] else 0}) {v}))")
        elif k == "text":
            parts.append(f"(entmake (list '(0 . \"TEXT\") (list 10 {s[1][0]:.10f} {s[1][1]:.10f} 0.0) (cons 40 {s[3]:.10f}) (cons 1 \"{s[2]}\")))")
        elif k == "block":  # ("block", name, [line/circle...], insert)
            parts.append(f"(entmake (list '(0 . \"BLOCK\") (cons 2 \"{s[1]}\") '(70 . 0) '(10 0.0 0.0 0.0)))")
            for sub in s[2]:
                if sub[0] == "circle":
                    parts.append(f"(entmake (list '(0 . \"CIRCLE\") (list 10 {sub[1][0]:.10f} {sub[1][1]:.10f} 0.0) (cons 40 {sub[2]:.10f})))")
                else:
                    parts.append(f"(entmake (list '(0 . \"LINE\") (list 10 {sub[1][0]:.10f} {sub[1][1]:.10f} 0.0) (list 11 {sub[2][0]:.10f} {sub[2][1]:.10f} 0.0)))")
            parts.append("(entmake '((0 . \"ENDBLK\")))")
            parts.append(f"(entmake (list '(0 . \"INSERT\") (cons 2 \"{s[1]}\") (list 10 {s[3][0]:.10f} {s[3][1]:.10f} 0.0)))")
        parts.append(f"(setq E{i} (entlast))")
    return "\n".join(parts)


def ours_setup_ops(setup) -> list[dict]:
    ops = []
    for i, s in enumerate(setup):
        k, tag = s[0], f"t{i}"
        if k == "line":
            ops.append({"op": "add_line", "start": list(s[1]), "end": list(s[2]), "tag": tag})
        elif k == "circle":
            ops.append({"op": "add_circle", "center": list(s[1]), "radius": s[2], "tag": tag})
        elif k == "arc":
            ops.append({"op": "add_arc", "center": list(s[1]), "radius": s[2], "start_angle": s[3], "end_angle": s[4], "tag": tag})
        elif k == "poly":
            ops.append({"op": "add_polyline", "points": [[x, y, b] for x, y, b in s[1]], "closed": s[2], "tag": tag})
        elif k == "text":
            ops.append({"op": "add_text", "text": s[2], "insert": list(s[1]), "height": s[3], "tag": tag})
        elif k == "block":
            ents = [{"op": "add_circle", "center": list(b[1]), "radius": b[2]} if b[0] == "circle"
                    else {"op": "add_line", "start": list(b[1]), "end": list(b[2])} for b in s[2]]
            ops.append({"op": "define_block", "name": s[1], "entities": ents})
            ops.append({"op": "insert_block", "name": s[1], "insert": list(s[3]), "tag": tag})
    return ops


def run_autocad(names=None) -> dict:
    sys.path.insert(0, str(HERE))
    from acad import run_lisp
    out = {}
    for name, case in CASES.items():
        if names and name not in names:
            continue
        # TRIMEXTENDMODE is stored in the user's AutoCAD profile: cases that change it
        # save it in *tem*, and it is restored in the same session
        restore = '(if *tem* (setvar "TRIMEXTENDMODE" *tem*))'
        r = run_lisp("oracle_" + name, "(setq *tem* nil)\n" + setup_lisp(case["setup"]) + "\n" + no_snap(case["acad"])
                     + "\n" + restore + "\n" + DUMP)
        ents = r.all("ent")
        out[name] = {"acad_entities": ents, "seconds": r.seconds}
        print(f"{name}: {len(ents)} entities ({r.seconds}s)")
        if not ents:
            print(r.log[-1500:])
    return out


if __name__ == "__main__":
    import ezdxf  # noqa: F401  (version recorded below)
    res = run_autocad(sys.argv[1:] or None)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(GOLDEN.read_text("utf-8"))["cases"] if GOLDEN.is_file() else {}
    old.update(res)
    GOLDEN.write_text(json.dumps({"source": "AutoCAD 2027 accoreconsole (X.60.0.0), research/autocad/exp_ops_oracle.py",
                                  "cases": old}, indent=1), "utf-8")
    print("wrote", GOLDEN)
