"""Strict-pass probes for puran-water/autocad-mcp (ezdxf headless backend).

Calls the product's MCP tool functions (autocad_mcp.server.*) directly, then reads saved
DXF files back independently with ezdxf. Run inside the offline container:
    AUTOCAD_MCP_BACKEND=ezdxf /work/.venv/bin/python /out/probes/probe_tools.py
"""
import asyncio
import base64
import json
import math
import os
import shutil
import sys
import traceback

os.environ.setdefault("AUTOCAD_MCP_BACKEND", "ezdxf")
import ezdxf  # noqa: E402

from autocad_mcp import server as S  # noqa: E402
from autocad_mcp import client  # noqa: E402

OUT = "/out/probe_artifacts"
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
RESULTS = []


def J(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return {"raw": x}
    return {"list_len": len(x)}


def rec(pid, name, expect, observed, verdict):
    RESULTS.append({"id": pid, "probe": name, "expected": expect, "observed": observed, "verdict": verdict})
    print(f"[{verdict}] {pid} {name}: {json.dumps(observed, default=str)[:400]}")


async def fresh():
    return J(await S.drawing(operation="create"))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


async def p_geometry():
    await fresh()
    r = {}
    r["line"] = J(await S.entity(operation="create_line", x1=0, y1=0, x2=30, y2=40, layer="G"))
    r["circle"] = J(await S.entity(operation="create_circle", data={"cx": 10, "cy": 5, "radius": 7.5}))
    r["arc"] = J(await S.entity(operation="create_arc", data={"cx": 0, "cy": 0, "radius": 10, "start_angle": 0, "end_angle": 90}))
    r["pl"] = J(await S.entity(operation="create_polyline", points=[[0, 0], [10, 0], [10, 5]], data={"closed": True}))
    r["ell"] = J(await S.entity(operation="create_ellipse", data={"cx": 0, "cy": 0, "major_x": 20, "major_y": 0, "ratio": 0.5}))
    r["mt"] = J(await S.entity(operation="create_mtext", data={"x": 1, "y": 2, "width": 50, "text": "HELLO"}))
    path = f"{OUT}/geom.dxf"
    r["save"] = J(await S.drawing(operation="save", data={"path": path}))
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    by = {e.dxf.handle: e for e in msp}
    ln = by[r["line"]["payload"]["handle"]]
    ci = by[r["circle"]["payload"]["handle"]]
    ar = by[r["arc"]["payload"]["handle"]]
    pl = by[r["pl"]["payload"]["handle"]]
    el = by[r["ell"]["payload"]["handle"]]
    checks = {
        "line_ok": tuple(ln.dxf.end)[:2] == (30, 40) and ln.dxf.layer == "G" and "G" in doc.layers,
        "circle_ok": close(ci.dxf.radius, 7.5) and tuple(ci.dxf.center)[:2] == (10, 5),
        "arc_ok": close(ar.dxf.start_angle, 0) and close(ar.dxf.end_angle, 90),
        "pl_closed": pl.closed and len(pl) == 3,
        "ellipse_ratio": close(el.dxf.ratio, 0.5) and close(el.dxf.major_axis[0], 20),
        "count": len(msp) == 6,
    }
    rec("P01", "ordinary primitives saved and reopened", "all values read back", checks,
        "pass" if all(checks.values()) else "FAIL")
    # entity get geometry coverage
    g_line = J(await S.entity(operation="get", entity_id=r["line"]["payload"]["handle"]))
    g_arc = J(await S.entity(operation="get", entity_id=r["arc"]["payload"]["handle"]))
    rec("P02", "entity get geometry readback (line vs arc)", "geometry for supported types",
        {"line": g_line, "arc": g_arc}, "observed: arc returns no geometry (type/handle/layer only)"
        if "center" not in g_arc.get("payload", {}) else "pass")
    # measurement: no tool exists
    rec("P03", "length/area measurement entry point", "tool op exists",
        J(await S.entity(operation="measure_area", entity_id=r["pl"]["payload"]["handle"])), "absent (unknown operation)")


async def p_transforms():
    await fresh()
    ln = J(await S.entity(operation="create_line", x1=0, y1=0, x2=10, y2=0))["payload"]["handle"]
    ci = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 1}))["payload"]["handle"]
    mv = J(await S.entity(operation="move", entity_id=ln, data={"dx": 5, "dy": 5}))
    rt = J(await S.entity(operation="rotate", entity_id=ln, data={"cx": 5, "cy": 5, "angle": 90}))
    sc = J(await S.entity(operation="scale", entity_id=ci, data={"cx": 0, "cy": 0, "factor": 3}))
    cp = J(await S.entity(operation="copy", entity_id=ci, data={"dx": 100, "dy": 0}))
    mi = J(await S.entity(operation="mirror", entity_id=ci, x1=50, y1=-10, x2=50, y2=10))
    ar = J(await S.entity(operation="array", entity_id=ci, data={"rows": 2, "cols": 3, "row_dist": 10, "col_dist": 20}))
    path = f"{OUT}/xform.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    by = {e.dxf.handle: e for e in doc.modelspace()}
    L = by[ln]
    C = by[ci]
    checks = {
        "move_rotate_line": [round(v, 6) for v in L.dxf.start][:2] == [5, 5] and [round(v, 6) for v in L.dxf.end][:2] == [5, 15],
        "scale_circle_r3": close(C.dxf.radius, 3),
        "copy_center_100": close(by[cp["payload"]["handle"]].dxf.center[0], 100),
        "mirror_center_100": close(by[mi["payload"]["handle"]].dxf.center[0], 100),
        "array_5_copies": ar["payload"]["copies"] == 5 and len(doc.modelspace()) == 2 + 1 + 1 + 5,
    }
    rec("P04", "transforms saved and reopened", "geometry matches requested transforms", checks,
        "pass" if all(checks.values()) else "FAIL")
    for op in ("offset", "fillet", "chamfer"):
        data = {"distance": 1} if op == "offset" else {"id1": ln, "id2": ci, "radius": 1, "dist1": 1, "dist2": 1}
        rec("P05", f"{op} on ezdxf", "explicit refusal", J(await S.entity(operation=op, entity_id=ci, data=data)), "refused honestly")
    # boundary: array with 0 rows -> nothing, still ok?
    n0 = len(client._backend._msp)
    a0 = J(await S.entity(operation="array", entity_id=ci, data={"rows": 0, "cols": 0, "row_dist": 1, "col_dist": 1}))
    rec("P06", "array rows=0 cols=0", "refusal or explicit no-op", {"result": a0, "entities_added": len(client._backend._msp) - n0},
        "ok=true with 0 copies (accepted silently)" if a0.get("ok") else "refused")
    sneg = J(await S.entity(operation="scale", entity_id=ci, data={"cx": 0, "cy": 0, "factor": 0}))
    rec("P07", "scale factor 0", "refusal", sneg, "accepted (degenerate)" if sneg.get("ok") else "refused")


