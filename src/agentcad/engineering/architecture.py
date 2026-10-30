"""Orthogonal wall plans, hosted openings, stairs, room detection and schedules.

Room detection floods the complement of actual wall solids. Opening threshold
rectangles close door/window gaps for net room areas, independent of room labels.
"""

from __future__ import annotations

from collections import defaultdict, deque
import math
import uuid

from ezdxf.math import Matrix44

from .. import geom as G
from ..errors import input_error
from .records import drawing_conventions, get, number, operations, point, put

WALL, SEAL = "ARCH_WALL", "ARCH_THRESHOLD"


def _rect(space, box, layer):
    a, b, c, d = box
    return space.add_lwpolyline([(a, b), (c, b), (c, d), (a, d)], close=True, dxfattribs={"layer": layer})


def _wall_segments(walls):
    out = []
    ids = set()
    for wall in walls:
        ident = wall.get("id")
        if not ident or ident in ids:
            raise input_error("INVALID_ID", "Wall ids must be unique and nonempty")
        ids.add(ident)
        pts = [point(p, "wall.axis") for p in wall.get("axis", [])]
        thick = number(wall.get("thickness"), "wall.thickness", True)
        if len(pts) < 2:
            raise input_error("INVALID_AXIS", "Wall axis needs at least two points")
        distance = 0
        for i, (a, b) in enumerate(zip(pts, pts[1:] + (pts[:1] if wall.get("closed") else []))):
            length = math.dist(a, b)
            if length <= 0 or abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                raise input_error("UNSUPPORTED_AXIS", "Wall segments must be nonzero and axis aligned")
            dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            out.append(
                {
                    "id": ident,
                    "index": i,
                    "start": a,
                    "end": b,
                    "length": length,
                    "offset": distance,
                    "thickness": thick,
                    "direction": (dx, dy),
                    "material": wall.get("material", ""),
                }
            )
            distance += length
    return out


def _bounds(points):
    return [
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    ]


def _world(seg, along, across):
    a, (dx, dy) = seg["start"], seg["direction"]
    return (a[0] + dx * along - dy * across, a[1] + dy * along + dx * across)


def _material_boxes(doc):
    boxes = []
    for e in doc.modelspace():
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == WALL and e.closed:
            points = list(e.get_points("xy"))
            box = _bounds(points)
            if abs(abs(G.polygon_area(points)) - (box[2] - box[0]) * (box[3] - box[1])) > 1e-3:
                raise input_error("NON_ORTHOGONAL_WALL", "Room detection requires rectangular wall solids")
            boxes.append(box)
        elif e.dxftype() == "INSERT":
            record = get(e, "arch")
            if record and record.get("role") == "opening":
                for child in e.virtual_entities():
                    if child.dxftype() == "LWPOLYLINE" and child.dxf.layer == SEAL:
                        boxes.append(_bounds(list(child.get_points("xy"))))
    return boxes


