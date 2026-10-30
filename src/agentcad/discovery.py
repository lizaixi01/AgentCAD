"""Searchable native command catalogue; aliases describe implemented workflows."""

import re

from .errors import input_error
from .ops import REGISTRY

ALIASES = {
    "add_line": "LINE",
    "add_circle": "CIRCLE",
    "add_arc": "ARC",
    "add_rectangle": "RECTANG RECTANGLE",
    "add_polyline": "PLINE",
    "add_hatch": "HATCH BHATCH",
    "trace_boundary": "BPOLY BOUNDARY",
    "fillet": "FILLET",
    "chamfer": "CHAMFER",
    "trim": "TRIM",
    "extend": "EXTEND",
    "move": "MOVE",
    "copy": "COPY",
    "rotate": "ROTATE",
    "scale": "SCALE",
    "offset": "OFFSET",
    "mirror": "MIRROR",
    "join": "JOIN PEDIT",
    "remove_duplicates": "OVERKILL",
    "delete": "ERASE",
    "change_space": "CHSPACE",
    "inspect_entities": "QSELECT SELECT FILTER",
    "block_from_entities": "WBLOCK",
    "export_drawing": "EXPORT SAVEAS",
    "create_layer": "LAYER",
    "set_page_setup": "PAGESETUP",
    "add_linear_dim": "DIMLINEAR",
    "add_diameter_dim": "DIMDIAMETER",
    "measure_entities": "AREA MEASUREGEOM",
}


def search(query, limit, tools):
    terms = re.findall(r"[\w]+", query.lower())
    if not terms or not 1 <= limit <= 30:
        raise input_error("BAD_PARAMETER", "Search needs a query and limit between 1 and 30")
    rows = [
        {"name": n, "kind": "operation", "tool": "apply_operations", "description": o.description}
        for n, o in REGISTRY.items()
    ]
    rows += [
        {"name": n, "kind": "tool", "tool": n, "description": fn.__doc__ or n.replace("_", " ")}
        for n, fn in tools.items()
    ]
    for row in rows:
        aliases = ALIASES.get(row["name"], "").lower().split()
        words = set(re.findall(r"\w+", (row["name"].replace("_", " ") + " " + row["description"]).lower()))
        row["score"] = sum(
            100 if t in aliases else 20 if t == row["name"].lower() else 3 if t in words else 0 for t in terms
        )
        row["aliases"] = ALIASES.get(row["name"], "").split()
    return sorted([r for r in rows if r["score"]], key=lambda r: (-r["score"], r["name"]))[:limit]
