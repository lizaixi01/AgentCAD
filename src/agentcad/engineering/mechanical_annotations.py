"""Saved manufacturing annotations for the declared revolved-profile geometry.

The contract follows the actual entities through DXF/DWG. Readback checks the
geometry, native dimension definitions, displayed values and retained notes.
It does not infer tolerances, finish or a manufacturing process.
"""
from __future__ import annotations

import math
from typing import Any

from ezdxf.tools.text import plain_mtext

from ..errors import input_error
from ..model import measure_dimension
from .records import operations


def _plain(text: str) -> str:
    text = plain_mtext(text).replace("%%C", "%%c").replace("%%c", "Ø")
    return "".join(text.replace("⌀", "Ø").replace("∅", "Ø").split())


def _rendered(doc, dimension) -> list[str] | None:
    block = doc.blocks.get(dimension.dxf.get("geometry", ""))
    if block is None:
        return None
    texts = [e for e in block if e.dxftype() in {"TEXT", "MTEXT"}]
    if not texts or any(not _visible(doc, e) or e.dxf.get(
            "height" if e.dxftype() == "TEXT" else "char_height", 0) <= 0 for e in texts):
        return None
    return sorted(_plain(e.dxf.text if e.dxftype() == "TEXT" else e.text) for e in texts)


def _visible(doc, entity) -> bool:
    if entity is None or not entity.is_alive or not doc.layers.has_entry(entity.dxf.layer):
        return False
    layer = doc.layers.get(entity.dxf.layer)
    return bool(not entity.dxf.get("invisible", 0) and not layer.is_off()
                and not layer.is_frozen() and layer.dxf.get("plot", 1))


def _model_visible(doc, entity) -> bool:
    return (_visible(doc, entity) and entity.dxf.owner == doc.modelspace().block_record_handle
            and not entity.dxf.get("paperspace", 0))


def _contract_valid(contract, part_handle) -> bool:
    """Malformed or truncated saved records must never imply complete coverage."""
    if type(contract.get("enabled")) is not bool:
        return False
    sources, annotations = contract.get("geometry"), contract.get("annotations")
    if not isinstance(sources, list) or not sources or not isinstance(annotations, list):
        return False
    if bool(annotations) != contract["enabled"]:
        return False
    required = contract.get("required")
    if not isinstance(required, dict) or bool(required) != contract["enabled"]:
        return False
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("handle"), str)
                or not isinstance(source.get("geometry"), dict) or not source["geometry"]):
            return False
    if part_handle not in [s["handle"] for s in sources]:
        return False
    handles, kinds = set(), set()
    for annotation in annotations:
        if not isinstance(annotation, dict) or any(not isinstance(annotation.get(k), str)
                for k in ("kind", "handle", "text")):
            return False
        if annotation["handle"] in handles or annotation["kind"] in kinds:
            return False
        handles.add(annotation["handle"])
        kinds.add(annotation["kind"])
        if annotation["kind"] not in required:
            return False
        if annotation.get("type") == "DIMENSION":
            value, rendered = annotation.get("value"), annotation.get("rendered")
            if (type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                    or not isinstance(annotation.get("definition"), dict)
                    or not isinstance(annotation.get("source"), dict)
                    or not isinstance(rendered, list) or not rendered
                    or not all(isinstance(s, str) for s in rendered)):
                return False
            if not _same(value, required[annotation["kind"]]):
                return False
        elif annotation.get("type") == "MTEXT":
            if (not isinstance(annotation.get("leader"), str)
                    or not isinstance(annotation.get("leader_geometry"), dict)
                    or not isinstance(annotation.get("source_pattern"), dict)
                    or required[annotation["kind"]] is not None):
                return False
        else:
            return False
    return kinds == required.keys() and (not contract["enabled"] or {"length.0", "outer_diameter.0"} <= kinds)


