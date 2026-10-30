"""Revolved-part drawing views, ISO-size sheets, drawing-derived BOM and linked balloons."""

from __future__ import annotations

from collections import defaultdict
import math
import uuid

from ezdxf import bbox

from ..errors import input_error
from ..model import get_tag
from .records import drawing_conventions, get, number, operations, point, put


def _sheet(ctx, spec):
    if spec.get("size", "A3") != "A3":
        raise input_error("UNSUPPORTED_SHEET", "Mechanical assembly sheets currently use A3 landscape")
    result = operations(
        ctx, [{"op": "add_rectangle", "corner": [20, 10], "width": 390, "height": 277, "layer": "BORDER"}]
    )[0]
    put(
        ctx.doc,
        ctx.doc.entitydb[result["created"][0]],
        "mech",
        {"role": "frame", "standard": "ISO 5457", "paper": [420, 297]},
    )
    ops = []
    for i, label in enumerate("ABCDEFGH"):
        x = 20 + (i + 0.5) * 390 / 8
        for y in (5, 290):
            ops.append({"op": "add_text", "text": label, "insert": [x, y], "height": 2.5, "layer": "BORDER"})
    for i in range(6):
        y = 10 + (i + 0.5) * 277 / 6
        for x in (15, 413):
            ops.append(
                {"op": "add_text", "text": str(i + 1), "insert": [x, y], "height": 2.5, "layer": "BORDER"}
            )
    for x in (20, 410):
        ops.append({"op": "add_line", "start": [x - 5, 148.5], "end": [x + 5, 148.5], "layer": "BORDER"})
    for y in (10, 287):
        ops.append({"op": "add_line", "start": [210, y - 5], "end": [210, y + 5], "layer": "BORDER"})
    operations(ctx, ops)
    name = "ACMECH_TITLE_" + uuid.uuid4().hex[:10]
    block = ctx.doc.blocks.new(name)
    block.add_lwpolyline([(0, 0), (180, 0), (180, 60), (0, 60)], close=True)
    for y in (15, 30, 45):
        block.add_line((0, y), (180, y))
    for x in (60, 120):
        block.add_line((x, 0), (x, 45))
    fields = {
        "TITLE": (3, 50, spec.get("title", "Assembly")),
        "DRAWING_NO": (3, 34, spec.get("drawing_no", "")),
        "MATERIAL": (63, 34, spec.get("material", "")),
        "SCALE": (123, 34, spec.get("scale", "1:1")),
        "DRAWN_BY": (3, 19, spec.get("drawn_by", "")),
        "REVISION": (63, 19, spec.get("revision", "A")),
        "SHEET": (123, 19, "1/1"),
        "UNITS": (3, 4, "mm"),
        "PROJECTION": (63, 4, "FIRST ANGLE"),
    }
    for key, (x, y, value) in fields.items():
        block.add_text(key.replace("_", " "), height=1.8, dxfattribs={"insert": (x, y + 7)})
        block.add_attdef(key, (x, y), height=3.5 if key == "TITLE" else 2.5)
    ref = ctx.layout.add_blockref(name, (230, 10), dxfattribs={"layer": "BORDER"})
    ref.add_auto_attribs({key: str(value[2]) for key, value in fields.items()})
    ctx.created(ref)
    put(ctx.doc, ref, "mech", {"role": "titleblock", "standard": "ISO 7200", "projection": "first"})


