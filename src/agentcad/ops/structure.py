"""Layers and blocks."""
from __future__ import annotations

from ..errors import input_error
from ..model import get_tag
from .registry import REGISTRY, Ctx, Param, coerce, op

P = Param


@op("create_layer", "layer", "Create a layer (no-op with if_exists='skip').",
    {"name": P("string", True), "color": P("int", default=7, ge=1, le=255, description="ACI color"),
     "linetype": P("string", default="Continuous"), "lineweight": P("int", default=-3, description="1/100 mm, -3 = default"),
     "if_exists": P("enum", enum=["error", "skip", "update"], default="error")})
def create_layer(ctx: Ctx, name, color, linetype, lineweight, if_exists):
    if name in ctx.doc.layers:
        if if_exists == "error":
            raise input_error("LAYER_EXISTS", f"Layer {name!r} already exists", hint="Use if_exists='skip' or 'update'")
        if if_exists == "skip":
            return {"layer": name, "skipped": True}
        return modify_layer(ctx, name=name, color=color, linetype=linetype, lineweight=lineweight,
                            on=None, frozen=None, locked=None, new_name=None)
    _check_lt(ctx, linetype)
    ctx.doc.layers.add(name, color=color, linetype=linetype, lineweight=lineweight)
    return {"layer": name, "layer_created": True}


def _check_lt(ctx: Ctx, lt: str | None) -> None:
    if lt and lt not in ctx.doc.linetypes:
        raise input_error("UNKNOWN_LINETYPE", f"Linetype {lt!r} is not defined",
                          hint=f"Available: {sorted(l.dxf.name for l in ctx.doc.linetypes)}")


@op("modify_layer", "layer", "Change layer properties (color, linetype, lineweight, on, frozen, locked, rename).",
    {"name": P("string", True), "color": P("int", ge=1, le=255), "linetype": P("string"), "lineweight": P("int"),
     "on": P("bool"), "frozen": P("bool"), "locked": P("bool"), "new_name": P("string")})
def modify_layer(ctx: Ctx, name, color, linetype, lineweight, on, frozen, locked, new_name):
    if name not in ctx.doc.layers:
        raise input_error("LAYER_NOT_FOUND", f"Layer {name!r} does not exist",
                          hint=f"Layers: {[l.dxf.name for l in ctx.doc.layers]}")
    layer = ctx.doc.layers.get(name)
    if color is not None:
        layer.color = color
    if linetype is not None:
        _check_lt(ctx, linetype)
        layer.dxf.linetype = linetype
    if lineweight is not None:
        layer.dxf.lineweight = lineweight
    if on is not None:
        layer.on() if on else layer.off()
    if frozen is not None:
        layer.freeze() if frozen else layer.thaw()
    if locked is not None:
        layer.lock() if locked else layer.unlock()
    if new_name is not None and new_name != name:
        if name == "0":
            raise input_error("LAYER_PROTECTED", "Layer '0' cannot be renamed")
        if new_name in ctx.doc.layers:
            raise input_error("LAYER_EXISTS", f"Layer {new_name!r} already exists")
        layer.rename(new_name)
        for e in ctx.msp:
            if e.dxf.layer == name:
                e.dxf.layer = new_name
                ctx.touched(e)
    return {"layer": new_name or name}


@op("delete_layer", "layer", "Delete a layer. Fails if entities are on it unless delete_entities=true.",
    {"name": P("string", True), "delete_entities": P("bool", default=False)})
def delete_layer(ctx: Ctx, name, delete_entities):
    if name in ("0", "Defpoints"):
        raise input_error("LAYER_PROTECTED", f"Layer {name!r} cannot be deleted")
    if name not in ctx.doc.layers:
        raise input_error("LAYER_NOT_FOUND", f"Layer {name!r} does not exist")
    used = [e for e in ctx.msp if e.dxf.layer == name]
    if used and not delete_entities:
        raise input_error("LAYER_NOT_EMPTY", f"Layer {name!r} has {len(used)} entities",
                          entities=[e.dxf.handle for e in used[:50]], hint="Move them or pass delete_entities=true")
    deleted = [e.dxf.handle for e in used]
    for e in used:
        ctx.removed(e)
    ctx.doc.layers.remove(name)
    return {"deleted": deleted, "layer_deleted": name}


DRAW_OPS_IN_BLOCK = {"add_line", "add_polyline", "add_rectangle", "add_circle", "add_arc", "add_ellipse",
                     "add_spline", "add_point", "add_text", "add_mtext", "add_polygon", "add_donut", "add_hatch"}