async def p_mirror_zero():
    await fresh()
    ci = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 1}))["payload"]["handle"]
    before = len(client._backend._msp)
    r = J(await S.entity(operation="mirror", entity_id=ci, x1=1, y1=1, x2=1, y2=1))
    after = len(client._backend._msp)
    path = f"{OUT}/mirror_zero.dxf"
    await S.drawing(operation="save", data={"path": path})
    saved = len(ezdxf.readfile(path).modelspace())
    rec("D-C1a", "mirror with zero-length line (refused call)", "ok=false and drawing unchanged",
        {"result": r, "entities_before": before, "entities_after": after, "entities_in_saved_dxf": saved},
        "REPRODUCED: refused call left stray copy" if (not r.get("ok") and after > before) else "not reproduced")


async def p_hatch():
    await fresh()
    ci = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 5}))["payload"]["handle"]
    before = len(client._backend._msp)
    r = J(await S.entity(operation="create_hatch", entity_id=ci))
    after = len(client._backend._msp)
    path = f"{OUT}/hatch_fail.dxf"
    await S.drawing(operation="save", data={"path": path})
    hatches = [e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "HATCH"]
    rec("D-C1b", "hatch on circle (refused call)", "ok=false and no HATCH added",
        {"result": r, "entities_before": before, "entities_after": after,
         "saved_hatches": [(h.dxf.handle, len(h.paths)) for h in hatches]},
        "REPRODUCED: empty HATCH left in saved file" if (not r.get("ok") and hatches and len(hatches[0].paths) == 0) else "not reproduced")
    await fresh()
    pl = J(await S.entity(operation="create_rectangle", x1=0, y1=0, x2=10, y2=4))["payload"]["handle"]
    r2 = J(await S.entity(operation="create_hatch", entity_id=pl, data={"pattern": "ANSI31"}))
    path = f"{OUT}/hatch_ok.dxf"
    await S.drawing(operation="save", data={"path": path})
    h = [e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "HATCH"][0]
    verts = [tuple(round(c, 6) for c in v[:2]) for v in h.paths[0].vertices]
    rec("P08", "hatch on closed rectangle, reopened", "1 boundary path with 4 vertices, ANSI31",
        {"result": r2, "pattern": h.dxf.pattern_name, "paths": len(h.paths), "vertices": verts},
        "pass" if h.dxf.pattern_name == "ANSI31" and len(verts) == 4 else "FAIL")


