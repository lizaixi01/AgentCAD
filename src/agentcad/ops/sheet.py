"""Printed sheets: paper-space layouts and viewports onto model space.

Paper space is always in millimetres (the plot units); a viewport's scale is paper mm per model unit, e.g. 0.5
for a mm drawing shown at 1:2.
"""
from __future__ import annotations

from ..errors import input_error
from ..model import is_model
from .registry import Ctx, Param, check_tag, op

P = Param

PAPER = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}


def page_setup_info(lay):
    x = lay.dxf_layout.dxf
    w, h = x.paper_width, x.paper_height
    return {"paper_size_mm": [w, h], "orientation": "landscape" if w >= h else "portrait",
            "ctb": x.get("current_style_sheet", ""),
            "scale": [x.get("scale_numerator", 1), x.get("scale_denominator", 1)]}


@op("set_page_setup", "layout", "Change an existing layout's physical paper size and plot style. ISO sizes "
    "and ANSI B (432 by 279 mm) are supported. monochrome.ctb is rendered by the native PDF exporter.",
    {"name": P("string", True), "paper": P("enum", enum=[*PAPER, "ANSI_B", "custom"], default="A3"),
     "orientation": P("enum", enum=["landscape", "portrait"], default="landscape"),
     "width": P("number", gt=0), "height": P("number", gt=0),
     "ctb": P("enum", enum=["", "monochrome.ctb"], default="")})
def set_page_setup(ctx: Ctx, name, paper, orientation, width, height, ctb):
    if is_model(name) or name not in ctx.doc.layouts:
        raise input_error("LAYOUT_NOT_FOUND", f"No paper-space layout {name!r}")
    lay = ctx.doc.layouts.get(name)
    before = page_setup_info(lay)
    if paper == "custom":
        if not width or not height:
            raise input_error("MISSING_PARAM", "Custom paper needs width and height")
        size = (width, height)
    else:
        size = (432, 279) if paper == "ANSI_B" else PAPER[paper]
    w, h = sorted(size, reverse=orientation == "landscape")
    lay.page_setup(size=(w, h), margins=(0, 0, 0, 0), units="mm", scale=(1, 1))
    lay.dxf_layout.dxf.current_style_sheet = ctb
    after = page_setup_info(lay)
    return {"layout": name, "page_setup": after,
            "changed": {key: {"old": before[key], "new": value} for key, value in after.items()
                        if before[key] != value}, "ctb_known": ctb in {"", "monochrome.ctb"}}


@op("change_space", "layout", "CHSPACE: transfer entities to another layout with an explicit scale and "
    "translation (paper millimetres per model unit). Original handles are retained.",
    {"target": P("selector", True), "destination": P("string", True),
     "scale": P("number", default=1, gt=0), "delta": P("point", default=[0, 0])})
def change_space(ctx: Ctx, target, destination, scale, delta):
    from ezdxf.math import Matrix44
    from ..model import select
    if destination not in ctx.doc.layouts:
        raise input_error("LAYOUT_NOT_FOUND", f"No layout {destination!r}")
    dest = ctx.doc.layouts.get(destination)
    ents = select(ctx.doc, target, ctx.refs)
    matrix = Matrix44.scale(scale, scale, 1) @ Matrix44.translate(*delta, 0)
    for e in ents:
        e.transform(matrix)
        if e.get_layout() != dest:
            e.get_layout().move_to_layout(e, dest)
        ctx.touched(e)
    return {"modified": [e.dxf.handle for e in ents], "destination": destination}


@op("create_layout", "layout", "Create a paper-space layout (a printed sheet) with its paper size. Draw the frame "
    "and title block into it with the usual ops and layout=<name>, then show the model with add_viewport.",
    {"name": P("string", True), "paper": P("enum", enum=[*PAPER, "custom"], default="A3"),
     "orientation": P("enum", enum=["landscape", "portrait"], default="landscape"),
     "width": P("number", gt=0, description="Paper width in mm (paper='custom')"),
     "height": P("number", gt=0, description="Paper height in mm (paper='custom')"),
     "if_exists": P("enum", enum=["error", "skip"], default="error")})
