"""Transactional operation engine.

``execute`` runs an operation batch against an in-memory document:

1. every op is validated (known op, policy allow-list, typed params, units)
   before anything is touched;
2. ops run in order; a failure aborts the whole batch (the caller discards the
   in-memory document, so the file on disk is never partially modified);
3. results carry created / modified / deleted entity ids per op.

``reconcile=True`` is used for spec-driven revisions: an op whose tag already
exists updates the existing entity *in place* (same handle) instead of adding
a new one, unchanged entities are left untouched, and tags that belonged to
the previous plan but not to the new one are removed.
"""
from __future__ import annotations

import difflib
import traceback
from typing import Any

from ezdxf.document import Drawing

from .errors import AgentCADError, input_error, policy_error
from .model import entity_to_dict, get_tag, set_tag
from .ops import REGISTRY, Ctx, coerce
from .policy import Policy


def prevalidate(ops: list[Any], unit: str | None, policy: Policy) -> list[dict[str, Any]]:
    if not isinstance(ops, list):
        raise input_error("INVALID_PLAN", "operations must be a list")
    if len(ops) > policy.max_ops_per_batch:
        raise policy_error("BUDGET_EXCEEDED", f"{len(ops)} operations exceed the batch limit {policy.max_ops_per_batch}")
    out = []
    for i, raw in enumerate(ops):
        if not isinstance(raw, dict) or not isinstance(raw.get("op"), str):
            raise input_error("INVALID_OP", f"operations[{i}] must be an object with an 'op' field", op_index=i)
        name = raw["op"]
        if name not in REGISTRY:
            close = difflib.get_close_matches(name, REGISTRY.keys(), n=3)
            raise input_error("UNKNOWN_OP", f"Unknown operation {name!r}", op_index=i, op=name,
                              hint=f"Did you mean {close}?" if close else "Use list_operations for the catalog")
        policy.check_op_allowed(name, i)
        out.append(coerce(REGISTRY[name], raw, unit, i))
    return out


def execute(doc: Drawing, ops: list[dict[str, Any]], unit: str | None, policy: Policy, *,
            reconcile: bool = False, previous_tags: set[str] | None = None) -> dict[str, Any]:
    params_list = prevalidate(ops, unit, policy)
    ctx = Ctx(doc, unit, policy)
    results = []
    produced_tags: set[str] = set()
    unchanged: list[str] = []
    for i, (raw, params) in enumerate(zip(ops, params_list)):
        name = raw["op"]
        opdef = REGISTRY[name]
        ctx.op_index = i
        try:
            tag = params.get("tag") if opdef.common_draw else None
            if reconcile and tag and ctx.tags().get(tag):
                res = _reconcile_op(ctx, opdef, params, tag, unchanged)
            else:
                res = opdef.fn(ctx, **params)
            if tag:
                produced_tags.add(tag)
        except AgentCADError as exc:
            exc.op_index = i
            exc.op = name
            exc.partial_changes = False
            raise
        except Exception as exc:  # library failure: report as internal, keep traceback for the journal
            raise AgentCADError("INTERNAL_ERROR", f"{name} failed: {type(exc).__name__}: {exc}", category="internal",
                                op=name, op_index=i, details={"traceback": traceback.format_exc(limit=6)})
        ctx.refs[i] = list(res.get("created") or res.get("modified") or res.get("existing") or [])
        results.append({"index": i, "op": name, **res})
    if reconcile and previous_tags:
        stale = sorted(previous_tags - produced_tags)
        for t in stale:
            for e in list(ctx.tags().get(t, [])):
                ctx.removed(e)
        if stale:
            results.append({"index": len(results), "op": "reconcile_remove_stale", "deleted_tags": stale})
    n = len(doc.modelspace())
    if n > policy.max_entities:
        raise policy_error("BUDGET_EXCEEDED", f"Drawing would contain {n} entities (limit {policy.max_entities})")
    return {"results": results, "added": ctx.added, "modified": ctx.modified, "deleted": ctx.deleted,
            "unchanged": unchanged, "tags": sorted(produced_tags)}


