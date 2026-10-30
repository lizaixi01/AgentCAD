"""Entity-local domain records that travel with DXF geometry."""

import json
import math

from ..errors import input_error


def put(doc, entity, domain, record):
    app = "AGENTCAD_" + domain.upper()
    if app not in doc.appids:
        doc.appids.add(app)
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False)
    entity.set_xdata(app, [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])


def get(entity, domain):
    app = "AGENTCAD_" + domain.upper()
    if not entity.has_xdata(app):
        return None
    try:
        record = json.loads("".join(t.value for t in entity.get_xdata(app) if t.code == 1000))
        if not isinstance(record, dict):
            raise ValueError("Domain record must be an object")
        return record
    except (ValueError, TypeError):
        raise input_error("INVALID_DOMAIN_RECORD", f"Malformed {domain} record on {entity.dxf.handle}")


def number(value, name, positive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or positive
        and value <= 0
    ):
        raise input_error("INVALID_VALUE", f"{name} must be a finite {'positive ' if positive else ''}number")
    return float(value)


def point(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise input_error("INVALID_POINT", f"{name} must be [x,y]")
    return [number(v, name) for v in value]


def operations(ctx, items):
    """Reuse primitive validation and policy inside one surrounding transaction."""
    from ..engine import prevalidate
    from ..ops import REGISTRY

    results = []
    for raw, params in zip(items, prevalidate(items, ctx.unit, ctx.policy)):
        params.pop("layout", None)
        results.append(REGISTRY[raw["op"]].fn(ctx, **params))
    return results


def drawing_conventions(doc):
    """Use legible metric annotations and conventional engineering layers.

    Header defaults matter to other CAD readers even when individual dimensions
    already carry the AgentCAD style. Keep both representations consistent.
    """
    doc.header["$DIMTXT"] = 2.5
    doc.header["$DIMDSEP"] = ord(".")
    for name in ("Standard", "AGENTCAD"):
        if name in doc.dimstyles:
            doc.dimstyles.get(name).dxf.dimtxt = 2.5
            doc.dimstyles.get(name).dxf.dimdsep = ord(".")
    if "HIDDEN" not in doc.linetypes:
        doc.linetypes.add("HIDDEN", pattern=[9.525, 6.35, -3.175], description="Hidden edges")
    for name, color, linetype in (("DIM", 2, "Continuous"), ("HIDDEN", 3, "HIDDEN")):
        if name not in doc.layers:
            doc.layers.add(name, color=color, linetype=linetype)
        else:
            doc.layers.get(name).dxf.color = color
            doc.layers.get(name).dxf.linetype = linetype
