"""Dimensions, leaders, tables and title blocks."""
from __future__ import annotations

import math
from typing import Any

from ezdxf.entities.dimstyleoverride import DimStyleOverride
from ezdxf.math import Vec2
from ezdxf.render.dim_curved import AngularDimension

from .. import geom as G
from ..errors import input_error
from ..model import select
from .registry import Ctx, Param, check_tag, op

P = Param
DIMSTYLE = "AGENTCAD"


# GB engineering SHX fonts that ship with every AutoCAD; gbcbig is the big font for Chinese characters.
# Without a big font AutoCAD shows CJK text as '???' (seen in AutoCAD 2027 plots).
TEXT_FONT, BIG_FONT = "gbenor.shx", "gbcbig.shx"


def setup_text_style(doc) -> None:
    st = doc.styles.get("Standard")
    st.dxf.font = TEXT_FONT
    st.dxf.bigfont = BIG_FONT


def apply_annotation_scale(doc, scale: float) -> None:
    """Plot scale 1:scale. Dimension sizes (DIMSCALE) and linetype patterns (LTSCALE) grow with it, so a
    6000 mm room drawn at 1:50 gets readable arrows and dash-dot axes."""
    doc.header["$DIMSCALE"] = scale
    doc.header["$LTSCALE"] = scale
    if DIMSTYLE in doc.dimstyles:
        doc.dimstyles.get(DIMSTYLE).dxf.dimscale = scale


def _dimstyle(ctx: Ctx) -> str:
    return DIMSTYLE if DIMSTYLE in ctx.doc.dimstyles else "Standard"


def _override(text_height, length_factor=None) -> dict[str, Any]:
    ov: dict[str, Any] = {"dimtxt": text_height} if text_height else {}
    if length_factor:
        ov["dimlfac"] = float(length_factor)
    return ov


def _finish_dim(ctx: Ctx, dimov, p: dict[str, Any], text: str | None) -> dict[str, Any]:
    if text:
        dimov.dimension.dxf.text = text
    if p.get("tolerance") is not None:
        from ..tolerances import apply_tolerance
        apply_tolerance(dimov, p["tolerance"], ctx.unit)
    elif text and "<>" not in text and (dimov.get("dimtol", 0) or dimov.get("dimlim", 0)):
        raise input_error("TOLERANCE_TEXT_OVERRIDE", "This dimension style shows a tolerance, so the text must "
                          "include the measured value (<>)", hint="Write e.g. '<> REF' instead of a fixed number")
    render_dimension(dimov)
    store_measurement(dimov.dimension)
    return {"created": [ctx.finish(dimov.dimension, p)]}


class _TwoLineAngularRenderer(AngularDimension):
    def get_center_of_arc(self):
        center, start, end = G.angular_sector(
            G.Seg(tuple(self.leg1_start), tuple(self.leg1_end)),
            G.Seg(tuple(self.leg2_start), tuple(self.leg2_end)), tuple(self.dim_line_location))
        self._start_dir = Vec2.from_deg_angle(start)
        self._end_dir = Vec2.from_deg_angle(end)
        leg1 = (self.leg1_end - self.leg1_start).normalize()
        if abs(self._start_dir.det(leg1)) > 1e-8:
            self.leg1_start, self.leg2_start = self.leg2_start, self.leg1_start
            self.leg1_end, self.leg2_end = self.leg2_end, self.leg1_end
        return Vec2(center)

    def get_ext1_dir(self):
        return self._start_dir

    def get_ext2_dir(self):
        return self._end_dir


class _RenderingStyle(DimStyleOverride):
    def get(self, attribute: str, default=None):
        value = super().get(attribute, default)
        # DXF zero means no rounding increment; ezdxf's xround(value, 0)
        # instead rounds to an integer. None skips xround before DIMDEC.
        # Only the renderer sees None: the stored override dictionary is intact.
        return None if attribute == "dimrnd" and value == 0 else value

    def get_renderer(self, ucs=None):
        if self.dimension.dimtype == 2:
            return _TwoLineAngularRenderer(self.dimension, ucs, self)
        return super().get_renderer(ucs)


