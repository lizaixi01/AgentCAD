"""Industry libraries as operations: P&ID symbols and lines, GD&T annotations, ISO standard holes and parts.

One op replaces the dozens of primitive ops each of these takes by hand. Sizes of annotation symbols follow the
drawing's annotation scale (a 3.5 mm GD&T frame text stays 3.5 mm on paper at 1:50); standard parts and holes
are true size. The data (dimensions, symbol geometry) lives in stdlib.py.
"""
from __future__ import annotations

import math
import re
from typing import Any

from ezdxf.enums import TextEntityAlignment

from .. import stdlib as L
from ..errors import geometry_error, input_error
from ..model import select
from ..units import UNITS
from .registry import Ctx, Param, check_tag, op

P = Param
SIZES = list(L.CLEARANCE)


# --- helpers ---------------------------------------------------------------------------------------------------
def _per_mm(ctx: Ctx) -> float:
    """Drawing units per millimetre."""
    return 1.0 / UNITS[ctx.unit][1] if ctx.unit in UNITS else 1.0


def _anno(ctx: Ctx) -> float:
    """Drawing units per paper millimetre: unit conversion times the annotation scale ($DIMSCALE)."""
    return _per_mm(ctx) * float(ctx.doc.header.get("$DIMSCALE", 1.0) or 1.0)


def _xf(pt, ins, s: float, rot: float) -> tuple[float, float]:
    c, si = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    x, y = pt[0] * s, pt[1] * s
    return ins[0] + x * c - y * si, ins[1] + x * si + y * c


def draw_prims(ctx: Ctx, space, prims, ins=(0.0, 0.0), s: float = 1.0, rot: float = 0.0,
               attrs: dict | None = None) -> list:
    """Draw stdlib primitives into ``space`` (a layout or block) placed at ``ins``, scaled and rotated."""
    out = []
    base = dict(attrs or {})
    for prim in prims:
        extra = prim[-1] if isinstance(prim[-1], dict) else {}
        a = {**base, **{k: v for k, v in extra.items() if k != "linetype" or v in ctx.doc.linetypes}}
        kind = prim[0]
        if kind == "line":
            out.append(space.add_line(_xf(prim[1], ins, s, rot), _xf(prim[2], ins, s, rot), dxfattribs=a))
        elif kind == "poly":
            out.append(space.add_lwpolyline([_xf(q, ins, s, rot) for q in prim[1]], close=prim[2], dxfattribs=a))
        elif kind == "circle":
            out.append(space.add_circle(_xf(prim[1], ins, s, rot), prim[2] * s, dxfattribs=a))
        elif kind == "arc":
            out.append(space.add_arc(_xf(prim[1], ins, s, rot), prim[2] * s, prim[3] + rot, prim[4] + rot,
                                     dxfattribs=a))
        elif kind == "ellipse":
            _, c, rx, ry, a0, a1 = prim[:6]
            if rx >= ry:
                major, ratio, shift = (rx * s * math.cos(math.radians(rot)), rx * s * math.sin(math.radians(rot))), ry / rx, 0
            else:
                ang = math.radians(rot + 90)
                major, ratio, shift = (ry * s * math.cos(ang), ry * s * math.sin(ang)), rx / ry, 90
            out.append(space.add_ellipse(_xf(c, ins, s, rot), major_axis=(*major, 0), ratio=ratio,
                                         start_param=math.radians(a0 - shift), end_param=math.radians(a1 - shift),
                                         dxfattribs=a))
        elif kind in ("fill", "disc"):
            color = a.pop("color", 256)
            h = space.add_hatch(color=color, dxfattribs=a)
            h.set_solid_fill(color=color, style=0)
            if kind == "fill":
                h.paths.add_polyline_path([_xf(q, ins, s, rot) for q in prim[1]], is_closed=True, flags=3)
            else:
                h.paths.add_edge_path(1).add_arc(_xf(prim[1], ins, s, rot), prim[2] * s, 0, 360)
            out.append(h)
        else:  # pragma: no cover - library data error
            raise ValueError(kind)
    return out


def _text(space, text: str, at, height: float, align: TextEntityAlignment, attrs: dict, rot: float = 0.0):
    t = space.add_text(text, height=height, rotation=rot, dxfattribs={**attrs, "style": "Standard"})
    t.set_placement(at, align=align)
    return t


def _finish_all(ctx: Ctx, ents: list, p: dict) -> list[str]:
    """Created entities that together form one annotation share its tag."""
    return [ctx.finish(e, p) for e in ents]


def _layer_default(ctx: Ctx, p: dict, name: str, **props) -> dict:
    q = dict(p)
    if not q.get("layer"):
        q["layer"] = name
        if name not in ctx.doc.layers:
            lt = props.pop("linetype", None)
            ctx.doc.layers.add(name, linetype=lt if lt and lt in ctx.doc.linetypes else "Continuous", **props)
    return q