def _part(ctx, spec):
    if spec.get("kind", "revolved") != "revolved":
        raise input_error("UNSUPPORTED_PART", "Mechanical drawing views currently support revolved profiles")
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise input_error("MISSING_PARAM", "Part name is required")
    at = point(spec.get("at"), "part.at")
    segments = []
    for s in spec.get("segments", []):
        length = number(s.get("length"), "segment.length", True)
        outer = number(s.get("d_outer"), "segment.d_outer", True)
        inner = number(s.get("d_inner", 0), "segment.d_inner")
        if not 0 <= inner < outer:
            raise input_error("INVALID_PROFILE", "Bore must be nonnegative and smaller than outer diameter")
        segments.append((length, outer / 2, inner / 2))
    if not segments or len(segments) > 50:
        raise input_error("INVALID_PROFILE", "Part needs 1..50 profile segments")
    length = sum(s[0] for s in segments)
    radius = max(s[1] for s in segments)
    top, bottom, inner_top, inner_bottom = [], [], [], []
    x = 0
    for step, outer, inner in segments:
        top.extend([(x, outer), (x + step, outer)])
        bottom.extend([(x, -outer), (x + step, -outer)])
        inner_top.extend([(x, inner), (x + step, inner)])
        inner_bottom.extend([(x, -inner), (x + step, -inner)])
        x += step
    views = spec.get("views", ["front"])
    if "front" not in views or set(views) - {"front", "side", "section"}:
        raise input_error("INVALID_VIEW", "Use front plus optional side and section views")
    if "section" in views and any(s[2] <= 0 for s in segments):
        raise input_error("UNSUPPORTED_SECTION", "Longitudinal section currently requires a through bore")

    def place(points, origin):
        out = []
        for x, y in points:
            p = [origin[0] + x, origin[1] + y]
            if not out or p != out[-1]:
                out.append(p)
        return out

    front = place(top + list(reversed(bottom)), at)
    body = operations(
        ctx,
        [{"op": "add_polyline", "points": front, "closed": True, "layer": "OUTLINE", "tag": "part." + name}],
    )[0]["created"][0]
    nominal = {"length": length, "diameter": 2 * radius}
    put(
        ctx.doc,
        ctx.doc.entitydb[body],
        "mech",
        {
            "role": "part",
            "name": name,
            "material": spec.get("material", ""),
            "nominal": nominal,
            "profile": front,
            "views": views,
        },
    )
    operations(
        ctx,
        [
            {
                "op": "add_line",
                "start": [at[0] - 5, at[1]],
                "end": [at[0] + length + 5, at[1]],
                "layer": "CENTER",
                "linetype": "CENTER",
            }
        ],
    )
    for inner in (inner_top, inner_bottom):
        if any(s[2] for s in segments):
            operations(
                ctx,
                [{"op": "add_polyline", "points": place(inner, at), "layer": "HIDDEN", "linetype": "HIDDEN"}],
            )
    if "section" in views:
        origin = [at[0] - length - 15, at[1]]
        for outer, inner in [(top, inner_top), (bottom, inner_bottom)]:
            loop = place(outer + list(reversed(inner)), origin)
            result = operations(
                ctx,
                [
                    {"op": "add_polyline", "points": loop, "closed": True, "layer": "OUTLINE"},
                    {
                        "op": "add_hatch",
                        "points": loop,
                        "pattern": "ANSI31",
                        "pattern_scale": 1,
                        "layer": "SECTION",
                    },
                ],
            )
            put(
                ctx.doc,
                ctx.doc.entitydb[result[0]["created"][0]],
                "mech",
                {"role": "section", "part": name, "style": "full"},
            )
        operations(
            ctx,
            [
                {
                    "op": "add_line",
                    "start": [origin[0] - 5, origin[1]],
                    "end": [origin[0] + length + 5, origin[1]],
                    "layer": "CENTER",
                    "linetype": "CENTER",
                },
                {
                    "op": "add_text",
                    "text": "A-A",
                    "insert": [origin[0] + length / 2, origin[1] - radius - 8],
                    "height": 3.5,
                    "layer": "TEXT",
                },
            ],
        )
    if "side" in views:
        center = [at[0] - radius - 20, at[1]]
        radii = sorted({s[1] for s in segments} | {s[2] for s in segments if s[2] > 0}, reverse=True)
        circles = []
        for r in radii:
            h = operations(ctx, [{"op": "add_circle", "center": center, "radius": r, "layer": "OUTLINE"}])[0][
                "created"
            ][0]
            circles.append(h)
            put(
                ctx.doc, ctx.doc.entitydb[h], "mech", {"role": "view_circle", "part": name, "kind": "profile"}
            )
        for feature in spec.get("features", []):
            if feature.get("kind") != "hole_circle":
                raise input_error("UNSUPPORTED_FEATURE", "End views support hole_circle features")
            count = feature.get("count")
            pcd = number(feature.get("pcd"), "hole_circle.pcd", True)
            diameter = number(feature.get("diameter"), "hole_circle.diameter", True)
            if type(count) is not int or not 1 <= count <= 100 or pcd / 2 + diameter / 2 > radius:
                raise input_error(
                    "INVALID_HOLE_PATTERN", "Hole circle must fit the part and have 1..100 holes"
                )
            for i in range(count):
                angle = math.radians(number(feature.get("start_angle", 0), "start_angle") + i * 360 / count)
                c = [center[0] + pcd / 2 * math.cos(angle), center[1] + pcd / 2 * math.sin(angle)]
                h = operations(
                    ctx, [{"op": "add_circle", "center": c, "diameter": diameter, "layer": "HOLES"}]
                )[0]["created"][0]
                circles.append(h)
                put(
                    ctx.doc,
                    ctx.doc.entitydb[h],
                    "mech",
                    {
                        "role": "view_circle",
                        "part": name,
                        "kind": "bolt_hole",
                        "pcd": pcd,
                        "diameter": diameter,
                    },
                )
        # One centre cross per physical circle, as required by the view engine.
        for h in circles:
            operations(ctx, [{"op": "add_center_mark", "target": h, "extension": 3, "layer": "CENTER"}])
    if spec.get("dimension", True):
        cursor = 0
        for step, outer, _ in segments:
            operations(
                ctx,
                [
                    {
                        "op": "add_linear_dim",
                        "p1": [at[0] + cursor, at[1] + outer],
                        "p2": [at[0] + cursor + step, at[1] + outer],
                        "base": [at[0], at[1] + radius + 10],
                        "layer": "DIM",
                    }
                ],
            )
            cursor += step
    return body


