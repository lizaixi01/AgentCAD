"""Strict-pass probes for varavista/autocad-mcp @7034dc4 (headless ezdxf backend).

Calls the backend API the MCP tools call (EzdxfBackend) and reads results back
independently with ezdxf after save/reopen. Each probe records expected vs observed
and a verdict: PASS (behaves as claimed), FAIL (wrong / false success), INFO.
"""
import asyncio, json, math, os, sys, tempfile, traceback
import ezdxf
from autocad_mcp.backends.ezdxf_backend import EzdxfBackend

OUT = sys.argv[1] if len(sys.argv) > 1 else "/out/probe_results.json"
W = tempfile.mkdtemp(prefix="probe_")
R = []

def rec(pid, item, expect, observed, verdict):
    R.append({"id": pid, "item": item, "expect": expect, "observed": observed, "verdict": verdict})
    print(f"[{verdict}] {pid} ({item}): {observed}")

async def fresh():
    b = EzdxfBackend(); r = await b.initialize(); assert r.ok; return b

def reopen(p):
    return ezdxf.readfile(p)

def close(a, b, tol=1e-6):
    return abs(a - b) <= tol

async def probe(pid, item, fn):
    try:
        await fn()
    except Exception as ex:
        rec(pid, item, "no uncaught exception", f"EXCEPTION {type(ex).__name__}: {ex}", "FAIL")