def check_group(ctx: Ctx, p: dict) -> list[str] | None:
    """check_tag for ops that tag several entities '<tag>' and '<tag>.<suffix>': 'skip' returns the whole group,
    'replace' removes the whole group, 'error' reports any of it."""
    tag = p.get("tag")
    if not tag:
        return None
    group = [e for t, ents in ctx.tags().items() if t == tag or t.startswith(tag + ".") for e in ents]
    if not group:
        return None
    mode = p.get("if_tag_exists") or "error"
    if mode == "skip":
        return [e.dxf.handle for e in group]
    if mode == "replace":
        for e in group:
            if e.is_alive:
                ctx.removed(e)
        for t in [t for t in ctx.tags() if t == tag or t.startswith(tag + ".")]:
            ctx.tags().pop(t, None)
        return None
    raise input_error("TAG_EXISTS", f"Entities tagged {tag!r} (or {tag + '.*'!r}) already exist",
                      entities=[e.dxf.handle for e in group][:50],
                      hint="Use if_tag_exists='skip' for idempotent replays or 'replace' to redraw them")


def _check_size(size: str, sizes: list[str], what: str) -> None:
    if size not in sizes:
        raise input_error("INVALID_SIZE", f"No {what} size {size!r}", hint=f"Sizes: {sizes}")


# --- P&ID ----------------------------------------------------------------------------------------------------------
def _pid_block(ctx: Ctx, symbol: str) -> str:
    name = "PID_" + symbol.upper()
    if name in ctx.doc.blocks:
        return name
    d = L.PID[symbol]
    blk = ctx.doc.blocks.new(name, base_point=(0, 0))
    draw_prims(ctx, blk, d["prims"])
    mid = TextEntityAlignment.MIDDLE_CENTER
    if d.get("instrument"):
        for tag, y in (("FUNC", 0.14), ("LOOP", -0.2)):
            a = blk.add_attdef(tag, (0, y), height=0.25)
            a.set_placement((0, y), align=mid)
    elif not d.get("no_tag"):
        y = d.get("tag_y", -0.6)
        a = blk.add_attdef("TAG", (0, y), height=0.25)
        a.set_placement((0, y), align=mid)
    return name


def _split_instrument_tag(tag_no: str) -> dict[str, str]:
    m = re.match(r"^\s*([A-Za-z]+)[\s\-_]*(\S*)\s*$", tag_no)
    return {"FUNC": m.group(1).upper(), "LOOP": m.group(2)} if m else {"FUNC": tag_no, "LOOP": ""}


PIPE_ATTRS = ("layer", "color", "linetype", "lineweight", "ltscale", "true_color", "transparency", "elevation",
              "extrusion", "const_width")
EPS = 1e-9


def _break_for_symbol(ctx: Ctx, e, at, half: float) -> tuple[tuple, float, tuple, tuple, list[str]]:
    """Cut a gap of 2*half into a LINE or open LWPOLYLINE around the point nearest ``at``. Returns the gap
    centre, the pipe direction (degrees), the two gap ends and ids of new pieces. A side of the gap with nothing
    left (symbol at a pipe end) leaves no piece; a gap ending on a vertex adds no duplicate vertex."""
    t = e.dxftype()
    from ..model import get_tag
    keep = {"tag": get_tag(e)} if get_tag(e) else {}  # every piece keeps the pipe's tag: 'on' still finds it
    space = ctx.space_of(e)
    if t == "LINE":
        segs = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))]
    elif t == "LWPOLYLINE":
        if e.closed:
            raise input_error("UNSUPPORTED_ENTITY", "Symbols go on open lines; this polyline is closed",
                              entities=[e.dxf.handle])
        pts = [tuple(q) for q in e.get_points("xyseb")]
        segs = [((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1])) for i in range(len(pts) - 1)]
    else:
        raise input_error("UNSUPPORTED_ENTITY", "'on' must be a LINE or an open LWPOLYLINE (a pipe)",
                          entities=[e.dxf.handle])
    best = None
    for i, (a, b) in enumerate(segs):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        if ln < 1e-12:
            continue
        u = max(0.0, min(ln, ((at[0] - a[0]) * dx + (at[1] - a[1]) * dy) / ln))
        q = (a[0] + dx / ln * u, a[1] + dy / ln * u)
        dist = math.hypot(at[0] - q[0], at[1] - q[1])
        if best is None or dist < best[0]:
            best = (dist, i, u, ln, (dx / ln, dy / ln))
    if best is None:
        raise geometry_error("DEGENERATE_GEOMETRY", "The pipe has no length", entities=[e.dxf.handle])
    _, i, u, ln, (ux, uy) = best
    if t == "LWPOLYLINE" and abs(pts[i][4]) > 1e-12:
        raise input_error("UNSUPPORTED_ENTITY", "Symbols go on straight pipe segments; this one is an arc",
                          entities=[e.dxf.handle])
    if ln < 2 * half - EPS:
        raise geometry_error("SYMBOL_DOES_NOT_FIT", f"The pipe segment is {ln:g} long, the symbol needs {2 * half:g}",
                             entities=[e.dxf.handle], hint="Use a smaller 'size' or a longer segment")
    u = max(half, min(ln - half, u))  # keep the symbol on the segment
    a, b = segs[i]
    g0 = (a[0] + ux * (u - half), a[1] + uy * (u - half))
    g1 = (a[0] + ux * (u + half), a[1] + uy * (u + half))
    centre = (a[0] + ux * u, a[1] + uy * u)
    attrs = {k: e.dxf.get(k) for k in PIPE_ATTRS if e.dxf.hasattr(k)}
    new: list[str] = []
    if t == "LINE":
        start, end = segs[0]
        before, after = math.dist(start, g0) > EPS, math.dist(g1, end) > EPS
        if before:
            e.dxf.end = (*g0, 0)
            ctx.touched(e)
        elif after:
            e.dxf.start = (*g1, 0)  # nothing before the symbol: the line keeps only its far part
            ctx.touched(e)
            after = False
        else:
            ctx.removed(e)  # the symbol covers the whole line
        if after:
            new.append(ctx.finish(space.add_line(g1, end, dxfattribs=attrs), keep))
        return centre, math.degrees(math.atan2(uy, ux)), g0, g1, new
    head = pts[:i + 1]
    first = head if math.dist(head[-1][:2], g0) <= EPS else [*head, (g0[0], g0[1], 0.0, 0.0, 0.0)]
    tail = pts[i + 1:]
    second = tail if math.dist(tail[0][:2], g1) <= EPS else [(g1[0], g1[1], 0.0, 0.0, 0.0), *tail]

    def has_length(q) -> bool:
        return len(q) >= 2 and any(math.dist(q[j][:2], q[j + 1][:2]) > EPS for j in range(len(q) - 1))
    first = [(*v[:4], 0.0) if j == len(first) - 1 else v for j, v in enumerate(first)]  # the cut end is straight
    if has_length(first):
        e.set_points(first, format="xyseb")
        ctx.touched(e)
        if has_length(second):
            n = space.add_lwpolyline(second, format="xyseb", dxfattribs=attrs)
            new.append(ctx.finish(n, keep))
    elif has_length(second):
        e.set_points(second, format="xyseb")  # nothing before the symbol: the pipe keeps only its far part
        ctx.touched(e)
    else:
        ctx.removed(e)
    return centre, math.degrees(math.atan2(uy, ux)), g0, g1, new