def bom(doc):
    groups = defaultdict(list)
    for e in doc.modelspace():
        r = get(e, "mech")
        if r and r.get("role") == "part":
            groups[(r["name"], r.get("material", ""), "")].append(e.dxf.handle)
        elif e.dxftype() == "INSERT" and e.has_attrib("PART") and e.get_attrib_text("PART"):
            groups[
                (e.get_attrib_text("PART"), e.get_attrib_text("STANDARD"), e.get_attrib_text("SIZE"))
            ].append(e.dxf.handle)
    return [
        {
            "item": i,
            "description": key[0],
            "standard": key[1],
            "size": key[2],
            "quantity": len(handles),
            "handles": sorted(handles),
        }
        for i, (key, handles) in enumerate(sorted(groups.items()), 1)
    ]


def draw(ctx, spec):
    if ctx.layout.name != "Model":
        raise input_error("UNSUPPORTED_LAYOUT", "Engineering assembly generation requires model space")
    if ctx.unit != "mm" or set(spec) - {"sheet", "parts", "fasteners", "bom"}:
        raise input_error(
            "INVALID_SPEC", "Mechanical assembly needs millimetres and sheet/parts/fasteners/bom"
        )
    if len(spec.get("parts", [])) + len(spec.get("fasteners", [])) > 100:
        raise input_error("BUDGET_EXCEEDED", "Assembly is limited to 100 parts")
    start = len(ctx.added)
    drawing_conventions(ctx.doc)
    _sheet(ctx, spec.get("sheet", {}))
    names = set()
    for part in spec.get("parts", []):
        if part.get("name") in names:
            raise input_error("DUPLICATE_ID", "Use unique part names in a drawing")
        names.add(part.get("name"))
        _part(ctx, part)
    for item in spec.get("fasteners", []):
        operations(ctx, [{"op": "add_standard_part", **item}])
    rows = bom(ctx.doc)
    if not rows:
        raise input_error("EMPTY_ASSEMBLY", "Assembly has no parts to list")
    at = spec.get("bom", {}).get("at", [230, 112])
    table = [["ITEM", "DESCRIPTION", "STANDARD / SIZE", "QTY"]] + [
        [str(r["item"]), r["description"], r["standard"] + " " + r["size"], str(r["quantity"])] for r in rows
    ]
    result = operations(
        ctx,
        [
            {
                "op": "add_table",
                "insert": at,
                "rows": table,
                "col_widths": [15, 50, 100, 15],
                "row_height": 7,
                "text_height": 2.5,
                "tag": "assembly.bom",
                "layer": "BOM",
            }
        ],
    )[0]
    put(ctx.doc, ctx.doc.entitydb[result["created"][0]], "mech", {"role": "bom", "tag": "assembly.bom"})
    for row in rows:
        target = ctx.doc.entitydb[row["handles"][0]]
        ext = bbox.extents([target], fast=True)
        tip = [ext.extmin.x, ext.extmax.y]
        # Parts are called out above their view; standard fasteners above their installation point.
        at = [tip[0], 110 if target.dxftype() == "INSERT" and target.has_attrib("PART") else tip[1] + 45]
        h = operations(ctx, [{"op": "add_circle", "center": at, "radius": 4, "layer": "BALLOON"}])[0][
            "created"
        ][0]
        text = ctx.layout.add_text(str(row["item"]), height=2.5, dxfattribs=ctx.attribs({"layer": "BALLOON"}))
        from ezdxf.enums import TextEntityAlignment

        text.set_placement(at, align=TextEntityAlignment.MIDDLE_CENTER)
        ctx.created(text)
        leader = ctx.layout.add_leader(
            [tip, [at[0], at[1] - 4]], dimstyle="Standard", dxfattribs=ctx.attribs({"layer": "BALLOON"})
        )
        ctx.created(leader)
        put(
            ctx.doc,
            ctx.doc.entitydb[h],
            "mech",
            {
                "role": "balloon",
                "item": row["item"],
                "targets": row["handles"],
                "leader": leader.dxf.handle,
                "text": text.dxf.handle,
            },
        )
    return {"created": ctx.added[start:], "parts": len(names), "bom": rows}


