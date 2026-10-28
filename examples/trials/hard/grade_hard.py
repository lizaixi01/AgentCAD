"""Neutral grading of the hard tasks (plain ezdxf plus AutoCAD only for DWG->DXF conversion and AUDIT).

    python examples/trials/hard/grade_hard.py [--agent claude] <A workspaces> <B workspaces> [task ...]

Writes examples/trials/hard/grades.json (or grades_<tasks>.json when tasks are given) and prints one line per
(task, arm, rep). H4-H6 are graded by grade_hard2.py. --agent claude grades the Claude Code runs (runs_cc/,
snapshots_cc/) into grades_cc*.json. Run from PowerShell/cmd: it starts AutoCAD for H2.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parent))
from grade import Drawing, check, polar  # noqa: E402
from summarize_run import summarize  # noqa: E402
from grade_hard2 import grade_h4, grade_h5, grade_h6  # noqa: E402

SAMPLE = Path(r"D:\Apps\AutoCAD\AutoCAD 2027\Sample\Sheet Sets\Manufacturing\VW252-02-0142.dwg")
JOBS = Path(tempfile.mkdtemp(prefix="gradehard"))
SFX = ""                                  # "_cc" for the Claude Code runs (--agent claude)
RUNS, SNAPS = HERE / "runs", HERE / "snapshots"


# --- H1 ---------------------------------------------------------------------------------------------
H1_STATES = {0: (120, 10, False, "A"), 1: (150, 10, False, "A"), 2: (150, 12, False, "A"),
             3: (150, 12, True, "A"), 4: (150, 10, True, "A"), 5: (150, 10, True, "C")}


def h1_state(g: Drawing, n: int) -> list[dict]:
    W, d, centre, rev = H1_STATES[n]
    other_w = 120 if W == 150 else 150
    other_d = 12 if d == 10 else 10
    k = 5 - 5 / math.sqrt(2)
    r = [check(all(g.on(p) for p in ((W / 2, 0), (W / 2, 80), (W, 40), (0, 40), (W - k, k), (k, 80 - k)))
               and not g.on((other_w, 40)), f"outline {W}×80 with R5", "geometry")]
    holes = ((12, 12), (W - 12, 12), (12, 68), (W - 12, 68))
    r.append(check(all(g.circle(c, d / 2) for c in holes) and not any(g.circle(c, other_d / 2) for c in holes),
                   f"4×Ø{d} at 12 from the edges", "geometry"))
    r.append(check(g.circle((W / 2, 40), 15) == centre, "centre hole Ø30" + ("" if centre else " absent"), "geometry"))
    dim_w = g.dim(W) == "dim" and g.dim(other_w) != "dim"
    dia = [x["value"] * (2 if x["kind"] == 4 else 1) for x in g.dims if x["kind"] in (3, 4) and x["value"] is not None]
    dim_d = any(abs(v - d) < 0.01 for v in dia) and not any(abs(v - other_d) < 0.01 for v in dia)
    r.append(check(dim_w, f"width dimension {W} (no stale {other_w})", "dimension"))
    r.append(check(dim_d, f"hole dimension Ø{d} (no stale Ø{other_d})", "dimension"))
    if centre:
        r.append(check(g.dim(30) == "dim", "Ø30 dimension", "dimension"))
    r.append(check(g.dim(80) == "dim" and sum(1 for x in g.dims if x["value"] and abs(x["value"] - 12) < .01) >= 2,
                   "untouched dims 80 / 12 / 12 kept", "preserve"))
    hatches = list(g.msp.query("HATCH"))
    r.append(check(len(hatches) == 1 and hatches[0].dxf.pattern_name == "ANSI31"
                   and all(g.on(p) for p in ((145, 60), (145, 75), (135, 67), (155, 67))) and g.text("ACME"),
                   "customer logo + hatch kept", "preserve"))
    r.append(check(any("技术要求" in t and "去毛刺" in t for t, _ in g.texts), "technical notes kept", "preserve"))
    att = {a.dxf.tag: a.dxf.text for i in g.msp.query("INSERT") if i.dxf.name == "TB" for a in i.attribs}
    r.append(check(att.get("PART_NO") == "BP-120" and att.get("REV") == rev, f"title block PART_NO kept, REV={rev}",
                   "preserve" if rev == "A" else "task"))
    if n == 5:
        r.append(check(any("REV C" in (t or "") and "150" in (t or "") for t, _ in g.texts), "revision note", "task"))
    return r


def grade_h1(ws: Path, snaps: Path) -> dict:
    rounds = {}
    for n in range(1, 6):
        f = snaps / f"round{n}.dxf"
        if not f.is_file():
            rounds[n] = {"ok": False, "error": "missing"}
            continue
        try:
            checks = h1_state(Drawing(f), n)
        except Exception as exc:
            rounds[n] = {"ok": False, "error": str(exc)[:200]}
            continue
        rounds[n] = {"ok": all(c["ok"] for c in checks), "passed": sum(c["ok"] for c in checks),
                     "total": len(checks), "fails": [c["check"] for c in checks if not c["ok"]]}
    final = rounds.get(5, {})
    return {"rounds": rounds, "final_ok": final.get("ok", False),
            "rounds_ok": sum(1 for r in rounds.values() if r.get("ok")), "undo_ok": rounds.get(4, {}).get("ok", False)}


# --- H2 ---------------------------------------------------------------------------------------------
def dwg_to_dxf(src: Path, dst: Path) -> bool:
    from agentcad.backends import autocad
    try:
        autocad.dwg_to_dxf(src, dst, JOBS, "2018")
        return dst.is_file()
    except Exception:
        return False


def key(e):
    t = e.dxftype()
    r = lambda v: round(v, 3)  # noqa: E731
    x = e.dxf
    if t == "LINE":
        a, b = sorted([(r(x.start.x), r(x.start.y)), (r(x.end.x), r(x.end.y))])
        return (t, x.layer, a, b)
    if t == "ARC":
        return (t, x.layer, r(x.center.x), r(x.center.y), r(x.radius), r(x.start_angle), r(x.end_angle))
    if t == "INSERT":
        return (t, x.layer, x.name, r(x.insert.x), r(x.insert.y))
    if t in ("TEXT",):
        return (t, x.layer, x.text, r(x.insert.x), r(x.insert.y))
    return (t, x.layer)


def grade_h2(ws: Path, ref: Path) -> dict:
    import ezdxf
    if (ws / "part.dwg").is_file():
        src, orig = ws / "part.dwg", SAMPLE
    else:  # arm B worked on the DXF that AutoCAD converted for it
        src, orig = ws / "part.dxf", SNAPS / "B" / ws.name / "part_given.dxf"
    out = {"part_dwg_untouched": src.is_file() and orig.is_file() and
           hashlib.sha256(src.read_bytes()).hexdigest() == hashlib.sha256(orig.read_bytes()).hexdigest()}
    dwg = ws / "part_rev.dwg"
    if not dwg.is_file():
        return out | {"exists": False, "ok": False}
    conv = JOBS / f"{ws.parent.name}_{ws.name}.dxf"
    if not dwg_to_dxf(dwg, conv):
        return out | {"exists": True, "opens_in_autocad": False, "ok": False}
    from agentcad.backends import autocad
    aud = autocad.audit_dxf(conv, JOBS)
    doc_a, doc_b = ezdxf.readfile(ref), ezdxf.readfile(conv)
    a, b = doc_a.modelspace(), doc_b.modelspace()
    # The printed sheet (paper-space layout "Base Plate") holds its own copy of the part at 0.325 scale, plus
    # the title block. A correct revision changes the holes there too; annotations may sit on the sheet.
    sheet_a, sheet_b = doc_a.layouts.get("Base Plate"), doc_b.layouts.get("Base Plate")
    sheet_hist = lambda L: Counter(round(2 * c.dxf.radius / 0.325, 2) for c in L.query("CIRCLE"))  # noqa: E731
    want_sheet = Counter({(10.5 if d == 10.2 else 26.0 if d == 25.0 else d): 0 for d in sheet_hist(sheet_a)})
    for d, n in sheet_hist(sheet_a).items():
        want_sheet[10.5 if d == 10.2 else 26.0 if d == 25.0 else d] += n
    sheet_ok = sheet_b is not None and +sheet_hist(sheet_b) == +want_sheet
    ca = [(round(c.dxf.center.x, 3), round(c.dxf.center.y, 3), round(2 * c.dxf.radius, 3)) for c in a.query("CIRCLE")]
    cb = Counter((round(c.dxf.center.x, 3), round(c.dxf.center.y, 3), round(2 * c.dxf.radius, 3)) for c in b.query("CIRCLE"))
    change = {10.2: 10.5, 25.0: 26.0}
    want = Counter((x, y, change.get(d, d)) for x, y, d in ca)
    circles_ok = cb == want
    hist = Counter(d for _, _, d in cb.elements())
    others_a = Counter(key(e) for e in a if e.dxftype() not in ("CIRCLE", "DIMENSION"))
    others_b = Counter(key(e) for e in b if e.dxftype() not in ("CIRCLE", "DIMENSION"))
    removed = others_a - others_b
    added = others_b - others_a
    added_texts = [k for k in added.elements() if k[0] in ("TEXT", "MTEXT")]
    layouts = [b] + ([sheet_b] if sheet_b is not None else [])
    texts = [(e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text) for L in layouts for e in L.query("TEXT MTEXT")]
    rev_ok = any("REV B" in t and "10.5" in t and "26" in t for t in texts)
    d40 = []
    for L in layouts:
        for d in L.query("DIMENSION"):
            try:
                shown = float(d.get_measurement()) * (d.override().get("dimlfac") or 1.0)  # value as displayed
                d40.append(abs(shown - 40) < 0.01 and (d.dimtype & 0x0F) in (3, 4))
            except Exception:
                pass
    unexpected_added = [k for k in added.elements() if k[0] not in ("TEXT", "MTEXT")]
    res = out | {"exists": True, "opens_in_autocad": True, "audit_errors": aud.get("audit_errors"),
                 "circles_ok": circles_ok, "diameter_histogram": {str(k): v for k, v in sorted(hist.items())},
                 "other_entities_removed": sum(removed.values()), "other_entities_added": len(unexpected_added),
                 "dims_on_d40": sum(d40), "rev_text_ok": rev_ok, "added_texts": len(added_texts),
                 "sheet_holes_updated": sheet_ok,
                 "sheet_hole_histogram": {str(k): v for k, v in sorted(sheet_hist(sheet_b).items())} if sheet_b else None}
    res["ok"] = bool(circles_ok and sheet_ok and not removed and not unexpected_added and sum(d40) >= 2 and rev_ok
                     and aud.get("audit_errors") == 0 and out["part_dwg_untouched"])
    return res


# --- H3 ---------------------------------------------------------------------------------------------
H3_ROWS = [r.split(",") for r in (HERE / "tasks" / "H3_batch.md").read_text(encoding="utf-8")
           .split("零件号,外径,中心孔,节圆,孔数,孔径,材料\n")[1].strip().splitlines()]
H3_INVALID = {"FL-109", "FL-111"}


def flange_checks(g: Drawing, od, bore, pcd, n, hd, pid, mat) -> list[dict]:
    r = [check(g.circle((0, 0), od / 2) and g.circle((0, 0), bore / 2), "outer + bore", "geometry"),
         check(all(g.circle(polar(pcd / 2, 90 + 360 / n * k), hd / 2) for k in range(n)), f"{n} holes first on top", "geometry"),
         check(all(g.on_center(polar(pcd / 2, 90 + 360 / n * (k + .5))) for k in range(min(n, 4))), "PCD centre line", "geometry"),
         check(g.on_center((od / 2 + 2, 0)) or g.on_center((od / 2 - 1, 0)), "centre lines", "geometry")]
    for name, v in (("OD", od), ("bore", bore), ("PCD", pcd)):
        r.append(check(g.dim(v) == "dim", f"dimension {name}", "dimension"))
    # hole pattern: a diameter dimension reading n×Ød, or the usual leader note with exactly that text
    callout = re.compile(rf"(?<!\d){n}\s*[×xX]\s*(?:Ø|⌀|%%[cC])?\s*{hd:g}(?![\d.])")
    r.append(check(g.dim(hd, [rf"{n}\s*[×xX]"]) == "dim" or any(callout.search(t or "") for t, _ in g.texts),
                   "hole callout n×Ød", "dimension"))
    r.append(check(any(pid in (t or "") and mat in (t or "") for t, _ in g.texts) or
                   (g.text(pid) and g.text(mat)), "part no + material text", "annotation"))
    return r


def grade_h3(ws: Path, final: str) -> dict:
    files = {}
    for pid, od, bore, pcd, n, hd, mat in H3_ROWS:
        f = ws / f"{pid}.dxf"
        if pid in H3_INVALID:
            files[pid] = {"invalid_row": True, "file_written": f.is_file(), "reported": pid in (final or ""),
                          "ok": (not f.is_file()) and pid in (final or "")}
            continue
        if not f.is_file():
            files[pid] = {"ok": False, "error": "missing"}
            continue
        try:
            c = flange_checks(Drawing(f), float(od), float(bore), float(pcd), int(n), float(hd), pid, mat)
        except Exception as exc:
            files[pid] = {"ok": False, "error": str(exc)[:200]}
            continue
        files[pid] = {"ok": all(x["ok"] for x in c), "fails": [x["check"] for x in c if not x["ok"]]}
    valid = [p for p in files if p not in H3_INVALID]
    return {"files": files, "valid_ok": sum(files[p]["ok"] for p in valid), "valid_total": len(valid),
            "invalid_handled": sum(files[p]["ok"] for p in H3_INVALID), "ok": all(f["ok"] for f in files.values())}


def cost(arm: str, task: str, rep: int) -> dict:
    logs = sorted((RUNS / arm).glob(f"{task}_r{rep}*.jsonl"))
    tot = {"calls": 0, "shell": 0, "tool_errors": 0, "input_tokens": 0, "cached": 0, "output_tokens": 0}
    finals = []
    for p in logs:
        s = summarize(p)
        tot["calls"] += sum(1 for c in s["calls"] if c["tool"] != "SHELL")
        tot["shell"] += sum(1 for c in s["calls"] if c["tool"] == "SHELL")
        tot["tool_errors"] += s["n_errors"]
        u = s["usage"] or {}
        tot["input_tokens"] += u.get("input_tokens", 0)
        tot["cached"] += u.get("cached_input_tokens", 0)
        tot["output_tokens"] += u.get("output_tokens", 0)
        finals.append(s["final"] or "")
    tot["final"] = finals[-1] if finals else ""
    return tot


def main() -> None:
    global SFX, RUNS, SNAPS
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if args[:2] == ["--agent", "claude"]:
        SFX, args = "_cc", args[2:]
        RUNS, SNAPS = HERE / "runs_cc", HERE / "snapshots_cc"
    roots = {"A": Path(args[0]), "B": Path(args[1])}
    only = set(args[2:])
    ref = JOBS / "reference.dxf"
    if not only or "H2" in only:
        dwg_to_dxf(SAMPLE, ref)
    summary = [s for f in sorted(RUNS.glob("summary_*.json"))
               for s in json.loads(f.read_text(encoding="utf-8")) if not only or s["task"] in only]
    secs = {(s["arm"], s["task"], s["rep"]): s["seconds"] for s in summary}
    out = []
    for (arm, task, rep) in sorted(secs):
        ws = roots[arm] / f"{task}_r{rep}"
        c = cost(arm, task, rep)
        if task == "H1":
            g = grade_h1(ws, SNAPS / arm / f"H1_r{rep}")
            ok = g["final_ok"]
        elif task == "H2":
            g = grade_h2(ws, ref)
            ok = g["ok"]
        elif task in ("H4", "H5", "H6"):
            g = {"H4": grade_h4, "H5": grade_h5, "H6": grade_h6}[task](ws)
            ok = g["ok"]
        else:
            g = grade_h3(ws, c["final"])
            ok = g["ok"]
        row = {"arm": arm, "task": task, "rep": rep, "ok": ok, "seconds": secs[(arm, task, rep)],
               "grade": g, "cost": {k: v for k, v in c.items() if k != "final"}, "final": c["final"][:1500]}
        out.append(row)
        brief = ({"rounds_ok": g["rounds_ok"], "undo_ok": g["undo_ok"],
                  "fails": {n: r.get("fails", r.get("error")) for n, r in g["rounds"].items() if not r.get("ok")}}
                 if task == "H1" else
                 {k: v for k, v in g.items() if k not in ("files",)} if task == "H2" else
                 {"fails": g["fails"]} if task in ("H4", "H5", "H6") else
                 {"valid_ok": f"{g['valid_ok']}/{g['valid_total']}", "invalid_handled": g["invalid_handled"],
                  "fails": {p: f.get("fails", f.get("error")) for p, f in g["files"].items() if not f["ok"]}})
        print(json.dumps({"task": task, "arm": arm, "rep": rep, "ok": ok, "s": row["seconds"], **brief,
                          "cost": row["cost"]}, ensure_ascii=False), flush=True)
    name = f"grades{SFX}_{'-'.join(sorted(only))}.json" if only else f"grades{SFX}.json"
    (HERE / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