def _distance(e, pt) -> float:
    if e.dxftype() == "LINE":
        pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    else:
        pts = [(q[0], q[1]) for q in e.get_points("xy")]
    best = math.inf
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln2 = dx * dx + dy * dy
        u = 0.0 if ln2 < 1e-24 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / ln2))
        best = min(best, math.hypot(pt[0] - a[0] - dx * u, pt[1] - a[1] - dy * u))
    return best


@op("add_pid_symbol", "library", "P&ID symbol (ISO 10628 / ISA-5.1 style) as a block with a TAG attribute "
    "(instruments: FUNC and LOOP, from tag_no 'FIC-101'). With 'on' (a pipe: LINE or open LWPOLYLINE) an inline "
    "symbol (valves, reducer, flange, strainer, orifice) is placed on the pipe at the point nearest 'insert' "
    "(default its middle), turned along it, and the pipe is cut where the symbol sits. 'size' is the symbol "
    "width (default 10 mm on paper). See standard_library for the symbol list.",
    {"symbol": P("enum", True, enum=sorted(L.PID)), "insert": P("point", description="Position (or point near "
                                                                    "the pipe with 'on')"),
     "on": P("selector", description="Pipe to put an inline symbol on"),
     "rotation": P("angle", default=0.0, description="Rotation; with 'on' added to the pipe direction (180 "
                                                     "reverses a check valve)"),
     "size": P("length", gt=0, description="Symbol width"), "tag_no": P("string", description="Tag number, "
                                                                          "e.g. 'V-101' or 'FIC-101'")},
    common_draw=True)