def read(doc):
    rows = bom(doc)
    parts, balloons, circles, sections, issues = [], [], [], [], []
    frames, titles, tables = [], [], []
    for e in doc.modelspace():
        record = get(e, "mech")
        if not record:
            continue
        role = record.get("role")
        if role == "part":
            if e.dxftype() != "LWPOLYLINE" or not e.closed:
                issues.append({"code": "INVALID_PART_PROFILE", "handle": e.dxf.handle})
                continue
            points = list(e.get_points("xy"))
            ext = bbox.extents([e], fast=True)
            measured = {"length": ext.size.x, "diameter": ext.size.y}
            parts.append(
                {
                    "handle": e.dxf.handle,
                    "name": record["name"],
                    "measured": measured,
                    "views": record["views"],
                }
            )
            if len(points) != len(record["profile"]) or any(
                math.dist(a, b) > 1e-6 for a, b in zip(points, record["profile"])
            ):
                issues.append({"code": "PART_PROFILE_CHANGED", "handle": e.dxf.handle})
        elif role == "balloon":
            balloons.append({**record, "handle": e.dxf.handle})
        elif role == "view_circle":
            circles.append(
                {
                    **record,
                    "handle": e.dxf.handle,
                    "center": list(e.dxf.center)[:2],
                    "diameter": e.dxf.radius * 2,
                }
            )
            center = tuple(e.dxf.center)[:2]
            lines = [
                line
                for line in doc.modelspace().query('LINE[layer=="CENTER"]')
                if G_distance(center, line) <= 1e-6
            ]
            if len(lines) < 2:
                issues.append({"code": "MISSING_CENTER_MARK", "handle": e.dxf.handle})
        elif role == "section":
            sections.append({**record, "handle": e.dxf.handle})
        elif role == "frame":
            frames.append(e.dxf.handle)
        elif role == "titleblock":
            titles.append(e.dxf.handle)
        elif role == "bom":
            tables.append(e.dxf.handle)
    if len(frames) != 1 or len(titles) != 1 or len(tables) != 1:
        issues.append(
            {"code": "SHEET_STRUCTURE", "frames": len(frames), "titles": len(titles), "tables": len(tables)}
        )
    cells = defaultdict(list)
    for e in doc.modelspace().query("TEXT"):
        tag = get_tag(e)
        if tag and tag.startswith("assembly.bom.r"):
            cells[tag].append(e.dxf.text)
    expected_cells = {
        f"assembly.bom.r0c{i}": [text]
        for i, text in enumerate(["ITEM", "DESCRIPTION", "STANDARD / SIZE", "QTY"])
    }
    for row in rows:
        want = [
            str(row["item"]),
            row["description"],
            row["standard"] + " " + row["size"],
            str(row["quantity"]),
        ]
        expected_cells.update({f"assembly.bom.r{row['item']}c{c}": [value] for c, value in enumerate(want)})
        linked = [b for b in balloons if b["item"] == row["item"]]
        if len(linked) != 1 or set(linked[0]["targets"]) != set(row["handles"]):
            issues.append({"code": "BALLOON_LINK_MISMATCH", "item": row["item"]})
    if dict(cells) != expected_cells:
        issues.append(
            {"code": "BOM_MISMATCH", "expected_cells": len(expected_cells), "actual_cells": len(cells)}
        )
    if not rows:
        issues.append({"code": "EMPTY_ASSEMBLY"})
    items = {row["item"] for row in rows}
    for balloon in balloons:
        if balloon["item"] not in items or any(doc.entitydb.get(h) is None for h in balloon["targets"]):
            issues.append({"code": "BALLOON_LINK_MISMATCH", "item": balloon["item"]})
        text, leader = doc.entitydb.get(balloon["text"]), doc.entitydb.get(balloon["leader"])
        if (
            text is None
            or text.dxftype() != "TEXT"
            or text.dxf.text != str(balloon["item"])
            or leader is None
        ):
            issues.append({"code": "BALLOON_ANNOTATION_MISSING", "handle": balloon["handle"]})
    return {
        "parts": parts,
        "bom": rows,
        "balloons": balloons,
        "circles": circles,
        "sections": sections,
        "critique": issues,
    }


def G_distance(center, line):
    from ..geom import dist_to_segment

    return dist_to_segment(center, tuple(line.dxf.start)[:2], tuple(line.dxf.end)[:2])