def _requirements(segments, patterns) -> dict[str, float | None]:
    """Record supplied roles separately from the generated entity list."""
    required = {f"length.{i}": s[0] for i, s in enumerate(segments)}
    for column, prefix in ((1, "outer_diameter"), (2, "bore_diameter")):
        seen = set()
        for i, segment in enumerate(segments):
            radius = segment[column]
            if radius and radius not in seen:
                required[f"{prefix}.{i}"] = 2 * radius
                seen.add(radius)
    if len(segments) > 1:
        required["overall_length"] = sum(s[0] for s in segments)
    for i, pattern in enumerate(patterns):
        required[f"hole_diameter.{i}"] = pattern["diameter"]
        required[f"pitch_diameter.{i}"] = pattern["pcd"]
        required[f"pattern_orientation.{i}"] = None
    return required


def geometry(entity) -> dict[str, Any] | None:
    kind = entity.dxftype()
    if kind == "LWPOLYLINE":
        return {"type": kind, "points": [list(p) for p in entity.get_points("xyseb")],
                "closed": entity.closed, "elevation": entity.dxf.elevation,
                "extrusion": list(entity.dxf.extrusion)}
    if kind == "CIRCLE":
        return {"type": kind, "center": list(entity.dxf.center), "radius": entity.dxf.radius,
                "extrusion": list(entity.dxf.extrusion)}
    if kind == "LINE":
        return {"type": kind, "start": list(entity.dxf.start), "end": list(entity.dxf.end)}
    if kind == "LEADER":
        return {"type": kind, "vertices": [list(p) for p in entity.vertices]}
    return None