def create_layout(ctx: Ctx, name, paper, orientation, width, height, if_exists):
    if is_model(name):
        raise input_error("INVALID_NAME", "'Model' is model space, not a layout")
    if name in ctx.doc.layouts:
        if if_exists == "skip":
            return {"layout": name, "skipped": True}
        raise input_error("LAYOUT_EXISTS", f"Layout {name!r} already exists", hint="Use if_exists='skip'")
    if paper == "custom":
        if not (width and height):
            raise input_error("MISSING_PARAM", "paper='custom' needs width and height (mm)")
        w, h = width, height
    else:
        w, h = PAPER[paper]
        if orientation == "portrait":
            w, h = h, w
    lay = ctx.doc.layouts.new(name)
    lay.page_setup(size=(w, h), margins=(0, 0, 0, 0), units="mm")
    return {"layout": name, "layout_created": True, "paper": [w, h],
            "hint": f"Paper space origin is the lower-left paper corner; draw with layout={name!r}"}


def _model_extents(ctx: Ctx):
    from ezdxf import bbox
    ext = bbox.extents(ctx.model, fast=True)
    return ext if ext.has_data else None


@op("add_viewport", "layout", "Add a viewport to a paper-space layout (pass layout=<name>) that shows model space "
    "at a fixed scale. center/width/height are on the paper in mm; scale is paper mm per model unit (0.5 = 1:2, "
    "2 = 2:1). view_center defaults to the centre of everything in model space; width/height default to the "
    "model extents at that scale plus a 5% margin.",
    {"center": P("point", True, description="Viewport centre on the paper (mm)"),
     "scale": P("number", True, gt=0, description="Paper mm per model unit, e.g. 0.5 for 1:2"),
     "width": P("number", gt=0, description="Viewport width on the paper (mm)"),
     "height": P("number", gt=0, description="Viewport height on the paper (mm)"),
     "view_center": P("point", description="Model-space point shown at the viewport centre")}, common_draw=True)
def add_viewport(ctx: Ctx, center, scale, width, height, view_center, **p):
    if ctx.layout is ctx.model:
        raise input_error("VIEWPORT_NEEDS_LAYOUT", "Viewports live in a paper-space layout",
                          hint=f"Pass layout=<name> (create one with create_layout); layouts: "
                               f"{[n for n in ctx.doc.layouts.names_in_taborder() if not is_model(n)]}")
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    ext = _model_extents(ctx)
    if view_center is None:
        if ext is None:
            raise input_error("EMPTY_MODEL", "Model space is empty: pass view_center")
        view_center = (ext.center.x, ext.center.y)
    if width is None or height is None:
        if ext is None:
            raise input_error("EMPTY_MODEL", "Model space is empty: pass width and height")
        width = width or ext.size.x * scale * 1.05
        height = height or ext.size.y * scale * 1.05
    vp = ctx.layout.add_viewport(center=center, size=(width, height), view_center_point=view_center,
                                 view_height=height / scale, dxfattribs=ctx.attribs(p))
    win = [view_center[0] - width / scale / 2, view_center[1] - height / scale / 2,
           view_center[0] + width / scale / 2, view_center[1] + height / scale / 2]
    out = {"created": [ctx.finish(vp, p)], "paper_rect": [center[0] - width / 2, center[1] - height / 2,
                                                         center[0] + width / 2, center[1] + height / 2],
           "model_window": [round(v, 6) for v in win], "scale": scale}
    if ext is not None:
        out["shows_all_model"] = (win[0] <= ext.extmin.x + 1e-6 and win[1] <= ext.extmin.y + 1e-6
                                  and win[2] >= ext.extmax.x - 1e-6 and win[3] >= ext.extmax.y - 1e-6)
        out["model_extents"] = [round(v, 6) for v in (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)]
    return out