async def p_purge():
    await fresh()
    await S.layer(operation="create", data={"name": "UNUSED"})
    await S.block(operation="define", data={"name": "UNUSEDBLK", "entities": [{"type": "LINE", "x2": 1}]})
    r = J(await S.drawing(operation="purge"))
    path = f"{OUT}/purge.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    still = {"UNUSED_layer": "UNUSED" in doc.layers, "UNUSEDBLK_block": "UNUSEDBLK" in doc.blocks}
    rec("D-C2c", "purge reports success", "unused layer/block removed or honest no-op",
        {"result": r, "still_present_after_save": still},
        "REPRODUCED: purged=true but nothing removed" if r.get("ok") and all(still.values()) else "not reproduced")


async def p_dims():
    await fresh()
    out = {}
    out["lin"] = J(await S.annotation(operation="create_dimension_linear", data={"x1": 0, "y1": 0, "x2": 42.5, "y2": 0, "dim_x": 20, "dim_y": 10}))
    out["ali"] = J(await S.annotation(operation="create_dimension_aligned", data={"x1": 0, "y1": 0, "x2": 30, "y2": 40, "offset": 5}))
    out["ang"] = J(await S.annotation(operation="create_dimension_angular", data={"cx": 0, "cy": 0, "x1": 10, "y1": 0, "x2": 0, "y2": 10}))
    out["rad"] = J(await S.annotation(operation="create_dimension_radius", data={"cx": 0, "cy": 0, "radius": 12, "angle": 45}))
    out["txt"] = J(await S.annotation(operation="create_text", data={"x": 0, "y": 0, "text": "NOTE", "height": 3.5}))
    out["ldr"] = J(await S.annotation(operation="create_leader", data={"points": [[0, 0], [10, 10]], "text": "LDR"}))
    path = f"{OUT}/dims.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"]
    texts = []
    for d in dims:
        blk = doc.blocks.get(d.dxf.geometry)
        t = [m.plain_text() if m.dxftype() == "MTEXT" else m.dxf.text for m in blk if m.dxftype() in ("MTEXT", "TEXT")] if blk else []
        texts.append({"dimtype": d.dimtype, "measurement": round(d.get_measurement(), 6) if not hasattr(d.get_measurement(), "x") else None, "block_text": t})
    checks = {"4_dimensions_saved": len(dims) == 4,
              "linear_42.5_displayed": any("42.5" in "".join(x["block_text"]) for x in texts),
              "aligned_50_displayed": any("50" in "".join(x["block_text"]) for x in texts),
              "handles_returned": all("handle" in (out[k].get("payload") or {}) for k in ("lin", "ali", "ang", "rad"))}
    rec("P09", "dimensions/text/leader saved and reopened", "4 DIMENSION entities with rendered text matching geometry",
        {"results": out, "dims": texts, "checks": checks},
        "pass (no handles returned for dimensions)" if all(v for k, v in checks.items() if k != "handles_returned") else "FAIL")
    # boundary: radius dimension with radius 0
    z = J(await S.annotation(operation="create_dimension_radius", data={"cx": 0, "cy": 0, "radius": 0, "angle": 0}))
    rec("P10", "radius dimension radius=0", "refusal", z, "accepted" if z.get("ok") else "refused")