def _same(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            _same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, (list, tuple)):
        return isinstance(actual, (list, tuple)) and len(actual) == len(expected) and all(
            _same(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if not isinstance(actual, (float, int)) or not math.isfinite(actual) or not math.isfinite(expected):
            return False
        # Keep roundtrip floating-point noise, but do not permit a micron-sized
        # tolerance to conceal changes in a dimension displaying eight decimals.
        tolerance = max(1e-9, 4 * math.ulp(actual), 4 * math.ulp(expected))
        return abs(actual - expected) <= tolerance
    return actual == expected


def _definition(dim) -> dict[str, Any]:
    kind = dim.dxf.dimtype & 15
    keys = ("defpoint2", "defpoint3") if kind in {0, 1} else ("defpoint", "defpoint4")
    return {"kind": kind, "points": [list(dim.dxf.get(k, (0, 0, 0))) for k in keys],
            "angle": dim.dxf.get("angle", 0) % 360 if kind == 0 else 0}


def _precision(value: float) -> int:
    for digits in range(9):
        if abs(round(value, digits) - value) <= min(1e-10, 4 * math.ulp(value)):
            return digits
    raise input_error("ANNOTATION_PRECISION", "Manufacturing dimensions support at most eight decimal places")


def _nominal_matches(actual, nominal) -> bool:
    # Coordinate subtraction can lose low bits even when both source vertices
    # are unchanged. The declared display precision is the numeric criterion;
    # source/definition integrity is checked separately, in coordinate space.
    return (isinstance(actual, (int, float)) and math.isfinite(actual)
            and f"{actual:.{_precision(nominal)}f}" == f"{nominal:.{_precision(nominal)}f}")


def _source_values(doc, source) -> list[float] | None:
    """Measure actual profiles/circles, independently of DIMENSION definitions."""
    try:
        def vertex(ref):
            entity = doc.entitydb[ref["handle"]]
            if entity.dxftype() != "LWPOLYLINE" or type(ref["index"]) is not int or ref["index"] < 0:
                raise ValueError("Invalid profile vertex")
            return entity.get_points("xy")[ref["index"]]
        def circle(handle):
            entity = doc.entitydb[handle]
            if entity.dxftype() != "CIRCLE":
                raise ValueError("Invalid source circle")
            return entity
        def span_value(item):
            axis = item["axis"]
            if type(axis) is not int or axis not in {0, 1}:
                raise ValueError("Invalid span axis")
            return float(abs(vertex(item["end"])[axis] - vertex(item["start"])[axis]))
        if source["mode"] == "span":
            return [span_value(source)]
        if source["mode"] == "spans":
            return [span_value(item) for item in source["items"]]
        if source["mode"] == "extent":
            points = doc.entitydb[source["handle"]].get_points("xy")
            return [float(max(p[0] for p in points) - min(p[0] for p in points))]
        if source["mode"] == "diameters":
            return [2 * circle(h).dxf.radius for h in source["handles"]]
        if source["mode"] == "pitch":
            center = circle(source["center"]).dxf.center
            return [2 * circle(source["circle"]).dxf.radius] + [
                2 * (circle(h).dxf.center - center).magnitude for h in source["holes"]]
    except (KeyError, TypeError, IndexError, AttributeError, ValueError):
        pass
    return None


def _orientation_matches(doc, source) -> bool:
    try:
        center, hole = doc.entitydb[source["center"]], doc.entitydb[source["first"]]
        if center.dxftype() != "CIRCLE" or hole.dxftype() != "CIRCLE":
            return False
        vector = hole.dxf.center - center.dxf.center
        actual = math.degrees(math.atan2(vector.y, vector.x)) % 360
        expected = source["angle"]
        # Zero and 360 describe the same direction.
        if actual > 180 and expected == 0:
            actual -= 360
        return _nominal_matches(actual, expected) or (expected == 0 and _nominal_matches(abs(actual), expected))
    except (KeyError, TypeError, AttributeError, ValueError):
        return False


def draw(ctx, at, segments, section_origin, patterns, source_handles, enabled=True) -> dict[str, Any]:
    contract: dict[str, Any] = {"version": 1, "enabled": enabled, "geometry": [], "annotations": [],
                                "required": _requirements(segments, patterns) if enabled else {}}
    for handle in source_handles:
        entity = ctx.doc.entitydb[handle]
        data = geometry(entity)
        if data is not None:
            contract["geometry"].append({"handle": handle, "geometry": data})
    if not enabled:
        return contract

    body = source_handles[0]
    bores = [h for h in source_handles if ctx.doc.entitydb[h].dxftype() == "LWPOLYLINE"
             and ctx.doc.entitydb[h].dxf.layer == "HIDDEN"]

    def vertex(handle, location):
        points = ctx.doc.entitydb[handle].get_points("xy")
        index = min(range(len(points)), key=lambda i: math.dist(points[i], location))
        if not _same(list(points[index]), location):
            raise input_error("ANNOTATION_SOURCE_MISMATCH", "A dimension has no matching source vertex")
        return {"handle": handle, "index": index}

    def span(first, p1, second, p2, axis):
        return {"mode": "span", "start": vertex(first, p1), "end": vertex(second, p2), "axis": axis}

    def diameter_spans(radius, column):
        # One diameter label may serve several segments. Check both ends of
        # every occurrence, including the unlabelled side of the front view.
        items, offset = [], 0
        lower, upper = (body, body) if column == 1 else (bores[1], bores[0])
        for segment in segments:
            if segment[column] == radius:
                for x in (at[0] + offset, at[0] + offset + segment[0]):
                    items.append(span(lower, [x, at[1] - radius], upper, [x, at[1] + radius], 1))
            offset += segment[0]
        return {"mode": "spans", "items": items}

    def dimension(kind, operation, value, source, location=None):
        handle = operations(ctx, [{**operation, "layer": "DIM"}])[0]["created"][0]
        entity = ctx.doc.entitydb[handle]
        override = entity.override()
        digits = _precision(value)
        # ezdxf's xround(value, 0) rounds to an integer. Use the actual display
        # increment, also meaningful in native CAD, to preserve fractional sizes.
        override.update({"dimdec": digits, "dimlfac": 1, "dimrnd": 10 ** -digits,
                         "dimzin": 8, "dimdsep": ord("."), "dimpost": "", "dimscale": 1,
                         "dimalt": 0, "dimtol": 0, "dimlim": 0, "dimlunit": 2,
                         "dimtxt": 2.5, "dimclrt": 7, "dimclrd": 7, "dimclre": 7})
        if location is not None:
            override.set_location(location)
            override.update({"dimtih": 1, "dimtoh": 1})
        override.render()
        number = f"{value:.{digits}f}"
        prefix = "Ø" if operation["op"] == "add_diameter_dim" else ""
        expected_text = _plain(operation.get("text", "<>").replace("<>", prefix + number))
        if _rendered(ctx.doc, entity) != [expected_text]:
            raise input_error("ANNOTATION_DISPLAY_MISMATCH", "Rendered dimension differs from the supplied size")
        measured = _source_values(ctx.doc, source)
        if not measured or not all(_nominal_matches(m, value) for m in measured):
            raise input_error("ANNOTATION_SOURCE_MISMATCH", "Source geometry does not express the nominal dimension")
        contract["annotations"].append({
            "kind": kind, "handle": handle, "type": "DIMENSION", "value": value,
            "definition": _definition(entity), "text": entity.dxf.get("text", ""),
            "rendered": [expected_text], "source": source,
        })

    length, radius = sum(s[0] for s in segments), max(s[1] for s in segments)
    cursor = 0
    outer_seen, inner_seen = set(), set()
    for index, (step, outer, inner) in enumerate(segments):
        dimension(f"length.{index}", {
            "op": "add_linear_dim", "p1": [at[0] + cursor, at[1] + outer],
            "p2": [at[0] + cursor + step, at[1] + outer],
            "base": [at[0], at[1] + radius + 10]}, step,
            {"mode": "spans", "items": [span(body, [at[0] + cursor, at[1] + sign * outer],
                body, [at[0] + cursor + step, at[1] + sign * outer], 0) for sign in (-1, 1)]})
        x = at[0] + cursor + step / 2
        if outer not in outer_seen:
            dimension(f"outer_diameter.{index}", {
                "op": "add_linear_dim", "orientation": "vertical", "text": "%%c<>",
                "p1": [x, at[1] - outer], "p2": [x, at[1] + outer],
                "base": [at[0] + length + 8 + 8 * len(outer_seen), at[1]]}, 2 * outer,
                diameter_spans(outer, 1))
            outer_seen.add(outer)
        if inner and inner not in inner_seen:
            origin = section_origin or at
            bx = origin[0] + cursor + step / 2
            base_x = (origin[0] - 8 - 8 * len(inner_seen) if section_origin else
                      at[0] + length + 8 + 8 * (len({s[1] for s in segments}) + len(inner_seen)))
            through = all(s[2] == inner for s in segments)
            dimension(f"bore_diameter.{index}", {
                "op": "add_linear_dim", "orientation": "vertical",
                "text": "%%c<> THRU" if through else "%%c<>",
                "p1": [bx, at[1] - inner], "p2": [bx, at[1] + inner],
                "base": [base_x, at[1]]}, 2 * inner,
                diameter_spans(inner, 2))
            inner_seen.add(inner)
        cursor += step
    if len(segments) > 1:
        dimension("overall_length", {
            "op": "add_linear_dim", "p1": [at[0], at[1]], "p2": [at[0] + length, at[1]],
            "base": [at[0], at[1] + radius + 20]}, length, {"mode": "extent", "handle": body})

    for index, pattern in enumerate(patterns):
        center, holes = pattern["center"], pattern["holes"]
        y = center[1] - radius - 12 - index * 25
        dimension(f"hole_diameter.{index}", {
            "op": "add_diameter_dim", "target": holes[0], "angle": 45,
            "text": f"{len(holes)}X <>"}, pattern["diameter"],
            {"mode": "diameters", "handles": holes}, [center[0] + radius + 4, y])
        dimension(f"pitch_diameter.{index}", {
            "op": "add_diameter_dim", "target": pattern["pitch_circle"], "angle": 135,
            "text": "PCD <>"}, pattern["pcd"],
            {"mode": "pitch", "center": pattern["center_handle"], "circle": pattern["pitch_circle"], "holes": holes},
            [center[0] - radius - 4, y])
        count = len(holes)
        spacing = str(360 // count) if 360 % count == 0 else f"360/{count}"
        start = f"{pattern['start_angle']:.{_precision(pattern['start_angle'])}f}"
        note = ((f"EQ SP {spacing} deg; " if count > 1 else "") +
                f"FIRST {start} deg CCW FROM +X")
        first = ctx.doc.entitydb[holes[0]].dxf.center
        end = [center[0] - radius, center[1] + radius + 14 + index * 8]
        created = operations(ctx, [{"op": "add_leader", "points": [[first.x + pattern["diameter"] / 2, first.y],
            [end[0] - 5, end[1]], end], "text": note, "layer": "DIM", "color": 7,
            "text_height": 2.5}])[0]["created"]
        source_pattern = {"center": pattern["center_handle"], "first": holes[0], "angle": pattern["start_angle"]}
        if not _orientation_matches(ctx.doc, source_pattern):
            raise input_error("ANNOTATION_SOURCE_MISMATCH", "Source geometry does not express the nominal orientation")
        contract["annotations"].append({"kind": f"pattern_orientation.{index}", "handle": created[1],
            "type": "MTEXT", "text": note, "leader": created[0],
            "leader_geometry": geometry(ctx.doc.entitydb[created[0]]), "source_pattern": source_pattern})
    return contract


def check(doc, contract, part_handle) -> tuple[list[dict], list[dict]]:
    issues, annotations = [], []
    if not isinstance(contract, dict) or contract.get("version") != 1:
        return [{"code": "MANUFACTURING_COVERAGE_UNRECORDED", "handle": part_handle}], annotations
    if not _contract_valid(contract, part_handle):
        return [{"code": "MANUFACTURING_RECORD_INVALID", "handle": part_handle}], annotations
    for source in contract["geometry"]:
        entity = doc.entitydb.get(source["handle"])
        if not _model_visible(doc, entity) or not _same(geometry(entity), source["geometry"]):
            issues.append({"code": "MANUFACTURING_GEOMETRY_CHANGED", "handle": source["handle"], "part": part_handle})
    for expected in contract["annotations"]:
        handle = expected["handle"]
        entity = doc.entitydb.get(handle)
        valid = _model_visible(doc, entity) and entity.dxftype() == expected["type"]
        measured = None
        source_values = None
        if valid and entity.dxftype() == "DIMENSION":
            measured = measure_dimension(entity)
            source_values = _source_values(doc, expected["source"])
            override = entity.override()
            valid = (_nominal_matches(measured, expected["value"]) and _same(_definition(entity), expected["definition"])
                     and bool(source_values) and all(_nominal_matches(m, expected["value"]) for m in source_values)
                     and entity.dxf.get("text", "") == expected["text"]
                     and override.get("dimlfac", 1) == 1
                     and override.get("dimdec", 2) == _precision(expected["value"])
                     and override.get("dimdsep", ord(".")) == ord(".")
                     and override.get("dimpost", "") == ""
                     and override.get("dimlunit", 2) == 2
                     and all(override.get(k, 0) == 0 for k in ("dimalt", "dimtol", "dimlim"))
                     and override.get("dimscale", 1) == 1 and override.get("dimtxt", 2.5) == 2.5
                     and override.get("dimrnd", 0) == 10 ** -_precision(expected["value"])
                     and _rendered(doc, entity) == expected["rendered"])
        elif valid:
            leader = doc.entitydb.get(expected["leader"])
            valid = (_plain(entity.text) == _plain(expected["text"]) and _model_visible(doc, leader)
                     and entity.dxf.char_height > 0
                     and _orientation_matches(doc, expected["source_pattern"])
                     and _same(geometry(leader), expected["leader_geometry"]))
        annotations.append({"kind": expected["kind"], "handle": handle, "measurement": measured,
                            "source_measurements": source_values, "passed": bool(valid)})
        if not valid:
            issues.append({"code": "MANUFACTURING_ANNOTATION_MISMATCH", "handle": handle,
                           "kind": expected["kind"], "part": part_handle})
    return issues, annotations