def render_dimension(override) -> None:
    """Render at native precision without persisting an artificial increment."""
    renderer = _RenderingStyle(override.dimension, override.dimstyle_attribs)
    renderer.render()
    override.dimstyle_attribs.update(renderer.dimstyle_attribs)


def store_measurement(dim) -> None:
    """ezdxf does not write group 42 (actual measurement); AutoCAD does. Write it.
    AutoCAD stores angular measurements in radians (observed in AutoCAD 2027);
    the runtime API reports degrees."""
    from ..model import DIMTYPES, measure_dimension
    m = measure_dimension(dim)
    if m is not None:
        if DIMTYPES.get(dim.dxf.dimtype & 0x0F) in ("angular", "angular3p"):
            m = math.radians(m)
        dim.dxf.actual_measurement = m


DIM_COMMON = {"text": P("string", description="Text override; '<>' stands for the measured value"),
              "tolerance": P("object", description="Signed lower/upper deviations in displayed drawing units (or unit strings); "
                             "optional precision=3 and mode=deviations|limits. Linear/radius/diameter dimensions only."),
              "text_height": P("length", gt=0, description="Override text height"),
              "length_factor": P("number", gt=0, description="DIMLFAC: displayed value = measured length x factor, "
                                 "e.g. 1/0.325 on a sheet that shows the part at scale 0.325")}


@op("add_linear_dim", "annotate", "Linear dimension between two points. orientation: horizontal | vertical | "
    "aligned | rotated. The dimension line is placed at 'base' or at 'offset' from the measured points.",
    {"p1": P("point", True, description="First extension line origin"),
     "p2": P("point", True, description="Second extension line origin"),
     "orientation": P("enum", enum=["horizontal", "vertical", "aligned", "rotated"], default="horizontal"),
     "angle": P("angle", default=0.0, description="Measurement direction for orientation=rotated"),
     "offset": P("length", default=10.0, description="Distance of the dimension line from the points (sign = side)"),
     "base": P("point", description="Explicit location of the dimension line"), **DIM_COMMON}, common_draw=True)
def add_linear_dim(ctx: Ctx, p1, p2, orientation, angle, offset, base, text, text_height, length_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if G.dist(p1, p2) < 1e-9:
        raise input_error("DEGENERATE_GEOMETRY", "Dimension points coincide")
    attrs = ctx.attribs(p)
    ov = _override(text_height, length_factor)
    if orientation == "aligned":
        dist = offset if base is None else _signed_dist(p1, p2, base)
        d = ctx.msp.add_aligned_dim(p1, p2, distance=dist, dimstyle=_dimstyle(ctx), override=ov, dxfattribs=attrs)
        return _finish_dim(ctx, d, p, text)
    ang = {"horizontal": 0.0, "vertical": 90.0}.get(orientation, angle)
    if base is None:
        a = math.radians(ang)
        n = (-math.sin(a), math.cos(a))  # dimension line normal
        far = max(G.dot(p1, n), G.dot(p2, n)) if offset >= 0 else min(G.dot(p1, n), G.dot(p2, n))
        shift = far + offset - G.dot(p1, n)
        base = G.add(p1, G.mul(n, shift))
    d = ctx.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=ang, dimstyle=_dimstyle(ctx), override=ov, dxfattribs=attrs)
    return _finish_dim(ctx, d, p, text)


def _signed_dist(p1, p2, b) -> float:
    u = G.unit(G.sub(p2, p1))
    return G.cross(u, G.sub(b, p1))


def _circle_of(ctx: Ctx, target, center, radius):
    if target is not None:
        ents = select(ctx.doc, target, ctx.refs)
        if len(ents) != 1 or ents[0].dxftype() not in ("CIRCLE", "ARC"):
            raise input_error("UNSUPPORTED_ENTITY", "target must be exactly one CIRCLE or ARC",
                              entities=[e.dxf.handle for e in ents])
        e = ents[0]
        from ..model import circle_wcs
        c, rad, _, _ = circle_wcs(e)
        return c, rad
    if center is None or radius is None:
        raise input_error("MISSING_PARAM", "Give 'target' (circle/arc) or 'center' + 'radius'")
    return center, radius