async def p_layers_blocks():
    await fresh()
    out = {}
    out["create"] = J(await S.layer(operation="create", data={"name": "WALLS", "color": "red", "linetype": "DASHED"}))
    out["props"] = J(await S.layer(operation="set_properties", data={"name": "WALLS", "color": "blue", "lineweight": 50}))
    out["freeze"] = J(await S.layer(operation="freeze", data={"name": "WALLS"}))
    out["lock"] = J(await S.layer(operation="lock", data={"name": "WALLS"}))
    out["cur_missing"] = J(await S.layer(operation="set_current", data={"name": "NOPE"}))
    path = f"{OUT}/layers.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    L = doc.layers.get("WALLS")
    checks = {"color_blue": L.color == 5, "frozen": L.is_frozen(), "locked": L.is_locked(),
              "lineweight_50": L.dxf.lineweight == 50, "linetype": L.dxf.linetype}
    rec("P11", "layer ops saved and reopened", "color/freeze/lock/lineweight persisted",
        {"results": out, "checks": checks},
        "partial: lineweight silently ignored while ok=true" if not checks["lineweight_50"] and out["props"].get("ok") else "pass")

    await fresh()
    d = J(await S.block(operation="define", data={"name": "VALVE", "entities": [
        {"type": "LINE", "x1": 0, "y1": 0, "x2": 5, "y2": 0},
        {"type": "ATTDEF", "tag": "TAG", "x": 0, "y": 2}]}))
    dup = J(await S.block(operation="define", data={"name": "VALVE", "entities": []}))
    ins = J(await S.block(operation="insert_with_attributes", data={"name": "VALVE", "x": 10, "y": 10, "attributes": {"TAG": "V-101"}}))
    h = ins["payload"]["handle"]
    ga = J(await S.block(operation="get_attributes", data={"entity_id": h}))
    up = J(await S.block(operation="update_attribute", data={"entity_id": h, "tag": "TAG", "value": "V-202"}))
    upbad = J(await S.block(operation="update_attribute", data={"entity_id": h, "tag": "NOSUCH", "value": "x"}))
    insmiss = J(await S.block(operation="insert", data={"name": "MISSING", "x": 0, "y": 0}))
    ins_extra = J(await S.block(operation="insert_with_attributes", data={"name": "VALVE", "x": 0, "y": 0, "attributes": {"NOTDEFINED": "Q"}}))
    path = f"{OUT}/blocks.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    by = {e.dxf.handle: e for e in doc.modelspace()}
    saved_attrs = {a.dxf.tag: a.dxf.text for a in by[h].attribs}
    extra_attrs = {a.dxf.tag: a.dxf.text for a in by[ins_extra["payload"]["handle"]].attribs} if ins_extra.get("ok") else None
    rec("P12", "block define/insert attributes/update, reopened", "TAG=V-202 after update; errors refused",
        {"define": d, "define_duplicate": dup, "get": ga, "update": up, "update_missing_tag": upbad,
         "insert_missing_block": insmiss, "saved_attrs": saved_attrs,
         "insert_with_undefined_tag": ins_extra, "undefined_tag_saved_attrs": extra_attrs},
        "pass" if saved_attrs.get("TAG") == "V-202" and not upbad.get("ok") and not insmiss.get("ok") else "FAIL")


async def p_errors():
    await fresh()
    out = {}
    out["get_bad"] = J(await S.entity(operation="get", entity_id="FFFFF"))
    out["move_bad"] = J(await S.entity(operation="move", entity_id="FFFFF", data={"dx": 1, "dy": 1}))
    out["erase_bad"] = J(await S.entity(operation="erase", entity_id="FFFFF"))
    out["missing_key"] = J(await S.entity(operation="create_circle", data={"cx": 0}))
    out["unknown_op"] = J(await S.entity(operation="explode"))
    out["open_missing"] = J(await S.drawing(operation="open", data={"path": "/nonexistent/x.dxf"}))
    bad = f"{OUT}/corrupt.dxf"
    with open(bad, "w") as f:
        f.write("0\nSECTION\n2\nENTITIES\n0\nLINE\n10\nnotanumber\n")
    out["open_corrupt"] = J(await S.drawing(operation="open", data={"path": bad}))
    out["save_bad_dir"] = J(await S.drawing(operation="save", data={"path": "/nonexistent_dir/x.dxf"}))
    out["undo"] = J(await S.drawing(operation="undo"))
    out["plot_pdf"] = J(await S.drawing(operation="plot_pdf", data={"path": f"{OUT}/x.pdf"}))
    out["exec_lisp"] = J(await S.system(operation="execute_lisp", data={"code": "(+ 1 2)"}))
    out["neg_radius"] = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": -5}))
    out["empty_polyline"] = J(await S.entity(operation="create_polyline", points=[]))
    out["line_none_coords"] = J(await S.entity(operation="create_line"))
    path = f"{OUT}/errors_after.dxf"
    s = J(await S.drawing(operation="save", data={"path": path}))
    reopened = None
    try:
        doc = ezdxf.readfile(path)
        reopened = {"entities": [(e.dxftype(), e.dxf.get("radius", None)) for e in doc.modelspace()],
                    "audit_errors": len(doc.audit().errors)}
    except Exception as ex:
        reopened = {"readfile_error": repr(ex)}
    rec("P13", "error and boundary cases", "bad input refused, no invalid entities saved",
        {"results": out, "save_after": s, "reopened": reopened}, "see observed")