async def main():
    # ---------------- F1 geometry + measurement, saved readback ----------------
    async def f1():
        b = await fresh()
        l = (await b.create_line(0, 0, 30, 40, layer="G")).payload["handle"]
        c = (await b.create_circle(10, 10, 5)).payload["handle"]
        p = (await b.create_polyline([[0, 0], [10, 0], [10, 20], [0, 20]], closed=True)).payload["handle"]
        a = (await b.create_arc(0, 0, 10, 0, 90)).payload["handle"]
        e = await b.create_ellipse(0, 0, 20, 0, 0.5)
        h = await b.create_hatch(p, "ANSI31")
        ln = (await b.geometry_length(l)).payload; ar = (await b.geometry_area(p)).payload
        ca = (await b.geometry_area(c)).payload; al = (await b.geometry_length(a)).payload
        path = os.path.join(W, "f1.dxf"); await b.drawing_save(path)
        d = reopen(path); msp = d.modelspace()
        types = sorted(x.dxftype() for x in msp)
        L = d.entitydb[l]; P = d.entitydb[p]
        ok = (close(L.dxf.end[0], 30) and close(L.dxf.end[1], 40) and L.dxf.layer == "G"
              and P.closed and len(P) == 4 and h.ok and e.ok
              and "HATCH" in types and "ELLIPSE" in types)
        rec("F1-ordinary", "F1", "primitives+hatch saved and reopened with same geometry; length 50, rect area 200, circle area 25pi, arc len 5pi",
            {"types": types, "line_len": ln, "poly_area": ar, "circle_area": ca, "arc_len": al},
            "PASS" if ok and close(ln["length"], 50) and close(ar["area"], 200) and close(ca["area"], 25 * math.pi, 1e-6) and close(al["length"], 5 * math.pi, 1e-6) else "FAIL")
        # hatch boundary from a circle (no get_points): error or false success?
        hc = await b.create_hatch(c, "ANSI31")
        rec("F1-hatch-circle", "F1", "hatch a circle boundary or refuse", {"ok": hc.ok, "error": hc.error}, "INFO")
        bad = await b.geometry_length("FFFFF")
        rec("F1-bad-handle", "F1", "ok=false for unknown handle", {"ok": bad.ok, "error": bad.error}, "PASS" if not bad.ok else "FAIL")
    await probe("F1", "F1", f1)

    # ---------------- F2 editing ----------------
    async def f2():
        b = await fresh()
        l = (await b.create_line(0, 0, 10, 0)).payload["handle"]
        await b.entity_move(l, 5, 5)
        await b.entity_rotate(l, 5, 5, 90)
        sc = await b.entity_scale(l, 5, 5, 2)
        m = await b.entity_mirror(l, 0, 0, 0, 10)
        arr = await b.entity_array(l, 2, 3, 10, 20)
        path = os.path.join(W, "f2.dxf"); await b.drawing_save(path)
        d = reopen(path); L = d.entitydb[l]
        s, e = L.dxf.start, L.dxf.end  # expected after move: (5,5)-(15,5); rot 90 about (5,5): (5,5)-(5,15); scale 2: (5,5)-(5,25)
        ok = close(s[0], 5, 1e-6) and close(s[1], 5, 1e-6) and close(e[0], 5, 1e-6) and close(e[1], 25, 1e-6)
        n_lines = len([x for x in d.modelspace() if x.dxftype() == "LINE"])
        M = d.entitydb[m.payload["handle"]] if m.ok else None
        mir_ok = M is not None and close(M.dxf.start[0], -5, 1e-6) and close(M.dxf.end[1], 25, 1e-6)
        rec("F2-transforms", "F2", "move/rotate/scale -> (5,5)-(5,25); mirror about x=0 -> (-5,5)-(-5,25); 2x3 array -> 5 copies",
            {"start": list(s)[:2], "end": list(e)[:2], "mirror": [list(M.dxf.start)[:2], list(M.dxf.end)[:2]] if M else None,
             "array_copies": arr.payload.get("copies"), "lines_in_file": n_lines},
            "PASS" if ok and mir_ok and arr.payload.get("copies") == 5 and n_lines == 7 else "FAIL")
        t1 = (await b.create_line(0, 100, 10, 100)).payload["handle"]
        t2 = (await b.create_line(7, 95, 7, 105)).payload["handle"]
        tr = await b.entity_trim(t1, t2)
        T = b._doc.entitydb[t1]
        rec("F2-trim", "F2", "line trimmed at boundary x=7", {"ok": tr.ok, "payload": tr.payload, "now": [list(T.dxf.start)[:2], list(T.dxf.end)[:2]]},
            "PASS" if tr.ok and close(T.dxf.end[0], 7, 1e-6) else "FAIL")
        un = [await b.entity_offset(l, 2), await b.entity_fillet(t1, t2, 1), await b.entity_chamfer(t1, t2, 1, 1)]
        rec("F2-unsupported", "F2", "offset/fillet/chamfer on ezdxf (report claims supported)", [{"ok": x.ok, "error": x.error} for x in un],
            "INFO")
        bad = await b.entity_move("NOPE", 1, 1)
        rec("F2-bad-handle", "F2", "ok=false on unknown handle", {"ok": bad.ok, "error": bad.error}, "PASS" if not bad.ok else "FAIL")
    await probe("F2", "F2", f2)

    # ---------------- F3 annotation ----------------
    async def f3():
        b = await fresh()
        rs = [await b.create_dimension_linear(0, 0, 25.4, 0, 10, 10),
              await b.create_dimension_aligned(0, 0, 30, 40, 5),
              await b.create_dimension_angular(0, 0, 10, 0, 0, 10),
              await b.create_dimension_radius(0, 0, 7.5, 45),
              await b.create_leader([[0, 0], [10, 10], [20, 10]], "NOTE"),
              await b.create_text(0, -10, "HELLO", 3.5)]
        path = os.path.join(W, "f3.dxf"); await b.drawing_save(path)
        d = reopen(path)
        dims = [x for x in d.modelspace() if x.dxftype() == "DIMENSION"]
        meas = []
        for x in dims:
            try: meas.append(round(x.get_measurement() if not hasattr(x.get_measurement(), "x") else 0, 4))
            except Exception as ex: meas.append(str(ex))
        texts = []
        for x in dims:
            blk = d.blocks.get(x.dxf.geometry) if x.dxf.hasattr("geometry") else None
            texts.append([t.plain_text() if t.dxftype() == "MTEXT" else t.dxf.text for t in (blk or []) if t.dxftype() in ("MTEXT", "TEXT")])
        ok = all(r.ok for r in rs) and len(dims) == 4
        rec("F3-dims", "F3", "4 dimensions + leader + text saved; rendered blocks show 25.4, 50, 90deg, R7.5",
            {"oks": [r.ok for r in rs], "measurements": meas, "rendered_texts": texts,
             "handles_returned": [bool(r.payload and r.payload.get("handle")) for r in rs[:4]]},
            "PASS" if ok else "FAIL")
    await probe("F3", "F3", f3)

    # ---------------- F4 organisation / exchange ----------------
    async def f4():
        b = await fresh()
        await b.layer_create("WALLS", "red"); await b.layer_freeze("WALLS"); await b.layer_lock("WALLS")
        await b.block_define("TAG", [{"type": "CIRCLE", "radius": 2}, {"type": "ATTDEF", "tag": "ID"}])
        ins = await b.block_insert_with_attributes("TAG", 5, 5, attributes={"ID": "P-101"})
        lc = await b.layout_create("SHEET2")
        ps = await b.layout_page_setup("SHEET2", paper_size="A4", orientation="portrait")
        vp = await b.layout_viewport_create(100, 100, 50, 40, scale=0.5)
        vs = await b.layout_viewport_set_scale("whatever", 0.25)
        vl = await b.layout_viewport_lock("whatever", True)
        bp = await b.layout_batch_plot(["SHEET2"], os.path.join(W, "plot.pdf"))
        path = os.path.join(W, "f4.dxf"); await b.drawing_save(path)
        d = reopen(path)
        Lw = d.layers.get("WALLS")
        I = [x for x in d.modelspace() if x.dxftype() == "INSERT"]
        attrs = {a.dxf.tag: a.dxf.text for a in I[0].attribs} if I else {}
        rec("F4-layers-blocks", "F4", "layer WALLS red/frozen/locked; INSERT TAG with ID=P-101 after reopen",
            {"layer": [Lw.dxf.color, Lw.is_frozen(), Lw.is_locked()], "insert_ok": ins.ok, "attrs": attrs, "layouts": d.layouts.names()},
            "PASS" if Lw.dxf.color == 1 and Lw.is_frozen() and Lw.is_locked() and attrs.get("ID") == "P-101" and "SHEET2" in d.layouts.names() else "FAIL")
        lay = d.layouts.get("SHEET2")
        rec("F4-page-setup-noop", "F4/C2", "page_setup either applies A4 portrait (210x297) or refuses; layout default is 420x297",
            {"ok": ps.ok, "payload": ps.payload, "saved_paper": [lay.dxf.paper_width, lay.dxf.paper_height, lay.dxf.plot_rotation]},
            "FAIL" if ps.ok else "PASS")
        vps = [x for x in d.layouts.get("Layout1") if x.dxftype() == "VIEWPORT"] if "Layout1" in d.layouts.names() else []
        rec("F4-viewport-noop", "F4/C2", "viewport scale/lock either applied or refused; batch_plot produces a file or refuses",
            {"vp_create": [vp.ok, vp.error], "set_scale": [vs.ok, vs.payload], "lock": [vl.ok, vl.payload], "batch_plot": [bp.ok, bp.payload],
             "plot_file_exists": os.path.exists(os.path.join(W, "plot.pdf")),
             "saved_viewports": [{"h": v.dxf.height, "vh": v.dxf.view_height} for v in vps]},
            "FAIL" if (vs.ok or vl.ok or bp.ok) else "PASS")
        wb = await b.drawing_wblock([I[0].dxf.handle] if I else [], os.path.join(W, "wb.dxf"))
        rec("F4-wblock", "F4", "wblock writes reopenable file", {"ok": wb.ok, "exists": os.path.exists(os.path.join(W, "wb.dxf"))}, "INFO")
    await probe("F4", "F4", f4)

    # ---------------- C1 batches / undo ----------------
    async def c1():
        b = await fresh()
        e0 = await b.batch_draw_lines([{"x1": 0, "y1": 0, "x2": 1, "y2": 1}])
        rec("C1-batch-empty-drawing", "C1/F1", "batch on a fresh (empty) drawing creates the line",
            {"ok": e0.ok, "error": e0.error, "entities": len(b._msp)}, "PASS" if e0.ok else "FAIL")
        await b.create_line(50, 50, 60, 60)
        r = await b.batch_draw_lines([{"x1": 0, "y1": 0, "x2": 1, "y2": 1}, {"x1": "bad", "y1": 0, "x2": 1, "y2": 1}])
        n = len(b._msp) - 1
        rec("C1-batch-partial", "C1", "batch with one invalid item fails as a whole or reports not-ok",
            {"ok": r.ok, "payload": r.payload, "entities_left": n}, "FAIL" if r.ok and n >= 1 else "PASS")
        u = await b.undo()
        rec("C1-undo", "C1", "undo refuses on ezdxf (can_undo=false)", {"ok": u.ok, "error": u.error}, "PASS" if not u.ok else "FAIL")
    await probe("C1", "C1", c1)

    # ---------------- C2 purge false success ----------------
    async def c2():
        b = await fresh()
        await b.layer_create("UNUSED"); b._doc.blocks.new("UNUSEDBLK")
        r = await b.drawing_purge()
        path = os.path.join(W, "c2.dxf"); await b.drawing_save(path)
        d = reopen(path)
        still = ["UNUSED" in d.layers, "UNUSEDBLK" in d.blocks]
        rec("C2-purge", "C2", "purge removes unused layer/block or refuses",
            {"ok": r.ok, "payload": r.payload, "still_present_after_reopen": still}, "FAIL" if r.ok and all(still) else "PASS")
    await probe("C2", "C2", c2)

    # ---------------- C3 save boundaries ----------------
    async def c3():
        b = await fresh()
        await b.create_line(0, 0, 1, 1)
        target = os.path.join(W, "existing.dxf")
        open(target, "w").write("precious user data\n")
        r = await b.drawing_save(target)
        rec("C3-overwrite", "C3/S1", "save refuses or warns before overwriting an existing non-DXF file",
            {"ok": r.ok, "file_head": open(target).read(20)}, "INFO")
        try:
            r2 = await b.drawing_save("/nonexistent_dir/x.dxf"); obs = {"ok": r2.ok, "error": r2.error}; v = "PASS" if not r2.ok else "FAIL"
        except Exception as ex:
            obs = f"raises {type(ex).__name__} (backend does not catch; server _safe wrapper converts)"; v = "INFO"
        rec("C3-bad-dir", "C3", "ok=false for unwritable path", obs, v)
        r3 = await b.drawing_save(os.path.join(W, "x.dwg"))
        head = open(os.path.join(W, "x.dwg"), "rb").read(6)
        rec("C3-dwg-ext", "C3", "saving to .dwg refuses or writes DWG", {"ok": r3.ok, "head": head.decode("latin1")},
            "FAIL" if r3.ok and not head.startswith(b"AC10") else "PASS")
    await probe("C3", "C3", c3)

    # ---------------- C4 foreign / abnormal ----------------
    async def c4():
        b = await fresh()
        m = await b.drawing_open(os.path.join(W, "missing.dxf"))
        bad = os.path.join(W, "corrupt.dxf"); open(bad, "w").write("0\nSECTION\n2\nENTITIES\n0\nLINE\n10\nnotanumber\n")
        c = await b.drawing_open(bad)
        st = await b.status()
        rec("C4-open-errors", "C4", "missing/corrupt files refused; previous document kept",
            {"missing": [m.ok, m.error], "corrupt": [c.ok, (c.error or "")[:120]], "has_document_after": st.payload.get("has_document")},
            "PASS" if not m.ok and not c.ok else "FAIL")
        b2 = await fresh(); await b2.create_line(0, 0, 1, 1)
        a0 = await b2.drawing_audit(fix=False)
        a = await b2.drawing_audit(fix=True)
        rec("C4-audit", "C4", "audit (fix=false and fix=true) returns issue list",
            {"fix_false": [a0.ok, a0.payload, a0.error], "fix_true": [a.ok, a.payload, a.error]}, "PASS" if a.ok and a0.ok else "FAIL")
        u = await b2.drawing_units(99)
        rec("C4-bad-units", "C4", "invalid $LUNITS value 99 refused", {"ok": u.ok, "payload": u.payload, "error": u.error}, "FAIL" if u.ok else "PASS")
    await probe("C4", "C4", c4)

    # ---------------- E1 standards data ----------------
    async def e1():
        b = await fresh()
        good = await b.electrical_voltage_drop(120, 20, "12", 100, 1)
        unk = await b.electrical_voltage_drop(120, 20, "999", 100, 1)
        # Expected for #12: 2*20*1.98*0.1 = 7.92 V
        rec("E1-vd-ordinary", "E1", "12 AWG, 20 A, 100 ft, 120 V -> 7.92 V", good.payload, "PASS" if good.ok and close(good.payload["voltage_drop"], 7.92, 0.01) else "FAIL")
        rec("E1-vd-unknown-gauge", "E1", "unknown gauge refused", {"ok": unk.ok, "payload": unk.payload}, "FAIL" if unk.ok else "PASS")
        t = await b.electrical_nec_lookup("bogus_table", {})
        rec("E1-unknown-table", "E1", "unknown table -> ok=false", {"ok": t.ok, "payload": t.payload}, "FAIL" if t.ok else "PASS")
        amp = await b.electrical_nec_lookup("wire_ampacity", {"wire_gauge": "999"})
        rec("E1-unknown-size", "E1", "unknown wire size refused", {"ok": amp.ok, "error": amp.error, "payload": amp.payload}, "PASS" if not amp.ok else "FAIL")
    await probe("E1", "E1", e1)

    # ---------------- E3 domain loop ----------------
    async def e3():
        b = await fresh()
        await b.create_line(0, 0, 10, 0); await b.create_line(10, 0, 10, 10); await b.create_line(20, 20, 30, 20)
        v = await b.validate_connectivity()
        await b.block_define("PUMP", [{"type": "CIRCLE", "radius": 2}])
        for x in range(3): await b.block_insert("PUMP", x * 10, 50)
        bom = await b.export_bom()
        rec("E3-connectivity-bom", "E3", "4 dangling endpoints (chain ends + isolated line); BOM PUMP=3",
            {"connectivity": {k: v.payload[k] for k in ("dangling_count", "total_endpoints")}, "bom": bom.payload},
            "PASS" if v.payload["dangling_count"] == 4 and "3" in json.dumps(bom.payload) else "FAIL")
    await probe("E3", "E3", e3)

    # ---------------- S1 dangerous ops / paths on headless ----------------
    async def s1():
        b = await fresh()
        x = await b.execute_lisp('(startapp "calc")')
        rec("S1-execute-lisp-ezdxf", "S1", "execute_lisp unavailable on ezdxf", {"ok": x.ok, "error": x.error}, "INFO")
        await b.create_line(0, 0, 1, 1)
        esc = os.path.join(W, "..", "escaped.dxf")
        r = await b.drawing_save(esc)
        rec("S1-path-scope", "S1", "save outside a workspace refused (no scope configured)", {"ok": r.ok, "written": os.path.realpath(esc)},
            "FAIL" if r.ok else "PASS")
    await probe("S1", "S1", s1)

    json.dump(R, open(OUT, "w"), indent=1, default=str)
    print("probes:", len(R), "PASS", sum(r["verdict"] == "PASS" for r in R), "FAIL", sum(r["verdict"] == "FAIL" for r in R))

asyncio.run(main())