@op("define_block", "block", "Define (or redefine) a block from a list of draw operations and attribute definitions.",
    {"name": P("string", True), "base_point": P("point", default=(0.0, 0.0)),
     "entities": P("list", True, description=f"Draw ops ({sorted(DRAW_OPS_IN_BLOCK)}) in block coordinates"),
     "attributes": P("list", default=None, description="[{tag, insert:[x,y], height, default}]"),
     "if_exists": P("enum", enum=["error", "skip", "redefine"], default="error")})
def define_block(ctx: Ctx, name, base_point, entities, attributes, if_exists):
    if name.startswith("*"):
        raise input_error("INVALID_NAME", "Anonymous block names (*...) are reserved")
    if name in ctx.doc.blocks:
        if if_exists == "error":
            raise input_error("BLOCK_EXISTS", f"Block {name!r} already exists", hint="Use if_exists='skip' or 'redefine'")
        if if_exists == "skip":
            return {"block": name, "skipped": True}
        blk = ctx.doc.blocks.get(name)
        for e in list(blk):
            blk.delete_entity(e)
        blk.block.dxf.base_point = (*base_point, 0)
    else:
        blk = ctx.doc.blocks.new(name, base_point=base_point)
    prev = ctx.layout
    ctx.layout = blk
    try:
        for i, raw in enumerate(entities):
            if not isinstance(raw, dict) or raw.get("op") not in DRAW_OPS_IN_BLOCK:
                raise input_error("INVALID_BLOCK_ENTITY", f"entities[{i}] must be a draw op in {sorted(DRAW_OPS_IN_BLOCK)}")
            d = REGISTRY[raw["op"]]
            params = coerce(d, raw, ctx.unit, ctx.op_index)
            params.pop("tag", None)
            d.fn(ctx, **params)
    finally:
        ctx.layout = prev
    from .registry import _point
    from ..units import parse_length
    for a in attributes or []:
        if not isinstance(a, dict) or "tag" not in a:
            raise input_error("INVALID_ATTDEF", "attribute definitions need at least a 'tag'")
        blk.add_attdef(str(a["tag"]).upper(), insert=_point(a.get("insert", [0, 0]), ctx.unit, "insert"),
                       height=parse_length(a.get("height", 2.5), ctx.unit, "height"), text=str(a.get("default", "")))
    return {"block": name, "entity_count": len(blk)}


@op("insert_block", "block", "Insert a block reference, filling attributes from 'attributes' {TAG: value}.",
    {"name": P("string", True), "insert": P("point", True), "scale": P("number", default=1.0, gt=0),
     "rotation": P("angle", default=0.0), "attributes": P("object", default=None)}, common_draw=True)
def insert_block(ctx: Ctx, name, insert, scale, rotation, attributes, **p):
    from .registry import check_tag
    if (s := check_tag(ctx, p)) is not None:
        return {"created": [], "skipped": True, "existing": s}
    if name not in ctx.doc.blocks or name.startswith("*"):
        raise input_error("BLOCK_NOT_FOUND", f"Block {name!r} is not defined",
                          hint=f"Blocks: {[b.name for b in ctx.doc.blocks if not b.name.startswith('*')]}")
    attrs = ctx.attribs(p)
    attrs.update(xscale=scale, yscale=scale, zscale=scale, rotation=rotation)
    ref = ctx.msp.add_blockref(name, insert, dxfattribs=attrs)
    if attributes:
        defs = {a.dxf.tag for a in ctx.doc.blocks.get(name).attdefs()}
        bad = [k for k in attributes if k.upper() not in defs]
        if bad:
            raise input_error("UNKNOWN_ATTRIBUTE", f"Block {name!r} has no attribute(s) {bad}", hint=f"Defined: {sorted(defs)}")
        ref.add_auto_attribs({k.upper(): str(v) for k, v in attributes.items()})
    elif any(True for _ in ctx.doc.blocks.get(name).attdefs()):
        ref.add_auto_attribs({})
    return {"created": [ctx.finish(ref, p)]}


@op("set_attributes", "block", "Set attribute values of block references.",
    {"target": P("selector", True), "values": P("object", True, description="{TAG: value}")})
def set_attributes(ctx: Ctx, target, values):
    from ..model import select
    ents = select(ctx.doc, target, ctx.refs)
    for e in ents:
        if e.dxftype() != "INSERT":
            raise input_error("UNSUPPORTED_ENTITY", "set_attributes needs INSERT entities", entities=[e.dxf.handle])
        for k, v in values.items():
            a = e.get_attrib(k.upper())
            if a is None:
                raise input_error("UNKNOWN_ATTRIBUTE", f"{e.dxf.handle} has no attribute {k!r}", entities=[e.dxf.handle])
            a.dxf.text = str(v)
        ctx.touched(e)
    return {"modified": [e.dxf.handle for e in ents]}
