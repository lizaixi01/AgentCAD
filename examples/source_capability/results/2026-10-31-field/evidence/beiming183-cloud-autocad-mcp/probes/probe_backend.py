"""Headless probes against the pinned AutoCAD-MCP ezdxf backend.

Calls the backend API the MCP tools call, then re-reads saved DXF files with
ezdxf independently. Prints one JSON line per probe.
"""
import asyncio
import json
import math
import os
import sys
import traceback

import ezdxf

from autocad_mcp.backends.ezdxf_backend import EzdxfBackend

OUT = os.environ.get("PROBE_OUT", "/tmp/probe")
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def rec(pid, item, passed, detail):
    row = {"probe": pid, "item": item, "result": "pass" if passed else "fail", "detail": detail}
    RESULTS.append(row)
    print(json.dumps(row, default=str))


async def fresh():
    b = EzdxfBackend()
    await b.initialize()
    return b


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


async def p_f1_geometry():
    b = await fresh()
    await b.layer_create("OUTLINE")
    r_line = await b.create_line(0, 0, 30, 40, layer="OUTLINE")
    r_circ = await b.create_circle(100, 0, 5, layer="OUTLINE")
    r_rect = await b.create_rectangle(0, 100, 20, 110, layer="OUTLINE")
    r_arc = await b.create_arc(0, 0, 10, 0, 90, layer="OUTLINE")
    r_poly = await b.create_polyline([[0, 200], [10, 200], [10, 210]], closed=False, layer="OUTLINE")
    g_line = await b.entity_get(r_line.payload["handle"])
    g_circ = await b.entity_get(r_circ.payload["handle"])
    g_rect = await b.entity_get(r_rect.payload["handle"])
    g_arc = await b.entity_get(r_arc.payload["handle"])
    g_poly = await b.entity_get(r_poly.payload["handle"])
    detail = {
        "line_length": g_line.payload.get("length"),
        "circle_area": g_circ.payload.get("area"),
        "rect_area": g_rect.payload.get("area"),
        "rect_length": g_rect.payload.get("length"),
        "arc_length": g_arc.payload.get("length"),
        "poly_length": g_poly.payload.get("length"),
    }
    ok = (
        close(detail["line_length"] or -1, 50.0, 1e-6)
        and close(detail["circle_area"] or -1, math.pi * 25, 1e-4)
        and close(detail["rect_area"] or -1, 200.0, 1e-6)
        and close(detail["rect_length"] or -1, 60.0, 1e-6)
        and close(detail["arc_length"] or -1, 10 * math.pi / 2, 1e-4)
        and close(detail["poly_length"] or -1, 20.0, 1e-6)
    )
    rec("F1-measure", "F1", ok, detail)

    # hatch on closed rectangle with an inner island circle, saved and reopened
    outer = await b.create_rectangle(200, 0, 260, 40, layer="OUTLINE")
    h = await b.create_hatch(outer.payload["handle"], "ANSI31", 0.0, 2.0, "OUTLINE")
    hv = await b.entity_get(h.payload.get("handle")) if h.ok else None
    path = os.path.join(OUT, "f1.dxf")
    await b.drawing_save(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    types = sorted(e.dxftype() for e in msp)
    hatches = [e for e in msp if e.dxftype() == "HATCH"]
    line = [e for e in msp if e.dxftype() == "LINE"][0]
    reopened = {
        "types": types,
        "line_end": list(line.dxf.end)[:2],
        "hatch_pattern": hatches[0].dxf.pattern_name if hatches else None,
        "hatch_scale": hatches[0].dxf.pattern_scale if hatches else None,
        "hatch_paths": len(hatches[0].paths) if hatches else 0,
        "hatch_tool_ok": h.ok,
        "hatch_readback": (hv.payload if hv else None),
        "hatch_area_reported": (hv.payload.get("area") if hv else None),
    }
    ok2 = (
        h.ok and len(hatches) == 1 and reopened["hatch_pattern"] == "ANSI31"
        and close(reopened["hatch_scale"], 2.0) and reopened["line_end"] == [30.0, 40.0]
    )
    rec("F1-hatch-save-reopen", "F1", ok2, reopened)

    # error/boundary: bad handle, negative radius, missing layer, NaN
    from types import SimpleNamespace as NS

    async def call(coro):
        try:
            return await coro
        except Exception as exc:
            return NS(ok=False, error="raised " + repr(exc), error_code=type(exc).__name__)
    e1 = await call(b.entity_get("ZZZZ"))
    e2 = await call(b.create_circle(0, 0, -5))
    e3 = await call(b.create_line(0, 0, 1, 1, layer="NOPE"))
    e4 = await call(b.create_line(0, 0, float("nan"), 1))
    n_before = len(b._msp)
    detail = {
        "bad_handle": [e1.ok, e1.error],
        "neg_radius": [e2.ok, e2.error, e2.error_code],
        "missing_layer": [e3.ok, e3.error, e3.error_code],
        "nan_coord": [e4.ok, e4.error, e4.error_code],
    }
    rec("F1-errors", "F1", (not e1.ok) and (not e3.ok), detail)
    # record whether invalid geometry was accepted (boundary)
    rec("F1-neg-radius-accepted", "F1", not e2.ok, {"ok": e2.ok, "entities_now": len(b._msp)})
    rec("F1-nan-accepted", "F1", not e4.ok, {"ok": e4.ok})


async def p_f2_edit():
    b = await fresh()
    ln = (await b.create_line(0, 0, 10, 0)).payload["handle"]
    mv = await b.entity_move(ln, 5, 5)
    rt = await b.entity_rotate(ln, 0, 0, 90)
    sc = await b.entity_scale(ln, 0, 0, 2)
    g = await b.entity_get(ln)
    mi = await b.entity_mirror(ln, 0, 0, 0, 10)
    ar = await b.entity_array(ln, 2, 3, 10, 10)
    off = await b.entity_offset(ln, 1)
    fil = await b.entity_fillet(ln, ln, 1)
    bad = await b.entity_move("ZZZZ", 1, 1)
    path = os.path.join(OUT, "f2.dxf")
    await b.drawing_save(path)
    lines = [e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "LINE"]
    # expected: (0,0)-(10,0) -> move (5,5)-(15,5) -> rot90 about 0 -> (-5,5)-(-5,15) -> scale2 -> (-10,10)-(-10,30)
    start, end = g.payload["start"], g.payload["end"]
    detail = {
        "after_transforms": [start, end],
        "mirror_ok": mi.ok, "array": ar.payload if ar.ok else ar.error,
        "line_count_reopened": len(lines),
        "offset": [off.ok, off.error], "fillet": [fil.ok, fil.error],
        "bad_handle_move": [bad.ok, bad.error],
    }
    ok = (
        close(start[0], -10, 1e-6) and close(start[1], 10, 1e-6) and close(end[1], 30, 1e-6)
        and mi.ok and ar.ok and len(lines) == 1 + 1 + 5 and not bad.ok
    )
    rec("F2-transforms-reopen", "F2", ok, detail)


async def p_f3_annot():
    b = await fresh()
    d = await b.create_dimension_linear(0, 0, 37.5, 0, 18, -10)
    path = os.path.join(OUT, "f3.dxf")
    await b.drawing_save(path)
    dims = [e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "DIMENSION"]
    meas = None
    block_text = None
    if dims:
        try:
            meas = dims[0].get_measurement()
        except Exception as exc:  # pragma: no cover
            meas = repr(exc)
        blk = dims[0].get_geometry_block()
        if blk is not None:
            block_text = [e.dxf.text for e in blk if e.dxftype() in ("MTEXT", "TEXT")]
    rec("F3-dimension-reopen", "F3", d.ok and dims and close(float(meas), 37.5, 1e-6),
        {"tool_ok": d.ok, "measurement": meas, "rendered_text": block_text})


async def p_f4_blocks():
    b = await fresh()
    await b.layer_create("TAGS")
    lower = await b.block_define("LOWERBLK", [{"type": "circle", "cx": 0, "cy": 0, "radius": 5},
                                              {"type": "attdef", "tag": "TAG", "x": 0, "y": -7, "height": 2}])
    rec("F4-block-define-lowercase-silent-drop", "F4",
        bool(lower.ok and len(b._doc.blocks["LOWERBLK"]) == 0 and lower.payload["entity_count"] == 2),
        {"tool_ok": lower.ok, "reported_entity_count": lower.payload.get("entity_count"),
         "actual_block_entities": len(b._doc.blocks["LOWERBLK"]), "note": "pass = silent drop reproduced"})
    bd = await b.block_define("PUMPBLK", [{"type": "CIRCLE", "cx": 0, "cy": 0, "radius": 5},
                                          {"type": "ATTDEF", "tag": "TAG", "x": 0, "y": -7, "height": 2}])
    try:
        dup = await b.block_define("PUMPBLK", [])
        dup_out = [dup.ok, dup.error]
    except Exception as exc:
        dup_out = ["raised", repr(exc)]
    ins = await b.block_insert_with_attributes("PUMPBLK", 50, 50, attributes={"TAG": "P-101"})
    upd = await b.block_update_attribute(ins.payload["handle"], "TAG", "P-102") if ins.ok else None
    path = os.path.join(OUT, "f4.dxf")
    await b.drawing_save(path)
    doc = ezdxf.readfile(path)
    inserts = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    attribs = {a.dxf.tag: a.dxf.text for a in inserts[0].attribs} if inserts else {}
    missing = await b.block_insert("NOSUCH", 0, 0)
    rec("F4-block-attr-reopen", "F4", bd.ok and ins.ok and attribs.get("TAG") == "P-102" and not missing.ok,
        {"define": bd.ok, "insert": ins.ok, "update": upd.ok if upd else None, "reopened_attribs": attribs,
         "missing_block": [missing.ok, missing.error], "duplicate_define": dup_out, "layouts": doc.layout_names()})


async def p_c1_batch():
    b = await fresh()
    await b.layer_create("OUTLINE")
    before = len(b._msp)
    r = await b.create_batch([
        {"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0, "layer": "OUTLINE"},
        {"type": "circle", "cx": 0, "cy": 0, "radius": 3},
        {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "layer": "MISSING"},
    ], atomic=True)
    after = len(b._msp)
    path = os.path.join(OUT, "c1.dxf")
    await b.drawing_save(path)
    reopened = len(ezdxf.readfile(path).modelspace())
    rec("C1-atomic-missing-layer", "C1", (not r.ok) and after == before and reopened == before,
        {"error_code": r.error_code, "rolled_back": r.payload.get("rolled_back"), "before": before, "after": after,
         "reopened_count": reopened})
    r2 = await b.create_batch([
        {"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
        {"type": "circle", "cx": 0, "cy": 0, "radius": -3},
    ], atomic=True)
    rec("C1-atomic-invalid-radius", "C1", (not r2.ok) and len(b._msp) == before,
        {"ok": r2.ok, "error_code": r2.error_code, "entities": len(b._msp)})
    nonatomic = await b.create_batch([
        {"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
        {"type": "bogus"},
    ], atomic=False, continue_on_error=True)
    rec("C1-nonatomic-partial-reported", "C1", (not nonatomic.ok) and nonatomic.payload["failures"] == 1,
        {"ok": nonatomic.ok, "processed": nonatomic.payload["processed"], "entities": len(b._msp)})
    # revision/document fencing headless
    ctx = await b.document_context()
    stale = await b.require_document_context(ctx.payload.get("doc_id"), -5) if ctx.ok else None
    wrong = await b.require_document_context("not-a-doc", ctx.payload.get("revision", 0)) if ctx.ok else None
    rec("C1-revision-fence", "C1", bool(ctx.ok and stale is not None and not stale.ok and not wrong.ok),
        {"ctx": ctx.payload if ctx.ok else ctx.error, "stale": stale.error_code if stale else None,
         "wrong": wrong.error_code if wrong else None})


async def p_c2_contract():
    from autocad_mcp.contracts import EntityExpectation  # noqa
    b = await fresh()
    r = await b.create_batch([{"type": "line", "x1": 1, "y1": 2, "x2": 3, "y2": 4},
                              {"type": "circle", "cx": 5, "cy": 6, "radius": 7}], atomic=True)
    entries = r.payload.get("results", [])
    verified = [e.get("payload", {}).get("verified") for e in entries]
    diffs = [e.get("payload", {}).get("diff") for e in entries]
    rec("C2-readback-verified", "C2", r.ok and all(verified) and all(d == [] for d in diffs),
        {"verified": verified, "diffs": diffs})
    # Tamper: change geometry behind the tool's back, then audit; does the audit flag a change?
    a1 = await b.drawing_audit()
    h = entries[0]["payload"]["handle"]
    ent = b._doc.entitydb[h]
    ent.dxf.end = (300, 400)
    a2 = await b.drawing_audit()
    changes = a2.payload.get("changes") if a2.ok else None
    rec("C2-external-edit-detected", "C2", bool(a2.ok and a1.payload.get("geometry_digest") != a2.payload.get("geometry_digest")),
        {"digest_before": a1.payload.get("geometry_digest"), "digest_after": a2.payload.get("geometry_digest"),
         "changes": changes})


async def p_c4_foreign():
    b = await fresh()
    missing = await b.drawing_audit_dxf(os.path.join(OUT, "nope.dxf"))
    corrupt = os.path.join(OUT, "corrupt.dxf")
    with open(corrupt, "w") as f:
        f.write("0\nSECTION\n2\nENTITIES\n0\nLINE\n10\nnot-a-number\n")
    cr = None
    try:
        cr = await b.drawing_audit_dxf(corrupt)
        cr_out = [cr.ok, cr.error, getattr(cr, "error_code", None)]
    except Exception as exc:
        cr_out = ["raised", repr(exc)]
    op = None
    try:
        op = await b.drawing_open(corrupt)
        op_out = [op.ok, op.error]
    except Exception as exc:
        op_out = ["raised", repr(exc)]
    # foreign DXF with unknown entity type + inch units, written independently
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 1
    msp = doc.modelspace()
    msp.add_line((0, 0), (1, 1))
    msp.add_mesh()
    msp.add_spline([(0, 0), (1, 2), (3, 1), (4, 4)])
    fpath = os.path.join(OUT, "foreign.dxf")
    doc.saveas(fpath)
    fr = await b.drawing_audit_dxf(fpath)
    units = fr.payload.get("units") if fr.ok else None
    rec("C4-missing-file", "C4", not missing.ok, [missing.ok, missing.error])
    rec("C4-corrupt-file", "C4", cr_out[0] is False and (op_out[0] is False), {"audit_dxf": cr_out, "open": op_out})
    rec("C4-foreign-units-unknown", "C4", bool(fr.ok), {"ok": fr.ok, "units": units,
                                                       "types": (fr.payload or {}).get("counts_by_type") if fr.ok else fr.error})


async def p_f5_pid_defect():
    b = await fresh()
    await b.pid_setup_layers()
    r = await b.pid_insert_symbol("NO-SUCH-CATEGORY", "NO-SUCH-SYMBOL", 10, 10, rotation=45)
    path = os.path.join(OUT, "f5.dxf")
    await b.drawing_save(path)
    types = sorted(e.dxftype() for e in ezdxf.readfile(path).modelspace())
    lst = await b.pid_list_symbols("VALVES")
    rec("F5-pid-placeholder-success", "F5",
        # 'pass' here means the defect reproduced: ok=True for nonexistent symbol, no INSERT
        bool(r.ok and "INSERT" not in types),
        {"tool_ok": r.ok, "payload": r.payload, "reopened_types": types, "list_symbols": lst.payload if lst.ok else lst.error,
         "note": "pass = defect reproduced"})


async def p_e_mech():
    b = await fresh()
    from autocad_mcp import drafting  # noqa
    r = await b.drawing_setup_mechanical() if hasattr(b, "drawing_setup_mechanical") else None
    rec("E1-setup-mechanical", "E1", bool(r and r.ok), {"available": r is not None, "payload": (r.payload if r and r.ok else (r.error if r else None))})


async def p_delivery_headless():
    from autocad_mcp.delivery import deliver_drawing
    import inspect
    b = await fresh()
    await b.create_line(0, 0, 10, 0)
    sig = str(inspect.signature(deliver_drawing))
    try:
        res = await deliver_drawing(b, {"name": "probe", "validation": {"min_entities": 1}})
        out = {"ok": res.ok, "error": res.error, "code": res.error_code,
               "manifest_status": (res.payload or {}).get("status") if isinstance(res.payload, dict) else None}
    except Exception as exc:
        out = {"raised": repr(exc)}
    rec("C3-deliver-headless", "C3", bool(out.get("ok")), {"signature": sig, **out})


async def p_workspace():
    from autocad_mcp import workspace
    os.environ["AUTOCAD_MCP_OUTPUT_ROOT"] = os.path.join(OUT, "ws")
    t1 = workspace.resolve_output_target("/etc/evil.dxf", category="drawings", extension=".dxf")
    t2 = workspace.resolve_output_target("../../../../etc/evil2.dxf", category="drawings", extension=".dxf")
    root = os.path.realpath(os.path.join(OUT, "ws"))
    ok = str(t1.path).startswith(root) and os.path.realpath(str(t2.path)).startswith(root)
    rec("S1-output-containment", "S1", ok, {"abs": str(t1.path), "abs_redirected": t1.redirected,
                                            "traversal": str(t2.path), "traversal_redirected": t2.redirected})


async def main():
    for fn in [p_f1_geometry, p_f2_edit, p_f3_annot, p_f4_blocks, p_c1_batch, p_c2_contract, p_c4_foreign,
               p_f5_pid_defect, p_e_mech, p_delivery_headless, p_workspace]:
        try:
            await fn()
        except Exception as exc:
            rec(fn.__name__, "?", False, {"exception": repr(exc), "tb": traceback.format_exc()[-1500:]})
    with open(os.path.join(OUT, "probe_backend_results.json"), "w") as f:
        json.dump(RESULTS, f, indent=1, default=str)


asyncio.run(main())
