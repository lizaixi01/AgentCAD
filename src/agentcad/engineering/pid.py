"""Port-connected P&ID creation and independent graph reconstruction from DXF."""

from __future__ import annotations

import math
import uuid

from ..errors import input_error
from ..ops.library import add_pid_symbol
from .records import get, number, put

SECTIONS = ("equipment", "valves", "instruments", "connectors")
CLASSES = {"process_major", "process_minor", "electric", "pneumatic", "hydraulic"}


def _node(ctx, section, item):
    ident = item.get("id")
    if not isinstance(ident, str) or not ident:
        raise input_error("MISSING_PARAM", "Every P&ID symbol needs a nonempty id")
    at = [number(item.get(k), f"{ident}.{k}") for k in ("x", "y")]
    rotation = number(item.get("rotation", 0), "rotation")
    size = number(item.get("scale", 1), "scale", True)
    symbol = item.get("symbol", "")
    tag = str(item.get("tag", ident))
    if section == "connectors" or symbol in {"vertical_vessel", "vessel_vertical"}:
        name = "ACPID_" + uuid.uuid4().hex[:12]
        block = ctx.doc.blocks.new(name)
        if section == "connectors":
            block.add_lwpolyline([(0, -3), (7, -3), (10, 0), (7, 3), (0, 3)], close=True)
            ports = {"in": [0, 0], "out": [10, 0]}
        else:
            params = item.get("params", {})
            width = number(params.get("width", 20), "vessel.width", True)
            height = number(params.get("height", 40), "vessel.height", True)
            if height < width:
                raise input_error("INVALID_VALUE", "Vertical vessel height must be at least its width")
            radius, straight = width / 2, (height - width) / 2
            block.add_line((-radius, -straight), (-radius, straight))
            block.add_line((radius, -straight), (radius, straight))
            block.add_arc((0, straight), radius, 0, 180)
            block.add_arc((0, -straight), radius, 180, 360)
            ports = {}
            for nozzle in params.get(
                "nozzles",
                [
                    {"name": "in", "side": "left", "fraction": 0.5},
                    {"name": "out", "side": "top", "fraction": 0.5},
                ],
            ):
                fraction = number(nozzle.get("fraction", 0.5), "nozzle.fraction")
                if not 0 <= fraction <= 1:
                    raise input_error("INVALID_VALUE", "Nozzle fraction must be in 0..1")
                side = nozzle.get("side")
                positions = {
                    "left": [-radius, (fraction - 0.5) * 2 * straight],
                    "right": [radius, (fraction - 0.5) * 2 * straight],
                    "top": [(fraction - 0.5) * width, height / 2],
                    "bottom": [(fraction - 0.5) * width, -height / 2],
                }
                if side not in positions:
                    raise input_error("INVALID_VALUE", "Nozzle side must be left, right, top or bottom")
                ports[nozzle["name"]] = positions[side]
                a = positions[side]
                dx, dy = {"left": (-2, 0), "right": (2, 0), "top": (0, 2), "bottom": (0, -2)}[side]
                block.add_line(a, (a[0] + dx, a[1] + dy))
                ports[nozzle["name"]] = [a[0] + dx, a[1] + dy]
        block.add_attdef("TAG", (0, -10), height=2.5)
        e = ctx.layout.add_blockref(
            name,
            at,
            dxfattribs=ctx.attribs({"layer": "PID_SYMBOL"})
            | {"rotation": rotation, "xscale": size, "yscale": size, "zscale": size},
        )
        e.add_auto_attribs({"TAG": tag})
        ctx.created(e)
    else:
        if section == "valves":
            symbol = (
                "control_valve"
                if item.get("actuator")
                else {"globe": "globe_valve", "gate": "gate_valve"}.get(symbol, symbol)
            )
            ports = {"in": [-0.5, 0], "out": [0.5, 0], "signal": [0, 0.9]}
        elif section == "instruments":
            symbol = "instrument_" + item.get("type", "field")
            ports = {"signal": [0, 0]}
        elif symbol == "centrifugal_pump":
            ports = {"suction": [-0.5, 0], "discharge": [0.65, 0.5]}
        else:
            raise input_error("UNSUPPORTED_SYMBOL", f"No port model for {symbol!r}")
        result = add_pid_symbol(ctx, symbol, at, None, rotation, 10 * size, tag, layer="PID_SYMBOL")
        e = ctx.doc.entitydb[result["created"][0]]
    record = {
        "role": "node",
        "id": ident,
        "tag": tag,
        "category": section,
        "symbol": symbol,
        "ports": ports,
        "description": item.get("desc", ""),
    }
    put(ctx.doc, e, "pid", record)
    return e, record