def _comparable(e) -> dict[str, Any]:
    d = entity_to_dict(e)
    d.pop("id", None)
    return d


def _reconcile_op(ctx: Ctx, opdef, params: dict[str, Any], tag: str, unchanged: list[str]) -> dict[str, Any]:
    old = ctx.tags()[tag][0]
    p = dict(params)
    p["tag"] = None
    res = opdef.fn(ctx, **p)
    created = res.get("created") or []
    if len(created) != 1:
        # multi-entity ops (e.g. leader + text): replace wholesale
        for e in list(ctx.tags().get(tag, [])):
            ctx.removed(e)
        if created:
            set_tag(ctx.doc, ctx.doc.entitydb[created[0]], tag)
        ctx._tags = None
        return res
    new = ctx.doc.entitydb[created[0]]
    if old.dxftype() != new.dxftype():
        ctx.removed(old)
        set_tag(ctx.doc, new, tag)
        ctx._tags = None
        return {"created": created, "replaced": old.dxf.handle}
    a, b = _comparable(old), _comparable(new)
    b["tag"] = tag
    if a == b:
        _discard(ctx, new)
        unchanged.append(old.dxf.handle)
        return {"unchanged": [old.dxf.handle]}
    update_in_place(ctx, old, new)
    _discard(ctx, new)
    ctx.touched(old)
    return {"modified": [old.dxf.handle]}


def _discard(ctx: Ctx, e) -> None:
    blk = e.dxf.get("geometry") if e.dxftype() == "DIMENSION" else None
    h = e.dxf.handle
    if h in ctx.added:
        ctx.added.remove(h)
    ctx.msp.delete_entity(e)
    if blk and blk in ctx.doc.blocks:
        ctx.doc.blocks.delete_block(blk, safe=False)


COPY_ATTRS = {
    "LINE": ["start", "end"],
    "CIRCLE": ["center", "radius"],
    "ARC": ["center", "radius", "start_angle", "end_angle"],
    "POINT": ["location"],
    "TEXT": ["text", "insert", "align_point", "height", "rotation", "halign", "valign"],
    "MTEXT": ["insert", "char_height", "width", "attachment_point"],
    "DIMENSION": ["defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "angle", "text", "dimtype",
                  "text_midpoint", "dimstyle"],
    "INSERT": ["name", "insert", "xscale", "yscale", "zscale", "rotation"],
    "ELLIPSE": ["center", "major_axis", "ratio", "start_param", "end_param"],
}


def update_in_place(ctx: Ctx, old, new) -> None:
    t = old.dxftype()
    for k in ("layer", "color", "linetype", "lineweight"):
        if new.dxf.hasattr(k):
            old.dxf.set(k, new.dxf.get(k))
        elif old.dxf.hasattr(k):
            old.dxf.discard(k)
    if t == "LWPOLYLINE":
        old.set_points(list(new.get_points("xyseb")), format="xyseb")
        old.closed = new.closed
    elif t == "SPLINE":
        old.fit_points = list(new.fit_points)
        old.control_points = list(new.control_points)
    elif t in COPY_ATTRS:
        for k in COPY_ATTRS[t]:
            if new.dxf.hasattr(k):
                old.dxf.set(k, new.dxf.get(k))
            elif old.dxf.hasattr(k):
                old.dxf.discard(k)
        if t == "MTEXT":
            old.text = new.text
        if t == "INSERT":
            for a in new.attribs:
                oa = old.get_attrib(a.dxf.tag)
                if oa is not None:
                    oa.dxf.text = a.dxf.text
        if t == "DIMENSION":
            from .ops.edit import rerender_dimension
            rerender_dimension(ctx, old)
    else:
        raise AgentCADError("UNSUPPORTED_ENTITY", f"In-place update of {t} is not supported", category="internal",
                            entities=[old.dxf.handle])


def plan_tags(ops: list[dict[str, Any]]) -> set[str]:
    return {o["tag"] for o in ops if isinstance(o, dict) and o.get("tag")}


def tags_in(doc: Drawing) -> set[str]:
    return {t for e in doc.modelspace() if (t := get_tag(e))}