def add_pid_symbol(ctx: Ctx, symbol, insert, on, rotation, size, tag_no, **p):
    if on is not None and p.get("if_tag_exists") == "replace" and p.get("tag") and ctx.tags().get(p["tag"]):
        raise input_error("REPLACE_NOT_SUPPORTED", "Replacing a symbol placed on a pipe would leave its old gap in "
                          "the pipe", entities=[e.dxf.handle for e in ctx.tags()[p["tag"]]],
                          hint="Use if_tag_exists='skip' to replay, or delete the symbol, close the gap (join) and "
                               "place it again")
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    d = L.PID[symbol]
    size = size or d.get("default_size", L.PID_DEFAULT_SIZE) * _anno(ctx)
    q = _layer_default(ctx, p, "PID", color=7, lineweight=35)
    space, rot, new, out = ctx.layout, rotation, [], {}
    if on is not None:
        if not d["inline"]:
            raise input_error("NOT_INLINE", f"{symbol} is not an inline symbol; place it with 'insert'",
                              hint="Inline: " + ", ".join(k for k, v in L.PID.items() if v["inline"]))
        ents = [e for e in select(ctx.doc, on, ctx.refs, field="on") if e.dxftype() in ("LINE", "LWPOLYLINE")]
        if not ents:
            raise input_error("UNSUPPORTED_ENTITY", "'on' must select a pipe (LINE or open LWPOLYLINE)")
        if insert is None:
            if len(ents) > 1:
                raise input_error("TARGET_NOT_UNIQUE", "'on' selects several pipe pieces: give 'insert' to say where",
                                  entities=[e.dxf.handle for e in ents])
            from ezdxf import bbox
            insert = tuple(bbox.extents(ents, fast=True).center)[:2]
        # a pipe already cut by earlier symbols is several pieces sharing its tag: use the one nearest 'insert'
        pipe = min(ents, key=lambda e: _distance(e, insert))
        space = ctx.space_of(pipe)  # before the cut: a symbol as long as the pipe consumes it
        insert, ang, g0, g1, new = _break_for_symbol(ctx, pipe, insert, d.get("span", 0.5) * size)
        rot = ang + rotation
        # a flow arrow of the pipe sitting where the symbol goes would be drawn through it
        for a in list(space.query('INSERT[name=="PID_FLOW_ARROW"]')):
            if math.dist((a.dxf.insert.x, a.dxf.insert.y), insert) <= d.get("span", 0.5) * size + 1e-9:
                out.setdefault("removed_flow_arrows", []).append(a.dxf.handle)
                ctx.removed(a)
        out["ports"] = [[round(v, 6) for v in g0], [round(v, 6) for v in g1]]
    elif insert is None:
        raise input_error("MISSING_PARAM", "add_pid_symbol needs 'insert' (or 'on' for an inline symbol)")
    name = _pid_block(ctx, symbol)
    attrs = ctx.attribs(q)
    ref = space.add_blockref(name, insert, dxfattribs={**attrs, "xscale": size, "yscale": size, "zscale": size,
                                                         "rotation": rot})
    if d.get("instrument"):
        ref.add_auto_attribs(_split_instrument_tag(tag_no) if tag_no else {})
        upright = None
    elif d.get("no_tag"):
        upright = None
    else:
        ref.add_auto_attribs({"TAG": tag_no or ""})
        th = 2.5 * _anno(ctx)  # tag text stays 2.5 mm on paper whatever the symbol size
        for a in ref.attribs:
            a.dxf.height = th
            a.set_placement(a.dxf.align_point, align=TextEntityAlignment.MIDDLE_CENTER)
        upright = ref
    if upright is not None and 90 < rot % 360 <= 270:  # keep text readable on pipes drawn right to left
        for a in upright.attribs:
            a.dxf.rotation = (rot + 180) % 360
    return {"created": [ctx.finish(ref, p), *new], "block": name, "rotation": round(rot % 360, 6),
            "size": size, **out}


@op("add_process_line", "library", "P&ID line through 'points' (one LWPOLYLINE): process, utility, "
    "signal_electric (dashed) or signal_pneumatic (with // marks), on a PID_* layer unless 'layer' is given. "
    "Optional flow arrows on each segment and a line number written along the longest segment. Arrows, marks and "
    "the number are tagged '<tag>.deco'.",
    {"points": P("points", True), "kind": P("enum", enum=list(L.LINE_KINDS), default="process"),
     "line_number": P("string", description="e.g. '2\"-P-1001-A1A'"),
     "flow_arrows": P("bool", default=True, description="Arrow in the middle of each segment, pointing along it"),
     "arrow_size": P("length", gt=0, description="Default 4 mm on paper")}, common_draw=True)