def detect_rooms(doc):
    boxes = _material_boxes(doc)
    if not boxes:
        return []
    xs = sorted({v for b in boxes for v in (b[0], b[2])})
    ys = sorted({v for b in boxes for v in (b[1], b[3])})
    margin = max(xs[-1] - xs[0], ys[-1] - ys[0]) * 0.1 + 1
    xs, ys = [xs[0] - margin, *xs, xs[-1] + margin], [ys[0] - margin, *ys, ys[-1] + margin]
    if len(xs) * len(ys) > 40000:
        raise input_error("ANALYSIS_BUDGET", "Room grid exceeds 40000 cells")
    empty = {
        (i, j)
        for i in range(len(xs) - 1)
        for j in range(len(ys) - 1)
        if not any(
            b[0] < (xs[i] + xs[i + 1]) / 2 < b[2] and b[1] < (ys[j] + ys[j + 1]) / 2 < b[3] for b in boxes
        )
    }
    rooms = []
    while empty:
        first = min(empty)
        empty.remove(first)
        pending, cells = deque([first]), []
        exterior = False
        while pending:
            i, j = pending.popleft()
            cells.append((i, j))
            exterior |= i in (0, len(xs) - 2) or j in (0, len(ys) - 2)
            for neighbor in [(i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)]:
                if neighbor in empty:
                    empty.remove(neighbor)
                    pending.append(neighbor)
        if exterior:
            continue
        area = sum((xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]) for i, j in cells)
        edges = set()
        for i, j in cells:
            pts = [(xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                if (b, a) in edges:
                    edges.remove((b, a))
                else:
                    edges.add((a, b))
        successors = dict(edges)
        start = min(successors)
        loop, p = [], start
        while p not in loop:
            loop.append(p)
            p = successors[p]
        if p != start or len(loop) != len(edges):
            raise input_error("ROOM_WITH_ISLAND", "Rooms with internal islands require a multi-loop reader")
        rooms.append({"loop": [list(p) for p in loop], "area": area, "confidence": 1.0})
    return sorted(rooms, key=lambda r: _bounds(r["loop"]))


def draw(ctx, spec):
    if ctx.layout.name != "Model":
        raise input_error("UNSUPPORTED_LAYOUT", "Engineering plan generation requires model space")
    if ctx.unit != "mm":
        raise input_error("UNSUPPORTED_UNITS", "Architectural plans currently use millimetres")
    if set(spec) - {"sheet", "lang", "poche", "walls", "openings", "stairs", "rooms", "chains", "schedules"}:
        raise input_error("INVALID_SPEC", "Unknown architectural spec field")
    start = len(ctx.added)
    drawing_conventions(ctx.doc)
    poche = spec.get("poche", True)
    if not isinstance(poche, bool) or spec.get("lang", "en") != "en":
        raise input_error(
            "INVALID_SPEC", "poche must be boolean; architectural schedules currently use English"
        )
    scale = number(spec.get("sheet", {}).get("scale", 50), "sheet.scale", True)
    operations(ctx, [{"op": "set_annotation_scale", "scale": scale}])
    for layer in [
        WALL,
        SEAL,
        "ARCH_POCHE",
        "ARCH_OPENING",
        "ARCH_ROOM",
        "ARCH_STAIR",
        "ARCH_DIM",
        "ARCH_SCHEDULE",
    ]:
        if layer not in ctx.doc.layers:
            ctx.doc.layers.add(layer)
    ctx.doc.layers.get(SEAL).dxf.plot = 0
    ctx.doc.layers.get(SEAL).off()
    segments = _wall_segments(spec.get("walls", []))
    if not segments or len(segments) > 200:
        raise input_error("INVALID_SPEC", "Plan needs 1..200 wall segments")
    openings = defaultdict(list)
    ids = set()
    for o in spec.get("openings", []):
        if not o.get("id") or o["id"] in ids or o.get("kind") not in {"door", "window"}:
            raise input_error("INVALID_OPENING", "Openings need unique ids and kind door or window")
        ids.add(o["id"])
        offset, width = (
            number(o.get("offset"), "opening.offset"),
            number(o.get("width"), "opening.width", True),
        )
        candidates = [
            s
            for s in segments
            if s["id"] == o.get("wall")
            and s["offset"] <= offset
            and offset + width <= s["offset"] + s["length"]
        ]
        if len(candidates) != 1:
            raise input_error("INVALID_OPENING", f"{o['id']} is not hosted entirely on one wall segment")
        seg = candidates[0]
        lo, hi = offset - seg["offset"], offset - seg["offset"] + width
        key = (seg["id"], seg["index"])
        if any(lo < b and hi > a for a, b, _ in openings[key]):
            raise input_error("OPENING_OVERLAP", "Hosted openings overlap")
        openings[key].append((lo, hi, o))
    for seg in segments:
        half = seg["thickness"] / 2
        cuts = sorted(openings[(seg["id"], seg["index"])])
        cursor = -half
        spans = []
        for lo, hi, o in cuts:
            spans.append((cursor, lo))
            cursor = hi
            name = "ACARCH_" + uuid.uuid4().hex[:12]
            block = ctx.doc.blocks.new(name)
            width = hi - lo
            _rect(block, [0, -half, width, half], SEAL)
            if o["kind"] == "door":
                right = o.get("hand") == "right"
                hinge = width if right else 0
                block.add_line((hinge, 0), (hinge, width), dxfattribs={"layer": "ARCH_OPENING"})
                block.add_arc(
                    (hinge, 0),
                    width,
                    90 if right else 0,
                    180 if right else 90,
                    dxfattribs={"layer": "ARCH_OPENING"},
                )
            else:
                for y in [-half, 0, half]:
                    block.add_line((0, y), (width, y), dxfattribs={"layer": "ARCH_OPENING"})
            # A domain-specific attribute avoids treating door marks as ISA
            # equipment TAGs in readers that discover foreign P&ID blocks.
            exterior = any(w["id"] == seg["id"] and w.get("closed") for w in spec["walls"])
            label_side = -1 if exterior else 1
            block.add_attdef("OPENING_MARK", (width / 2, label_side * (half + 3 * scale)), height=2.5 * scale)
            ref = ctx.layout.add_blockref(
                name,
                _world(seg, lo, 0),
                dxfattribs={
                    "layer": "ARCH_OPENING",
                    "rotation": math.degrees(math.atan2(seg["direction"][1], seg["direction"][0])),
                },
            )
            ref.add_auto_attribs({"OPENING_MARK": o.get("tag", o["id"])})
            for attr in ref.attribs:
                attr.dxf.rotation = 0
            ctx.created(ref)
            put(
                ctx.doc,
                ref,
                "arch",
                {
                    "role": "opening",
                    "id": o["id"],
                    "kind": o["kind"],
                    "wall": seg["id"],
                    "nominal_width": width,
                    "height": o.get("height"),
                    "sill": o.get("sill"),
                },
            )
        spans.append((cursor, seg["length"] + half))
        for lo, hi in spans:
            if hi <= lo:
                continue
            box = _bounds([_world(seg, s, t) for s in (lo, hi) for t in (-half, half)])
            e = _rect(ctx.layout, box, WALL)
            ctx.created(e)
            put(ctx.doc, e, "arch", {"role": "wall", "id": seg["id"], "material": seg["material"]})
            if poche:
                hatch = ctx.layout.add_hatch(color=8, dxfattribs={"layer": "ARCH_POCHE"})
                hatch.paths.add_polyline_path(list(e.get_points("xy")), is_closed=True)
                ctx.created(hatch)
    for stair in spec.get("stairs", []):
        at = point(stair.get("start"), "stair.start")
        width, going = (
            number(stair.get("width"), "stair.width", True),
            number(stair.get("going"), "stair.going", True),
        )
        risers = stair.get("risers")
        if type(risers) is not int or not 2 <= risers <= 100:
            raise input_error("INVALID_STAIR", "Stair risers must be an integer in 2..100")
        number(stair.get("riser_height"), "stair.riser_height", True)
        angle = math.radians(number(stair.get("direction_deg", 0), "stair.direction_deg"))
        matrix = Matrix44.chain(Matrix44.z_rotate(angle), Matrix44.translate(*at, 0))
        e = _rect(ctx.layout, [0, 0, (risers - 1) * going, width], "ARCH_STAIR")
        e.transform(matrix)
        ctx.created(e)
        put(
            ctx.doc,
            e,
            "arch",
            {"role": "stair", "id": stair["id"], "risers": risers, "riser_height": stair["riser_height"]},
        )
        for i in range(1, risers - 1):
            e = ctx.layout.add_line((i * going, 0), (i * going, width), dxfattribs={"layer": "ARCH_STAIR"})
            e.transform(matrix)
            ctx.created(e)
    faces = detect_rooms(ctx.doc)
    for room in spec.get("rooms", []):
        at = point(room.get("at"), "room.at")
        candidates = [f for f in faces if G.point_in_polygon(at, f["loop"])]
        if len(candidates) != 1:
            raise input_error("ROOM_NOT_ENCLOSED", f"Room {room.get('id')} needs one enclosed wall face")
        area = candidates[0]["area"]
        if "area" in room and abs(number(room["area"], "room.area") - area) > area * 0.001:
            raise input_error("ROOM_AREA_MISMATCH", "Stated room area disagrees with wall geometry")
        e = ctx.layout.add_text(
            f"{room['number']} {room['name']} {area / 1e6:.2f} m2",
            height=3 * scale,
            dxfattribs={"insert": at, "layer": "ARCH_ROOM"},
        )
        from ezdxf.enums import TextEntityAlignment

        e.set_placement(at, align=TextEntityAlignment.MIDDLE_CENTER)
        ctx.created(e)
        put(
            ctx.doc,
            e,
            "arch",
            {
                "role": "room",
                "id": room["id"],
                "number": str(room["number"]),
                "name": room["name"],
                "area": area,
            },
        )
    if spec.get("chains"):
        # Dimension the actual exterior faces and opening jambs. Each extension
        # origin is a saved wall vertex, so the chain remains geometrically
        # verifiable instead of referring to invisible construction axes.
        points = [
            tuple(p)
            for e in ctx.doc.modelspace().query(f'LWPOLYLINE[layer=="{WALL}"]')
            for p in e.get_points("xy")
        ]
        x0, y0, x1, y1 = _bounds(points)
        ops = []
        for side in spec["chains"].get("sides", []):
            if side in {"bottom", "top"}:
                y = y0 if side == "bottom" else y1
                anchors = [[x, y] for x in sorted({p[0] for p in points if abs(p[1] - y) < 1e-6})]
                direction = [0, -1 if side == "bottom" else 1]
                orientation = "horizontal"
            elif side in {"left", "right"}:
                x = x0 if side == "left" else x1
                anchors = [[x, y] for y in sorted({p[1] for p in points if abs(p[0] - x) < 1e-6})]
                direction = [-1 if side == "left" else 1, 0]
                orientation = "vertical"
            else:
                raise input_error("INVALID_SIDE", side)
            pairs = [(a, b, 10) for a, b in zip(anchors, anchors[1:])]
            if len(anchors) > 2:
                pairs.append((anchors[0], anchors[-1], 18))
            for a, b, offset in pairs:
                ops.append(
                    {
                        "op": "add_linear_dim",
                        "p1": a,
                        "p2": b,
                        "base": [a[i] + direction[i] * offset * scale for i in range(2)],
                        "orientation": orientation,
                        "layer": "ARCH_DIM",
                    }
                )
        operations(ctx, ops)
    plan = read(ctx.doc)
    for schedule in spec.get("schedules", []):
        kind = schedule["kind"]
        rows = plan["schedules"].get(kind)
        if rows is None:
            raise input_error("INVALID_SCHEDULE", kind)
        table = (
            [["ROOM", "AREA m2"]] + [[r["number"], f"{r['area'] / 1e6:.2f}"] for r in rows]
            if kind == "rooms"
            else [["TAG", "WIDTH"]] + [[r["tag"], f"{r['width']:g}"] for r in rows]
        )
        operations(
            ctx,
            [
                {
                    "op": "add_table",
                    "insert": schedule["at"],
                    "rows": table,
                    "col_widths": [25 * scale, 30 * scale],
                    "row_height": 7 * scale,
                    "text_height": 2.5 * scale,
                    "layer": "ARCH_SCHEDULE",
                }
            ],
        )
    return {"created": ctx.added[start:], "rooms": len(faces), "omitted": []}


def read(doc):
    faces = detect_rooms(doc)
    rooms, openings, stairs, issues = [], [], [], []
    for e in doc.modelspace():
        record = get(e, "arch")
        if not record:
            continue
        role = record.get("role")
        if role == "room" and e.dxftype() == "TEXT":
            matches = [f for f in faces if G.point_in_polygon(tuple(e.dxf.insert)[:2], f["loop"])]
            area = matches[0]["area"] if len(matches) == 1 else None
            row = {**record, "handle": e.dxf.handle, "detected_area": area}
            rooms.append(row)
            if area is None or abs(area - record["area"]) > max(1e-6, record["area"] * 0.001):
                issues.append({"code": "ROOM_AREA_MISMATCH", "handle": e.dxf.handle})
        elif role == "opening" and e.dxftype() == "INSERT":
            seals = [p for p in e.virtual_entities() if p.dxftype() == "LWPOLYLINE" and p.dxf.layer == SEAL]
            width = max(
                (
                    math.dist(a, b)
                    for p in seals
                    for a, b in zip(list(p.get_points("xy")), list(p.get_points("xy"))[1:])
                ),
                default=0,
            )
            tag = e.get_attrib_text("OPENING_MARK")
            openings.append({**record, "tag": tag, "width": width, "handle": e.dxf.handle})
            if abs(width - record["nominal_width"]) > 1e-6:
                issues.append({"code": "OPENING_WIDTH_MISMATCH", "handle": e.dxf.handle})
        elif role == "stair":
            stairs.append({**record, "handle": e.dxf.handle})
    if len(faces) != len(rooms):
        issues.append({"code": "ROOM_LABEL_COVERAGE", "faces": len(faces), "labels": len(rooms)})
    tags = [o["tag"] for o in openings]
    if len(set(tags)) != len(tags):
        issues.append({"code": "DUPLICATE_OPENING_TAG"})
    return {
        "rooms": rooms,
        "detected_rooms": faces,
        "openings": openings,
        "stairs": stairs,
        "critique": issues,
        "schedules": {
            "rooms": rooms,
            "doors": [r for r in openings if r["kind"] == "door"],
            "windows": [r for r in openings if r["kind"] == "window"],
        },
    }