RAD_PARAMS = {"target": P("selector", description="CIRCLE or ARC to dimension"), "center": P("point"),
              "radius": P("length", gt=0), "angle": P("angle", default=45.0, description="Direction of the leader"),
              **DIM_COMMON}


@op("add_radius_dim", "annotate", "Radius dimension of a circle/arc.", RAD_PARAMS, common_draw=True)
def add_radius_dim(ctx: Ctx, target, center, radius, angle, text, text_height, length_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    c, r = _circle_of(ctx, target, center, radius)
    d = ctx.msp.add_radius_dim(center=c, radius=r, angle=angle, dimstyle=_dimstyle(ctx),
                               override=_override(text_height, length_factor), dxfattribs=ctx.attribs(p))
    return _finish_dim(ctx, d, p, text)


@op("add_diameter_dim", "annotate", "Diameter dimension of a circle/arc.", RAD_PARAMS, common_draw=True)
def add_diameter_dim(ctx: Ctx, target, center, radius, angle, text, text_height, length_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    c, r = _circle_of(ctx, target, center, radius)
    d = ctx.msp.add_diameter_dim(center=c, radius=r, angle=angle, dimstyle=_dimstyle(ctx),
                                 override=_override(text_height, length_factor), dxfattribs=ctx.attribs(p))
    return _finish_dim(ctx, d, p, text)


@op("add_angular_dim", "annotate", "Angular dimension from vertex 'center' between rays to p1 and p2 "
    "(measured CCW from p1 to p2); 'radius' places the dimension arc.",
    {"center": P("point", True), "p1": P("point", True), "p2": P("point", True),
     "radius": P("length", gt=0, description="Radius of the dimension arc (default: 0.6 x shorter ray)"), **DIM_COMMON},
    common_draw=True)
def add_angular_dim(ctx: Ctx, center, p1, p2, radius, text, text_height, length_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    a1 = G.angle_of(G.sub(p1, center))
    a2 = G.angle_of(G.sub(p2, center))
    rr = radius or 0.6 * min(G.dist(center, p1), G.dist(center, p2))
    mid = a1 + G.ccw_span(a1, a2) / 2
    base = G.polar(center, rr, mid)
    d = ctx.msp.add_angular_dim_3p(base=base, center=center, p1=p1, p2=p2, dimstyle=_dimstyle(ctx),
                                   override=_override(text_height, length_factor), dxfattribs=ctx.attribs(p))
    return _finish_dim(ctx, d, p, text)


@op("add_ordinate_dim", "annotate", "Ordinate (datum) dimension: the X or Y distance of 'feature' from 'origin', "
    "written at the end of a leader from the feature to 'leader_end'.",
    {"feature": P("point", True, description="Point being dimensioned"),
     "leader_end": P("point", True, description="End of the leader, where the text goes"),
     "axis": P("enum", True, enum=["x", "y"], description="'x' measures the X distance (vertical leader), 'y' the Y distance"),
     "origin": P("point", default=(0.0, 0.0), description="Datum point (UCS origin of the ordinates)"), **DIM_COMMON},
    common_draw=True)
def add_ordinate_dim(ctx: Ctx, feature, leader_end, axis, origin, text, text_height, length_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if G.dist(feature, leader_end) < 1e-9:
        raise input_error("DEGENERATE_GEOMETRY", "leader_end coincides with feature")
    add = ctx.msp.add_ordinate_x_dim if axis == "x" else ctx.msp.add_ordinate_y_dim
    d = add(feature_location=feature, offset=G.sub(leader_end, feature), origin=origin, dimstyle=_dimstyle(ctx),
            override=_override(text_height, length_factor), dxfattribs=ctx.attribs(p))
    return _finish_dim(ctx, d, p, text)


@op("add_center_mark", "annotate", "Center mark of CIRCLEs / ARCs (AutoCAD CENTERMARK): a horizontal and a vertical "
    "LINE through each center, 'extension' beyond the radius. Layer CENTER with linetype CENTER unless given. With "
    "'tag' the lines are tagged '<tag>.h' / '<tag>.v' (several targets: '<tag>.<i>.h').",
    {"target": P("selector", True, description="CIRCLE / ARC entities"),
     "extension": P("length", ge=0, description="Overshoot past the circle (default: max(2, radius/2))")},
    common_draw=True)
def add_center_mark(ctx: Ctx, target, extension, **p):
    from ..model import circle_wcs
    from .registry import check_tag as _check
    ents = select(ctx.doc, target, ctx.refs)
    bad = [e.dxf.handle for e in ents if e.dxftype() not in ("CIRCLE", "ARC")]
    if bad:
        raise input_error("UNSUPPORTED_ENTITY", "add_center_mark needs CIRCLE or ARC targets", entities=bad)
    q = dict(p)
    q["layer"] = p.get("layer") or "CENTER"
    if "CENTER" in ctx.doc.linetypes and not p.get("linetype") and q["layer"] not in ctx.doc.layers:
        ctx.doc.layers.add(q["layer"], color=1, linetype="CENTER")
    attrs = ctx.attribs(q)
    created = []
    for i, e in enumerate(ents):
        c, r, _, _ = circle_wcs(e)
        ext = r + (max(2.0, r / 2) if extension is None else extension)
        for suffix, a, b in (("h", (c[0] - ext, c[1]), (c[0] + ext, c[1])), ("v", (c[0], c[1] - ext), (c[0], c[1] + ext))):
            tag = p.get("tag") and (f"{p['tag']}.{suffix}" if len(ents) == 1 else f"{p['tag']}.{i}.{suffix}")
            tp = {**p, "tag": tag}
            if tag and (s := _check(ctx, tp)) is not None:
                created.extend(s)
                continue
            created.append(ctx.finish(ctx.space_of(e).add_line(a, b, dxfattribs=attrs), tp))
    return {"created": created}


@op("create_text_style", "annotate", "Create a text style for add_text / add_mtext 'style'. 'font' is an SHX "
    "(e.g. gbenor.shx, txt.shx) or TrueType file (e.g. simsun.ttc, arial.ttf); SHX fonts need 'big_font' "
    "(e.g. gbcbig.shx) to show Chinese, which is the default for SHX fonts.",
    {"name": P("string", True, description="Style name"),
     "font": P("string", default=TEXT_FONT, description="Font file"),
     "big_font": P("string", description="Big font for CJK characters (SHX fonts only; default gbcbig.shx)"),
     "width_factor": P("number", default=1.0, gt=0, description="Character width factor"),
     "oblique": P("angle", default=0.0, description="Slant angle"),
     "height": P("length", default=0.0, ge=0, description="Fixed text height (0 = set per text)"),
     "if_exists": P("enum", enum=["error", "skip", "update"], default="error")})
def create_text_style(ctx: Ctx, name, font, big_font, width_factor, oblique, height, if_exists):
    shx = font.lower().endswith(".shx")
    if big_font and not shx:
        raise input_error("INVALID_PARAMS", "big_font only applies to SHX fonts", hint="Drop big_font for TrueType fonts")
    if name in ctx.doc.styles:
        if if_exists == "error":
            raise input_error("STYLE_EXISTS", f"Text style {name!r} already exists", hint="Use if_exists='skip' or 'update'")
        if if_exists == "skip":
            return {"style": name, "skipped": True}
        st = ctx.doc.styles.get(name)
    else:
        st = ctx.doc.styles.new(name)
    st.dxf.font = font
    if shx:
        st.dxf.bigfont = big_font or BIG_FONT
    else:
        st.dxf.discard("bigfont")
    st.dxf.width = width_factor
    st.dxf.oblique = oblique
    st.dxf.height = height
    return {"style": name}


def text_style(ctx: Ctx, name: str | None) -> dict[str, Any]:
    if not name:
        return {}
    if name not in ctx.doc.styles:
        raise input_error("UNKNOWN_STYLE", f"Text style {name!r} is not defined",
                          hint=f"Create it with create_text_style; defined: {sorted(s.dxf.name for s in ctx.doc.styles if s.dxf.name)}")
    return {"style": name}


@op("add_leader", "annotate", "Leader (arrow polyline) with an MTEXT note at the last vertex.",
    {"points": P("points", True, description="Leader vertices, arrow at the first point"),
     "text": P("string", True), "text_height": P("length", default=2.5, gt=0)}, common_draw=True)
def add_leader(ctx: Ctx, points, text, text_height, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if len(points) < 2:
        raise input_error("TOO_FEW_POINTS", "A leader needs at least 2 points")
    pts = [(q[0], q[1]) for q in points]
    attrs = ctx.attribs(p)
    ld = ctx.msp.add_leader(pts, dimstyle=_dimstyle(ctx), dxfattribs=attrs)
    last = pts[-1]
    right = pts[-1][0] >= pts[-2][0]
    mt = ctx.msp.add_mtext(text, dxfattribs={**attrs, "char_height": text_height,
                                              "insert": (last[0] + (text_height * 0.5 if right else -text_height * 0.5),
                                                         last[1] + text_height * 0.5)})
    mt.dxf.attachment_point = 7 if right else 9  # bottom-left / bottom-right
    h1 = ctx.finish(ld, p)
    return {"created": [h1, ctx.created(mt)]}


@op("add_table", "annotate", "Simple table drawn as grid lines + TEXT. 'insert' is the top-left corner. "
    "With 'tag', cell texts are tagged '<tag>.r<row>c<col>' and grid lines '<tag>.h<i>' / '<tag>.v<j>', so "
    "{tag_prefix: '<tag>.'} selects the whole table.",
    {"insert": P("point", True), "rows": P("list", True, description="List of rows, each a list of cell strings"),
     "col_widths": P("list", True, description="Column widths"), "row_height": P("length", default=8.0, gt=0),
     "text_height": P("length", default=2.5, gt=0)}, common_draw=True)
def add_table(ctx: Ctx, insert, rows, col_widths, row_height, text_height, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    from ..units import parse_length
    widths = [parse_length(w, ctx.unit, "col_widths") for w in col_widths]
    if any(w <= 0 for w in widths):
        raise input_error("OUT_OF_RANGE", "col_widths must be > 0")
    if any(not isinstance(r, list) or len(r) > len(widths) for r in rows):
        raise input_error("INVALID_TABLE", "Each row must be a list with at most len(col_widths) cells")
    x0, y0 = insert
    W, H = sum(widths), row_height * len(rows)
    attrs = ctx.attribs(p)
    tag = p.get("tag")
    created = []
    from ..model import set_tag

    def line(a, b, name):
        e = ctx.msp.add_line(a, b, dxfattribs=attrs)
        if tag:  # untagged grid lines stayed behind when the table was deleted by its tag prefix
            set_tag(ctx.doc, e, f"{tag}.{name}")
        created.append(ctx.created(e))

    for i in range(len(rows) + 1):
        line((x0, y0 - i * row_height), (x0 + W, y0 - i * row_height), f"h{i}")
    x = x0
    for j, w in enumerate([0.0] + widths):
        x += w
        line((x, y0), (x, y0 - H), f"v{j}")
    from ezdxf.enums import TextEntityAlignment
    for i, row in enumerate(rows):
        x = x0
        for j, cell in enumerate(row):
            if cell not in (None, ""):
                t = ctx.msp.add_text(str(cell), height=text_height, dxfattribs=attrs)
                t.set_placement((x + widths[j] / 2, y0 - (i + 0.5) * row_height), align=TextEntityAlignment.MIDDLE_CENTER)
                if tag:
                    set_tag(ctx.doc, t, f"{tag}.r{i}c{j}")
                created.append(ctx.created(t))
            x += widths[j]
    return {"created": created}


@op("set_annotation_scale", "annotate", "Set the plot scale 1:scale for annotations: dimension arrows/text/gaps "
    "(DIMSCALE) and linetype dash lengths (LTSCALE) are multiplied by 'scale'. Use e.g. 50 or 100 for building "
    "plans in mm. Existing dimensions are re-rendered.",
    {"scale": P("number", True, gt=0, description="N of the plot scale 1:N")})
def set_annotation_scale(ctx: Ctx, scale):
    apply_annotation_scale(ctx.doc, float(scale))
    from .edit import rerender_dimension
    done = []
    for d in ctx.msp.query("DIMENSION"):
        if d.dxf.get("dimstyle") == DIMSTYLE:  # per-entity overrides (text_height) are kept by override()
            rerender_dimension(ctx, d)
            ctx.touched(d)
            done.append(d.dxf.handle)
    return {"scale": float(scale), "rerendered": done}


TITLE_FIELDS = ["TITLE", "DWG_NO", "MATERIAL", "SCALE", "UNITS", "DRAWN_BY", "DATE", "SHEET"]
TITLE_BLOCK = "AGENTCAD_TITLE"


def ensure_title_block(ctx: Ctx, k: float) -> None:
    """Block definition 180x32 (scaled by k), base point = lower-right corner."""
    from ezdxf.enums import TextEntityAlignment
    if TITLE_BLOCK in ctx.doc.blocks:
        return
    blk = ctx.doc.blocks.new(TITLE_BLOCK, base_point=(0, 0))
    W, H = 180 * k, 32 * k
    x0, y0 = -W, 0.0
    a = {"layer": "0"}
    blk.add_lwpolyline([(x0, y0), (0, y0), (0, H), (x0, H)], close=True, dxfattribs=a)
    blk.add_line((x0, 16 * k), (0, 16 * k), dxfattribs=a)
    blk.add_line((x0, 8 * k), (0, 8 * k), dxfattribs=a)
    for xs in (45, 90, 135):
        blk.add_line((x0 + xs * k, 0), (x0 + xs * k, 16 * k), dxfattribs=a)
    cells = {"TITLE": (x0 + 2 * k, 24 * k, 5 * k), "DWG_NO": (x0 + 120 * k, 24 * k, 3.5 * k)}
    labels = {"MATERIAL": (0, 8), "SCALE": (45, 8), "UNITS": (90, 8), "SHEET": (135, 8),
              "DRAWN_BY": (0, 0), "DATE": (45, 0)}
    # Small label in the top of each 8 mm cell, value below it: no overlap whatever the font width.
    for f, (xx, yy) in labels.items():
        cells[f] = (x0 + xx * k + 1.5 * k, yy * k + 1.2 * k, 2.5 * k)
        t = blk.add_text(f.replace("_", " ").title(), height=1.5 * k, dxfattribs=a)
        t.set_placement((x0 + xx * k + 1 * k, yy * k + 5.6 * k), align=TextEntityAlignment.LEFT)
    for f in TITLE_FIELDS:
        x, y, h = cells[f]
        blk.add_attdef(f, insert=(x, y), height=h, text="", dxfattribs=a)


@op("add_title_block", "annotate", "Insert the standard 180x32 mm title block (ISO-like) with attributes "
    f"{TITLE_FIELDS}. 'insert' is the lower-right corner (usually the inner border corner).",
    {"insert": P("point", True), "fields": P("object", default=None, description="Attribute values, e.g. {TITLE: 'Plate'}"),
     "size_factor": P("number", default=1.0, gt=0, description="Scale relative to the mm size")}, common_draw=True)
def add_title_block(ctx: Ctx, insert, fields, size_factor, **p):
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    fields = fields or {}
    bad = [f for f in fields if f not in TITLE_FIELDS]
    if bad:
        raise input_error("UNKNOWN_FIELD", f"Unknown title block field(s) {bad}", hint=f"Fields: {TITLE_FIELDS}")
    from ..units import UNITS
    k = (1.0 / UNITS[ctx.unit][1] if ctx.unit else 1.0)  # 1 mm in drawing units
    ensure_title_block(ctx, 1.0)
    vals = {f: "" for f in TITLE_FIELDS}
    vals["UNITS"] = ctx.unit or ""
    vals.update({k_: str(v) for k_, v in fields.items()})
    attrs = ctx.attribs(p)
    sf = k * size_factor
    attrs.update(xscale=sf, yscale=sf)
    ref = ctx.msp.add_blockref(TITLE_BLOCK, insert, dxfattribs=attrs)
    ref.add_auto_attribs(vals)
    return {"created": [ctx.finish(ref, p)]}