def add_process_line(ctx: Ctx, points, kind, line_number, flow_arrows, arrow_size, **p):
    if (s := check_group(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if len(points) < 2:
        raise input_error("TOO_FEW_POINTS", "A process line needs at least 2 points")
    layer, lt, lw = L.LINE_KINDS[kind]
    q = _layer_default(ctx, p, layer, color=7, linetype=lt, lineweight=lw)
    attrs = ctx.attribs(q)
    pts = [(x[0], x[1]) for x in points]
    pl = ctx.layout.add_lwpolyline(pts, dxfattribs=attrs)
    created = [ctx.finish(pl, p)]
    deco_p = {"tag": f"{p['tag']}.deco"} if p.get("tag") else {}
    deco_attrs = {k: v for k, v in attrs.items() if k != "linetype"}
    k = _anno(ctx)
    asz = arrow_size or 4.0 * k
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if math.dist(pts[i], pts[i + 1]) > 1e-9]
    deco = []
    for a, b in segs:
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ln = math.dist(a, b)
        if flow_arrows and ln > 3 * asz:
            name = _pid_block(ctx, "flow_arrow")
            deco.append(ctx.layout.add_blockref(name, mid, dxfattribs={**deco_attrs, "xscale": asz, "yscale": asz,
                                                                       "zscale": asz, "rotation": ang}))
        if kind == "signal_pneumatic":  # ISA: pairs of short slashes along the line
            n = max(1, int(ln // (8 * k)))
            for j in range(n):
                c = (a[0] + (b[0] - a[0]) * (j + 0.5) / n, a[1] + (b[1] - a[1]) * (j + 0.5) / n)
                for off in (-0.5, 0.5):
                    deco.extend(draw_prims(ctx, ctx.layout, [("line", (off - 0.6, -1.0), (off + 0.6, 1.0))],
                                           c, 1.2 * k, ang + (12 if flow_arrows and ln > 3 * asz else 0), deco_attrs))
    if line_number:
        a, b = max(segs, key=lambda sg: math.dist(*sg)) if segs else (pts[0], pts[1])
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if 90 < ang % 360 <= 270:
            ang -= 180
        h = 2.5 * k
        nx, ny = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
        mid = ((a[0] + b[0]) / 2 + nx * 0.8 * h, (a[1] + b[1]) / 2 + ny * 0.8 * h)
        if flow_arrows and math.dist(a, b) > 3 * asz:  # keep the number clear of the arrow
            mid = (mid[0] + math.cos(math.radians(ang)) * 2 * asz, mid[1] + math.sin(math.radians(ang)) * 2 * asz)
        deco.append(_text(ctx.layout, line_number, mid, h, TextEntityAlignment.BOTTOM_CENTER,
                          {k2: v for k2, v in deco_attrs.items() if k2 != "lineweight"}, ang))
    created += _finish_all(ctx, deco, deco_p)
    return {"created": created, "layer": q["layer"], "segments": len(segs)}


# --- GD&T --------------------------------------------------------------------------------------------------------
def _text_h(ctx: Ctx, height) -> float:
    return height or 3.5 * _anno(ctx)


def _circled(space, letter: str, centre, h: float, attrs: dict) -> list:
    return [space.add_circle(centre, 0.45 * h, dxfattribs=attrs),
            _text(space, letter, centre, 0.65 * h, TextEntityAlignment.MIDDLE_CENTER, attrs)]


@op("add_feature_control_frame", "library", "GD&T feature control frame (ISO 1101 / ASME Y14.5): characteristic "
    "symbol, tolerance (with diameter sign and material modifier) and up to three datum references such as 'A', "
    "'B(M)', 'A-B'. 'insert' is the frame's lower-left corner; 'leader_to' adds a leader with an arrow to the "
    "feature. Text height defaults to 3.5 mm on paper; the frame is twice as high. All entities share the tag.",
    {"insert": P("point", True), "characteristic": P("enum", True, enum=sorted(L.GDT)),
     "tolerance": P("string", True, description="e.g. '0.05'"),
     "diameter": P("bool", default=False, description="Cylindrical zone: prefix %%c (Ø)"),
     "modifier": P("enum", enum=list(L.MODIFIERS), description="Tolerance modifier, e.g. M = MMC"),
     "datums": P("list", default=None, description="Datum references, primary first"),
     "height": P("length", gt=0, description="Text height"), "leader_to": P("point")}, common_draw=True)
def add_feature_control_frame(ctx: Ctx, insert, characteristic, tolerance, diameter, modifier, datums, height,
                              leader_to, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    datums = [str(x) for x in (datums or [])]
    if len(datums) > 3:
        raise input_error("TOO_MANY_DATUMS", "A frame has at most three datum references")
    if characteristic in L.DATUM_REQUIRED and not datums:
        raise input_error("MISSING_DATUM", f"{characteristic} needs a datum reference", hint="e.g. datums=['A']")
    if characteristic in L.FORM_ONLY and datums:
        raise input_error("DATUM_NOT_ALLOWED", f"{characteristic} is a form tolerance and takes no datum")
    parsed = []
    for dref in datums:
        m = re.fullmatch(r"\s*([A-Z](?:\s*-\s*[A-Z])*)\s*(?:\(([A-Z])\))?\s*", dref)
        if not m or (m.group(2) and m.group(2) not in L.MODIFIERS):
            raise input_error("INVALID_DATUM", f"Datum reference {dref!r} not understood",
                              hint="Capital letters, e.g. 'A', 'A-B', 'B(M)'")
        parsed.append((m.group(1).replace(" ", ""), m.group(2)))
    q = _layer_default(ctx, p, "DIM", color=3, lineweight=18)
    attrs = ctx.attribs(q)
    h = _text_h(ctx, height)
    H, pad, cw = 2 * h, 0.5 * h, 0.72 * h
    x0, y0 = insert
    sp = ctx.layout
    ents = []
    # cell 1: characteristic symbol
    xs = [x0, x0 + H]
    ents += draw_prims(ctx, sp, L.GDT[characteristic]["prims"], (x0 + H / 2, y0 + H / 2), H * 0.8, 0, attrs)
    # cell 2: tolerance
    tol = ("%%c" if diameter else "") + tolerance
    tw = (len(tolerance) + (1 if diameter else 0)) * cw
    ents.append(_text(sp, tol, (xs[-1] + pad, y0 + H / 2), h, TextEntityAlignment.MIDDLE_LEFT, attrs))
    w = tw + 2 * pad
    if modifier:
        ents += _circled(sp, modifier, (xs[-1] + pad + tw + 0.75 * h, y0 + H / 2), h, attrs)
        w += 1.2 * h
    xs.append(xs[-1] + w)
    for letters, mod in parsed:
        lw_ = len(letters) * cw
        w = max(H, lw_ + 2 * pad + (1.2 * h if mod else 0))
        cx = xs[-1] + (w - (1.2 * h if mod else 0)) / 2
        ents.append(_text(sp, letters, (cx, y0 + H / 2), h, TextEntityAlignment.MIDDLE_CENTER, attrs))
        if mod:
            ents += _circled(sp, mod, (cx + lw_ / 2 + 0.75 * h, y0 + H / 2), h, attrs)
        xs.append(xs[-1] + w)
    x1 = xs[-1]
    ents.append(sp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y0 + H), (x0, y0 + H)], close=True, dxfattribs=attrs))
    for x in xs[1:-1]:
        ents.append(sp.add_line((x, y0), (x, y0 + H), dxfattribs=attrs))
    if leader_to is not None:
        lx, ly = leader_to
        if lx < x0:
            start = (x0, y0 + H / 2)
        elif lx > x1:
            start = (x1, y0 + H / 2)
        else:
            start = (min(max(lx, x0 + H / 2), x1 - H / 2), y0 if ly < y0 else y0 + H)
        from .annotate import _dimstyle
        ents.append(sp.add_leader([leader_to, start], dimstyle=_dimstyle(ctx), dxfattribs=attrs))
    return {"created": _finish_all(ctx, ents, p), "frame": [[x0, y0], [x1, y0 + H]], "text_height": h}


@op("add_datum_feature", "library", "GD&T datum feature symbol: a filled triangle on the feature at 'on', a line "
    "to a square box centred at 'insert' with the datum letter. All entities share the tag.",
    {"letter": P("string", True), "on": P("point", True, description="Point on the datum feature"),
     "insert": P("point", True, description="Centre of the letter box"),
     "height": P("length", gt=0, description="Text height (default 3.5 mm on paper)")}, common_draw=True)
def add_datum_feature(ctx: Ctx, letter, on, insert, height, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if not re.fullmatch(r"[A-Z]{1,2}", letter):
        raise input_error("INVALID_DATUM", f"Datum letter {letter!r}: use one or two capital letters")
    h = _text_h(ctx, height)
    dx, dy = insert[0] - on[0], insert[1] - on[1]
    dist = math.hypot(dx, dy)
    if dist < 2.2 * h:
        raise geometry_error("TOO_CLOSE", f"'insert' must be at least {2.2 * h:g} from 'on'")
    ux, uy = dx / dist, dy / dist
    nx, ny = -uy, ux
    apex = (on[0] + ux * h, on[1] + uy * h)
    q = _layer_default(ctx, p, "DIM", color=3, lineweight=18)
    attrs = ctx.attribs(q)
    sp = ctx.layout
    tri = [(on[0] + nx * 0.6 * h, on[1] + ny * 0.6 * h), apex, (on[0] - nx * 0.6 * h, on[1] - ny * 0.6 * h)]
    ents = draw_prims(ctx, sp, [("fill", tri), ("poly", tri, True)], attrs=attrs)
    t = h / max(abs(ux), abs(uy))  # from the box centre back to its edge
    ents.append(sp.add_line(apex, (insert[0] - ux * t, insert[1] - uy * t), dxfattribs=attrs))
    cx, cy = insert
    ents.append(sp.add_lwpolyline([(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)],
                                  close=True, dxfattribs=attrs))
    ents.append(_text(sp, letter, insert, h, TextEntityAlignment.MIDDLE_CENTER, attrs))
    return {"created": _finish_all(ctx, ents, p)}


@op("add_surface_finish", "library", "Surface texture symbol (ISO 1302 / ISO 21920): tip at 'insert' on the "
    "surface; process any | removal_required (closed V) | removal_prohibited (circle); optional Ra value written "
    "over the extension bar. 'rotation' turns the symbol about its tip.",
    {"insert": P("point", True), "ra": P("string", description="e.g. '3.2' (written 'Ra 3.2')"),
     "process": P("enum", enum=["any", "removal_required", "removal_prohibited"], default="any"),
     "rotation": P("angle", default=0.0), "height": P("length", gt=0, description="Text height (default 3.5 mm "
                                                                                  "on paper)")}, common_draw=True)
def add_surface_finish(ctx: Ctx, insert, ra, process, rotation, height, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    h = _text_h(ctx, height)
    h1, h2 = 1.4 * h, 3.0 * h
    t30 = math.tan(math.radians(30))
    prims: list = [("line", (0, 0), (-h1 * t30, h1)), ("line", (0, 0), (h2 * t30, h2))]
    if process == "removal_required":
        prims.append(("line", (-h1 * t30, h1), (h1 * t30, h1)))
    elif process == "removal_prohibited":
        prims.append(("circle", (0, 0.66 * h1), 0.33 * h1))
    text = f"Ra {ra}" if ra else None
    if text:
        prims.append(("line", (h2 * t30, h2), (h2 * t30 + len(text) * 0.72 * h + 0.5 * h, h2)))
    q = _layer_default(ctx, p, "DIM", color=3, lineweight=18)
    attrs = ctx.attribs(q)
    ents = draw_prims(ctx, ctx.layout, prims, insert, 1.0, rotation, attrs)
    if text:
        at = _xf((h2 * t30 + 0.25 * h, h2 + 0.3 * h), insert, 1.0, rotation)
        ents.append(_text(ctx.layout, text, at, h, TextEntityAlignment.BOTTOM_LEFT, attrs, rotation))
    return {"created": _finish_all(ctx, ents, p)}


# --- standard holes and parts ----------------------------------------------------------------------------------------
@op("add_standard_hole", "library", "ISO metric holes at one or more 'centers' in one op: clearance (ISO 273, "
    "fit fine|medium|coarse), tapped (tap-drill circle plus the thin 3/4 thread circle of ISO 6410, on layer "
    "THREAD) or counterbore for ISO 4762 cap screws. Circles go on HOLES unless 'layer' is given; center marks are "
    "added by default. The result gives the diameters and a callout text (e.g. 'M8-6H') for a leader.",
    {"centers": P("points", True), "size": P("enum", True, enum=SIZES),
     "kind": P("enum", enum=list(L.HOLE_KINDS), default="clearance"),
     "fit": P("enum", enum=list(L.FITS), default="medium"),
     "center_marks": P("bool", default=True)}, common_draw=True)
def add_standard_hole(ctx: Ctx, centers, size, kind, fit, center_marks, **p):
    if (s := check_group(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    dims = L.hole_dims(size, kind, fit)
    k = _per_mm(ctx)
    q = _layer_default(ctx, p, "HOLES", color=7, lineweight=50)
    attrs = ctx.attribs(q)
    thread_attrs = None
    if kind == "tapped":
        thread_attrs = ctx.attribs(_layer_default(ctx, {"layer": None}, "THREAD", color=7, lineweight=18))
        thread_attrs["layer"] = "THREAD"
    created, circles = [], []
    for i, c in enumerate(centers):
        c = (c[0], c[1])
        tp = {**p, "tag": f"{p['tag']}.{i}" if p.get("tag") and len(centers) > 1 else p.get("tag")}
        e = ctx.layout.add_circle(c, dims["diameter"] * k / 2, dxfattribs=attrs)
        created.append(ctx.finish(e, tp))
        circles.append(e.dxf.handle)
        extra = []
        if kind == "tapped":
            extra.append(ctx.layout.add_arc(c, dims["thread_diameter"] * k / 2, 90, 0, dxfattribs=thread_attrs))
        elif kind == "counterbore":
            extra.append(ctx.layout.add_circle(c, dims["counterbore_diameter"] * k / 2, dxfattribs=attrs))
        dp = {"tag": f"{tp['tag']}.feature"} if tp.get("tag") else {}
        created += _finish_all(ctx, extra, dp)
    if center_marks:
        from .annotate import add_center_mark
        cm = add_center_mark(ctx, target=circles, extension=None,
                             **{"tag": f"{p['tag']}.cm" if p.get("tag") else None})
        created += cm["created"]
    return {"created": created, "holes": circles, "count": len(circles),
            "dims": {k2: (round(v * k, 6) if isinstance(v, float) and k2 != "pitch" else v)
                     for k2, v in dims.items()}}


def _hexagon(r: float, start: float = 0.0) -> list:
    return [(r * math.cos(math.radians(start + 60 * i)), r * math.sin(math.radians(start + 60 * i))) for i in range(6)]


THIN = {"lineweight": 18}


def _shank(d: float, d1: float, length: float, b: float) -> list:
    out: list = [("poly", [(-d / 2, 0), (-d / 2, -length), (d / 2, -length), (d / 2, 0)], False),
                 ("line", (-d1 / 2, -length), (-d1 / 2, -length + b), THIN),
                 ("line", (d1 / 2, -length), (d1 / 2, -length + b), THIN)]
    if b < length - 1e-9:
        out.append(("line", (-d / 2, -length + b), (d / 2, -length + b)))
    return out


def part_prims(part: str, dm: dict[str, Any], view: str) -> list:
    """Geometry of a standard part in mm. Side views stand on the insertion point (bearing face under the head,
    nut and washer bottom face), the axis pointing -y for bolts and screws; bearings are centred."""
    rect = lambda x0, y0, x1, y1: ("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)  # noqa: E731
    if part == "ball_bearing":
        d, D, B = dm["d"], dm["D"], dm["B"]
        if view == "top":
            w = (D - d) * 0.15
            return [("circle", (0, 0), D / 2), ("circle", (0, 0), d / 2),
                    ("circle", (0, 0), d / 2 + w, THIN), ("circle", (0, 0), D / 2 - w, THIN)]
        pm, rb = (D + d) / 4, (D - d) / 4 * 0.6
        return [rect(-B / 2, -D / 2, B / 2, D / 2), ("line", (-B / 2, d / 2), (B / 2, d / 2)),
                ("line", (-B / 2, -d / 2), (B / 2, -d / 2)), ("circle", (0, pm), rb), ("circle", (0, -pm), rb)]
    if part == "washer":
        if view == "top":
            return [("circle", (0, 0), dm["d2"] / 2), ("circle", (0, 0), dm["d1"] / 2)]
        return [rect(-dm["d2"] / 2, 0, dm["d2"] / 2, dm["h"])]
    d, d1 = dm["d"], dm["minor_diameter"]
    if part == "hex_nut":
        e, s, m = dm["e"], dm["s"], dm["m"]
        if view == "top":
            return [("poly", _hexagon(e / 2), True), ("circle", (0, 0), s / 2, THIN), ("circle", (0, 0), d1 / 2),
                    ("arc", (0, 0), d / 2, 90, 0, THIN)]
        return [rect(-e / 2, 0, e / 2, m), ("line", (-e / 4, 0), (-e / 4, m)), ("line", (e / 4, 0), (e / 4, m))]
    if part == "hex_bolt":
        e, s, kk = dm["e"], dm["s"], dm["k"]
        if view == "top":
            return [("poly", _hexagon(e / 2), True), ("circle", (0, 0), s / 2, THIN)]
        return [rect(-e / 2, 0, e / 2, kk), ("line", (-e / 4, 0), (-e / 4, kk)), ("line", (e / 4, 0), (e / 4, kk)),
                *_shank(d, d1, dm["length"], dm["thread_length"])]
    # socket head cap screw
    dk, kk, s = dm["dk"], dm["k"], dm["s"]
    if view == "top":
        return [("circle", (0, 0), dk / 2), ("poly", _hexagon(s / math.cos(math.radians(30)) / 2), True)]
    hid = {"linetype": "DASHED", **THIN}
    t = 0.5 * kk
    return [rect(-dk / 2, 0, dk / 2, kk), ("line", (-s / 2, kk), (-s / 2, kk - t), hid),
            ("line", (s / 2, kk), (s / 2, kk - t), hid), ("line", (-s / 2, kk - t), (s / 2, kk - t), hid),
            *_shank(d, d1, dm["length"], dm["thread_length"])]


@op("add_standard_part", "library", "ISO standard part as a block, true size: hex_bolt (ISO 4014/4017), hex_nut "
    "(ISO 4032), washer (ISO 7089), socket_head_cap_screw (ISO 4762) in sizes M3-M24, or ball_bearing (ISO 15, "
    "6000-6310). view 'top' looks along the axis; 'side' stands on 'insert' (bolts and screws: the bearing face "
    "under the head, shank pointing -y before 'rotation'; bearings: centred). Bolts and screws need 'length' for "
    "the side view. The block carries PART / STANDARD / SIZE attributes for the parts list "
    "(standard_library drawing=...).",
    {"part": P("enum", True, enum=list(L.PARTS)), "size": P("string", True, description="'M10' or '6204'"),
     "insert": P("point", True), "view": P("enum", enum=["top", "side"], default="side"),
     "length": P("length", gt=0, description="Nominal length (bolts and screws)"),
     "rotation": P("angle", default=0.0),
     "count_in_bom": P("bool", default=True, description="false for a second view of a part already counted")},
    common_draw=True)
def add_standard_part(ctx: Ctx, part, size, insert, view, length, rotation, count_in_bom, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    info = L.PARTS[part]
    _check_size(size, info["sizes"], part)
    k = _per_mm(ctx)
    length_mm = None
    if info["needs_length"]:
        if length is None and view == "side":
            raise input_error("MISSING_PARAM", f"{part} side view needs 'length'")
        length_mm = round(length / k, 6) if length is not None else None
    dm = L.part_dims(part, size, length_mm)
    std = dm.get("standard", info["standard"])
    label = size + (f"x{length_mm:g}" if length_mm else "")
    name = f"{std.split('/')[0].replace(' ', '')}_{label}_{view.upper()}".replace(".", "_")
    if name not in ctx.doc.blocks:
        blk = ctx.doc.blocks.new(name, base_point=(0, 0))
        draw_prims(ctx, blk, part_prims(part, dm, view))
        for tag in ("PART", "STANDARD", "SIZE"):
            a = blk.add_attdef(tag, (0, 0), height=2.5)
            a.dxf.flags = 1  # invisible: data for the parts list
    q = _layer_default(ctx, p, "PARTS", color=7, lineweight=50)
    ref = ctx.layout.add_blockref(name, insert, dxfattribs={**ctx.attribs(q), "xscale": k, "yscale": k,
                                                              "zscale": k, "rotation": rotation})
    ref.add_auto_attribs({"PART": part if count_in_bom else "", "STANDARD": std, "SIZE": label})
    return {"created": [ctx.finish(ref, p)], "block": name, "standard": std, "dims_mm": dm}
