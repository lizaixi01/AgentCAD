"""Analytic planar measurements and conservative spatial selection."""

from __future__ import annotations

import math

from ezdxf import bbox
from ezdxf.math import bulge_to_arc

from . import geom as G
from .errors import input_error
from .model import circle_wcs, lwpoly_wcs


def poly_metrics(vertices, closed=True):
    area = perimeter = 0.0
    for a, b in zip(vertices, vertices[1:] + (vertices[:1] if closed else [])):
        chord = math.dist(a[:2], b[:2])
        bulge = a[2] if len(a) > 2 else 0.0
        area += (a[0] * b[1] - a[1] * b[0]) / 2
        if abs(bulge) > 1e-12 and chord:
            theta = 4 * math.atan(bulge)
            radius = chord * (1 + bulge * bulge) / (4 * abs(bulge))
            area += radius * radius * (theta - math.sin(theta)) / 2
            perimeter += abs(radius * theta)
        else:
            perimeter += chord
    return area, perimeter


def flatten(vertices, steps=64):
    points = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        points.append(tuple(a[:2]))
        bulge = a[2] if len(a) > 2 else 0
        if abs(bulge) > 1e-12:
            center, _, _, radius = bulge_to_arc(a[:2], b[:2], bulge)
            start = math.atan2(a[1] - center.y, a[0] - center.x)
            theta = 4 * math.atan(bulge)
            for i in range(1, steps):
                angle = start + theta * i / steps
                points.append((center.x + radius * math.cos(angle), center.y + radius * math.sin(angle)))
    return points


def hatch_metrics(entity):
    loops = []
    for path in entity.paths:
        if hasattr(path, "vertices"):
            vertices = list(path.vertices)
            a, length = poly_metrics(vertices)
            loops.append((abs(a), length, flatten(vertices)))
        else:
            area = length = 0.0
            polygon = []
            for edge in path.edges:
                name = type(edge).__name__
                if name == "LineEdge":
                    a, b = tuple(edge.start), tuple(edge.end)
                    area += (a[0] * b[1] - a[1] * b[0]) / 2
                    length += math.dist(a, b)
                    polygon.append(a)
                elif name == "ArcEdge":
                    cx, cy = edge.center
                    r = edge.radius
                    a, b = math.radians(edge.start_angle), math.radians(edge.end_angle)
                    span = (b - a) % (2 * math.pi) or 2 * math.pi
                    if not edge.ccw:
                        a, span = b, -span
                    b = a + span
                    area += (
                        r * cx * (math.sin(b) - math.sin(a))
                        - r * cy * (math.cos(b) - math.cos(a))
                        + r * r * span
                    ) / 2
                    length += abs(r * span)
                    polygon.extend(
                        (cx + r * math.cos(a + span * i / 128), cy + r * math.sin(a + span * i / 128))
                        for i in range(128)
                    )
                else:
                    raise input_error("UNSUPPORTED_MEASUREMENT", f"Exact hatch area does not support {name}")
            loops.append((abs(area), length, polygon))
    style = entity.dxf.hatch_style
    area = perimeter = 0.0
    for i, (a, length, polygon) in enumerate(loops):
        if not polygon:
            raise input_error("EMPTY_BOUNDARY", "Cannot measure an empty hatch loop")
        depth = sum(G.point_in_polygon(polygon[0], other[2]) for j, other in enumerate(loops) if i != j)
        if style == 2 and depth > 0 or style == 1 and depth > 1:
            continue
        area += a * (-1 if depth % 2 else 1)
        perimeter += length
    return {
        "area": area,
        "perimeter": perimeter,
        "exact": True,
        "method": "analytic_bulge",
        "style": {0: "normal", 1: "outer", 2: "ignore"}[style],
        "paths": len(loops),
    }


def measure_entity(entity):
    typ = entity.dxftype()
    result = {"handle": entity.dxf.handle, "type": typ, "exact": True}
    if typ == "LWPOLYLINE":
        area, length = poly_metrics(lwpoly_wcs(entity), entity.closed)
        result.update(
            area=abs(area) if entity.closed else None,
            perimeter=length,
            method="analytic_bulge",
            closed=bool(entity.closed),
        )
    elif typ == "HATCH":
        result.update(hatch_metrics(entity))
    elif typ in ("CIRCLE", "ARC"):
        _, radius, start, end = circle_wcs(entity)
        span = 2 * math.pi if typ == "CIRCLE" else math.radians((end - start) % 360)
        result.update(
            area=math.pi * radius * radius if typ == "CIRCLE" else None,
            perimeter=radius * span,
            radius=radius,
            method="analytic_circle",
        )
    elif typ == "LINE":
        result.update(length=(entity.dxf.end - entity.dxf.start).magnitude, method="euclidean")
    else:
        raise input_error("UNSUPPORTED_MEASUREMENT", f"No exact planar measurement for {typ}")
    return result


def spatial_filter(entities, window=None, polygon=None, mode="crossing"):
    if mode not in {"crossing", "window"}:
        raise input_error("INVALID_ENUM", "selection_mode must be crossing or window")
    if window is not None and polygon is not None:
        raise input_error("AMBIGUOUS_PARAMS", "Choose window or polygon")
    if polygon is not None and (len(polygon) < 3 or abs(G.polygon_area(polygon)) < 1e-12):
        raise input_error("INVALID_POINTS", "Selection polygon needs three non-collinear points")
    if polygon is not None and mode != "window":
        raise input_error("UNSUPPORTED_SELECTION", "Polygon selection currently supports window containment")
    result = []
    for e in entities:
        ext = bbox.extents([e], fast=False)
        if not ext.has_data:
            continue
        x0, y0, x1, y1 = ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y
        if window is not None:
            (a, b), (c, d) = window
            a, c, b, d = min(a, c), max(a, c), min(b, d), max(b, d)
            keep = (
                (x0 >= a and x1 <= c and y0 >= b and y1 <= d)
                if mode == "window"
                else (x1 >= a and x0 <= c and y1 >= b and y0 <= d)
            )
        elif polygon is not None:
            # The entire entity bounding box must fit: conservative for circles and rotated geometry.
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            keep = all(G.point_in_polygon(p, polygon) for p in corners)
            # A concave selection polygon can enter a rectangle despite all four corners being inside.
            keep &= not any(x0 < p[0] < x1 and y0 < p[1] < y1 for p in polygon)
        else:
            keep = True
        if keep:
            result.append(e)
    return result
