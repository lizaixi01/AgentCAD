"""Entity-local domain records that travel with DXF geometry."""

import json
import math

from ..errors import input_error


def put(doc, entity, domain, record):
    app = "AGENTCAD_" + domain.upper()
    if app not in doc.appids:
        doc.appids.add(app)
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False)
    chunks = [raw[i : i + 240] for i in range(0, len(raw), 240)]
    # AutoCAD limits all XDATA on one entity to 16 KiB. Large profile/annotation
    # manifests belong in an entity-owned XRECORD; keep only a small locator in
    # XDATA so existing domain discovery continues to work.
    if len(raw) > 8000:
        extension = entity.get_extension_dict() if entity.has_extension_dict else entity.new_extension_dict()
        xrecord = extension.get(app) or extension.add_xrecord(app)
        xrecord.reset([(1, chunk) for chunk in chunks])
        entity.set_xdata(app, [(1000, "$AGENTCAD_XRECORD_V1")])
    else:
        entity.set_xdata(app, [(1000, chunk) for chunk in chunks])


def get(entity, domain):
    app = "AGENTCAD_" + domain.upper()
    if not entity.has_xdata(app):
        return None
    try:
        raw = "".join(t.value for t in entity.get_xdata(app) if t.code == 1000)
        if raw == "$AGENTCAD_XRECORD_V1":
            if not entity.has_extension_dict:
                raise ValueError("Missing domain XRECORD")
            xrecord = entity.get_extension_dict().get(app)
            if xrecord is None or xrecord.dxftype() != "XRECORD":
                raise ValueError("Missing domain XRECORD")
            raw = "".join(t.value for t in xrecord.tags if t.code == 1)
        record = json.loads(raw)
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