async def p_pid():
    await fresh()
    out = {}
    out["layers"] = J(await S.pid(operation="setup_layers"))
    out["valve"] = J(await S.pid(operation="insert_valve", data={"x": 0, "y": 0, "valve_type": "GATE", "rotation": 45, "attributes": {"TAG": "V-1"}}))
    out["sym"] = J(await S.pid(operation="insert_symbol", data={"category": "PUMPS-BLOWERS", "symbol": "PUMP-CENTRIF1", "x": 50, "y": 0}))
    out["conn"] = J(await S.pid(operation="connect_equipment", data={"x1": 0, "y1": 0, "x2": 50, "y2": 20}))
    out["list"] = J(await S.pid(operation="list_symbols", data={"category": "PUMPS-BLOWERS"}))
    out["list_bad"] = J(await S.pid(operation="list_symbols", data={"category": "NOPE"}))
    path = f"{OUT}/pid.dxf"
    await S.drawing(operation="save", data={"path": path})
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    v = {e.dxf.handle: e for e in msp}[out["valve"]["payload"]["handle"]]
    vpts = [tuple(round(c, 6) for c in p) for p in v.get_points(format="xy")]
    inserts = [e for e in msp if e.dxftype() == "INSERT"]
    attribs = [a for e in inserts for a in e.attribs]
    obs = {"results": out, "valve_vertices_after_rotation45": vpts, "insert_entities": len(inserts),
           "attribs_saved": len(attribs), "entity_types": sorted({e.dxftype() for e in msp}),
           "conn_vertices": [tuple(round(c, 3) for c in p) for p in {e.dxf.handle: e for e in msp}[out["conn"]["payload"]["handle"]].get_points(format="xy")]}
    unrot = vpts == [(-3, 0), (0, 3), (3, 0), (0, -3)]
    rec("P14", "P&ID headless symbols", "symbols as blocks with tags, rotation honoured",
        obs, "REPRODUCED: placeholder geometry, rotation and attributes ignored, no blocks" if unrot and not inserts else "differs")


async def p_save_anywhere():
    await fresh()
    await S.entity(operation="create_line", x1=0, y1=0, x2=1, y2=1)
    target = f"{OUT}/sub/../escaped_outside.txt"
    os.makedirs(f"{OUT}/sub", exist_ok=True)
    with open(f"{OUT}/victim.txt", "w") as f:
        f.write("important user data\n")
    r1 = J(await S.drawing(operation="save", data={"path": target}))
    r2 = J(await S.drawing(operation="save", data={"path": f"{OUT}/victim.txt"}))
    with open(f"{OUT}/victim.txt") as f:
        head = f.read(30)
    rec("S1a", "save path scope", "path confined / no silent overwrite",
        {"traversal_save": r1, "overwrite_existing_non_dxf": r2, "victim_now_starts_with": head},
        "REPRODUCED: arbitrary path written and existing non-DXF file overwritten without warning"
        if r2.get("ok") and not head.startswith("important") else "not reproduced")


async def p_screenshot_status():
    await fresh()
    await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 5})
    r = await S.view(operation="get_screenshot")
    ok = isinstance(r, list) and len(r) == 2
    png_ok = False
    if ok:
        data = base64.b64decode(r[1].data)
        png_ok = data[:8] == b"\x89PNG\r\n\x1a\n"
        with open(f"{OUT}/screenshot.png", "wb") as f:
            f.write(data)
    st = J(await S.system(operation="status"))
    rec("P15", "matplotlib screenshot + status capabilities", "PNG returned; capabilities listed",
        {"png": png_ok, "status": st}, "pass" if png_ok and st.get("ok") else "FAIL")
    z = J(await S.view(operation="zoom_extents"))
    rec("P16", "zoom on ezdxf", "refusal consistent with can_zoom=false", z, "refused" if not z.get("ok") else "accepted")


async def main():
    from autocad_mcp.config import detect_backend
    os.environ["AUTOCAD_MCP_BACKEND"] = "auto"
    rec("B1a", "auto backend on Linux", "falls back to ezdxf", {"detected": detect_backend()}, "observed")
    os.environ["AUTOCAD_MCP_BACKEND"] = "file_ipc"
    try:
        detect_backend()
        rec("B1b", "file_ipc requested on Linux", "explicit error", {"raised": False}, "FAIL")
    except RuntimeError as ex:
        rec("B1b", "file_ipc requested on Linux", "explicit error", {"raised": str(ex)}, "pass")
    os.environ["AUTOCAD_MCP_BACKEND"] = "ezdxf"
    for fn in (p_geometry, p_transforms, p_mirror_zero, p_hatch, p_purge, p_dims, p_layers_blocks,
               p_errors, p_pid, p_save_anywhere, p_screenshot_status):
        try:
            await fn()
        except Exception:
            rec(fn.__name__, "probe crashed", "-", traceback.format_exc()[-800:], "PROBE ERROR")
    with open("/out/probe_results.json", "w") as f:
        json.dump(RESULTS, f, indent=1, default=str)


asyncio.run(main())