def draw(ctx, spec):
    if ctx.layout.name != "Model" or ctx.unit != "mm":
        raise input_error("UNSUPPORTED_DRAWING", "P&ID generation requires model space and millimetres")
    start = len(ctx.added)
    if not isinstance(spec, dict) or set(spec) - {*SECTIONS, "lines", "sheet"}:
        raise input_error(
            "INVALID_SPEC", "P&ID spec accepts equipment, valves, instruments, connectors, lines and sheet"
        )
    nodes = {}
    items = [(section, item) for section in SECTIONS for item in spec.get(section, [])]
    if len(items) + len(spec.get("lines", [])) > 2000:
        raise input_error("BUDGET_EXCEEDED", "P&ID spec exceeds 2000 symbols and lines")
    for section, item in items:
        if item.get("id") in nodes:
            raise input_error("DUPLICATE_ID", f"Duplicate symbol id {item['id']}")
        e, record = _node(ctx, section, item)
        nodes[record["id"]] = (e, record)

    def endpoint(reference):
        ident, _, port = reference.partition(".")
        if ident not in nodes:
            raise input_error("UNKNOWN_ENDPOINT", f"Unknown P&ID endpoint {reference!r}")
        e, record = nodes[ident]
        if not port and len(record["ports"]) == 1:
            port = next(iter(record["ports"]))
        if port not in record["ports"]:
            raise input_error("UNKNOWN_PORT", f"Unknown port {reference!r}")
        p = e.matrix44().transform((*record["ports"][port], 0))
        return [p.x, p.y]

    lines = list(spec.get("lines", []))
    for item in spec.get("connectors", []):
        if "from" in item:
            lines.append(
                {
                    "from": item["from"],
                    "to": item["id"] + ".in",
                    "class": item.get("class", "process_major"),
                    "number": item.get("number"),
                }
            )
        elif "to" in item:
            lines.append(
                {
                    "from": item["id"] + ".out",
                    "to": item["to"],
                    "class": item.get("class", "process_major"),
                    "number": item.get("number"),
                }
            )
    sequence = 0
    for line in lines:
        cls = line.get("class", "process_major")
        if cls not in CLASSES:
            raise input_error("INVALID_LINE_CLASS", cls)
        a, b = endpoint(line["from"]), endpoint(line["to"])
        points = [a, b] if a[0] == b[0] or a[1] == b[1] else [a, [b[0], a[1]], b]
        if "route" in line:
            from .records import point

            points = [a, *[point(p, "route") for p in line["route"]], b]
        is_signal = cls in {"electric", "pneumatic"}
        if not is_signal:
            sequence += 1
        number_ = None if is_signal else line.get("number") or str(sequence)
        attrs = ctx.attribs(
            {"layer": "PID_" + cls.upper(), "linetype": "DASHED" if is_signal else "CONTINUOUS"}
        )
        e = ctx.layout.add_lwpolyline(points, dxfattribs=attrs)
        ctx.created(e)
        put(
            ctx.doc,
            e,
            "pid",
            {
                "role": "edge",
                "class": cls,
                "line_number": number_,
                "from_port": line["from"],
                "to_port": line["to"],
                "service": line.get("service"),
                "size": line.get("size"),
            },
        )
        if number_:
            text = ctx.layout.add_text(number_, height=2.5, dxfattribs=ctx.attribs({"layer": "PID_TEXT"}))
            text.set_placement(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 3))
            ctx.created(text)
    return {"created": list(ctx.added[start:]), "nodes": len(nodes), "lines": len(lines)}


def read(doc):
    nodes, edges, issues = [], [], []
    ports = []
    for e in doc.modelspace():
        record = get(e, "pid")
        if not record or record.get("role") != "node":
            continue
        if e.dxftype() != "INSERT":
            issues.append({"code": "PID_NODE_TYPE", "handle": e.dxf.handle})
            continue
        attrs = {a.dxf.tag: a.dxf.text for a in e.attribs}
        tag = (
            attrs.get("TAG")
            or "-".join(filter(None, [attrs.get("FUNC"), attrs.get("LOOP")]))
            or record["tag"]
        )
        node = {
            "id": record["id"],
            "tag": tag,
            "category": record["category"],
            "handle": e.dxf.handle,
            "symbol": record["symbol"],
        }
        nodes.append(node)
        for name, at in record["ports"].items():
            p = e.matrix44().transform((*at, 0))
            ports.append((node, name, (p.x, p.y)))
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids):
        issues.append({"code": "PID_DUPLICATE_ID"})
    dangling = 0
    for e in doc.modelspace():
        record = get(e, "pid")
        if not record or record.get("role") != "edge":
            continue
        if e.dxftype() != "LWPOLYLINE" or len(e) < 2:
            issues.append({"code": "PID_EDGE_TYPE", "handle": e.dxf.handle})
            dangling += 2
            continue
        points = list(e.get_points("xy"))
        ends = []
        for point_ in (points[0], points[-1]):
            matches = [(node, port) for node, port, at in ports if math.dist(at, point_) < 1e-6]
            ends.append(matches[0] if len(matches) == 1 else None)
            dangling += len(matches) != 1
        edge = {
            "handle": e.dxf.handle,
            "from_tag": ends[0][0]["tag"] if ends[0] else None,
            "to_tag": ends[1][0]["tag"] if ends[1] else None,
            "line_class": record["class"],
            "line_number": record["line_number"],
            "number_source": "xdata",
            "confidence": 1.0 if all(ends) else 0.0,
        }
        edges.append(edge)
    if dangling:
        issues.append({"code": "PID_DANGLING", "count": dangling})
    instruments = []
    for node in nodes:
        if node["category"] == "instruments":
            attached = sorted(
                {
                    e["to_tag"] if e["from_tag"] == node["tag"] else e["from_tag"]
                    for e in edges
                    if node["tag"] in {e["from_tag"], e["to_tag"]}
                }
                - {None}
            )
            instruments.append({"tag": node["tag"], "connected_to": ",".join(attached)})
    return {
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "dangling": dangling,
                "confidence_min": min((e["confidence"] for e in edges), default=0),
            },
        },
        "critique": issues,
        "line_list": edges,
        "instrument_index": sorted(instruments, key=lambda r: r["tag"]),
        "equipment_list": sorted([n for n in nodes if n["category"] == "equipment"], key=lambda r: r["tag"]),
    }
