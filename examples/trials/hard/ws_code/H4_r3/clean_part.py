"""Clean this installation-plate DXF and verify a round trip before replacement."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import ezdxf
from ezdxf.entities import DXFGraphic
from ezdxf.lldxf.tagwriter import TagCollector


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "part.dxf"
BACKUP = ROOT / "part.original.dxf"
CANDIDATE = ROOT / "part.cleaned.dxf"
REPORT = ROOT / "cleanup_report.json"
STANDARDS = {
    "OUTLINE": (7, "Continuous", 50),
    "CENTER": (1, "CENTER", 25),
    "DIM": (3, "Continuous", 25),
    "TEXT": (4, "Continuous", 25),
}
DISPLAY_CODES = {6, 8, 62, 370, 420, 430}


def content_tags(entity, identity=True):
    """Include all geometry, text, dimension data and non-display DXF tags."""
    ignored = DISPLAY_CODES if identity else DISPLAY_CODES | {5, 330}
    return [(t.code, t.value) for t in TagCollector.dxftags(entity)
            if t.code not in ignored]


def signature(entity, identity=True):
    return json.dumps(content_tags(entity, identity), ensure_ascii=False, default=str)


def entities(doc):
    return [e for block in doc.blocks for e in block]


def line_key(start, end):
    # Exact endpoints, without tolerances or rounding that could merge near lines.
    return tuple(sorted((tuple(start), tuple(end))))


def polyline_edges(entity):
    if entity.dxftype() != "LWPOLYLINE":
        return set()
    points = list(entity.get_points("xyseb"))
    wcs = list(entity.vertices_in_wcs())
    result = set()
    count = len(points) if entity.closed else len(points) - 1
    for i in range(count):
        # Width and bulge must be zero to coincide with an ordinary LINE.
        if points[i][2:] == (0.0, 0.0, 0.0) and entity.dxf.const_width == 0:
            result.add(line_key(wcs[i], wcs[(i + 1) % len(points)]))
    return result


def set_bylayer(entity, layer):
    entity.dxf.layer = layer
    entity.dxf.color = 256
    entity.dxf.linetype = "BYLAYER"
    entity.dxf.lineweight = -1
    entity.dxf.discard("true_color")
    entity.dxf.discard("color_name")


def main():
    doc = ezdxf.readfile(SOURCE)
    assert doc.units == 4, "Expected millimetres."
    audit = doc.audit()
    assert not audit.errors and not audit.fixes, "Input needs repair before cleanup."
    if not BACKUP.exists():
        shutil.copy2(SOURCE, BACKUP)

    before = {e.dxf.handle: signature(e) for e in entities(doc)}
    measurements_before = {e.dxf.handle: e.get_measurement()
                           for e in doc.modelspace().query("DIMENSION")}
    style_before = {s.dxf.name: s.dxf.all_existing_dxf_attribs().copy()
                    for s in doc.dimstyles}
    deleted = []
    for block in doc.blocks:
        edges = set().union(*(polyline_edges(e) for e in block)) if len(block) else set()
        seen = {}
        for e in list(block):
            reason = None
            same_as = None
            if e.dxftype() == "LINE":
                if tuple(e.dxf.start) == tuple(e.dxf.end):
                    reason = "zero_length_line"
                elif line_key(e.dxf.start, e.dxf.end) in edges:
                    reason = "line_coincides_with_polyline_edge"
            key = signature(e, identity=False)
            if e.dxftype() == "LINE":
                key = ("LINE", line_key(e.dxf.start, e.dxf.end), e.dxf.extrusion, e.dxf.thickness)
            if reason is None and key in seen:
                reason, same_as = "exact_duplicate", seen[key]
            if reason:
                deleted.append({"handle": e.dxf.handle, "type": e.dxftype(),
                                "block": block.name, "reason": reason,
                                "same_as": same_as,
                                "original_attributes": e.dxf.all_existing_dxf_attribs()})
                block.delete_entity(e)
            else:
                seen[key] = e.dxf.handle

    for name, (color, linetype, weight) in STANDARDS.items():
        assert linetype in doc.linetypes
        layer = doc.layers.get(name) if name in doc.layers else doc.layers.new(name)
        layer.dxf.color, layer.dxf.linetype, layer.dxf.lineweight = color, linetype, weight
        layer.dxf.discard("true_color")

    expected_layers = {}
    dimension_blocks = {e.dxf.geometry for e in doc.modelspace().query("DIMENSION")}
    arrow_blocks = {e.dxf.name for name in dimension_blocks
                    for e in doc.blocks.get(name).query("INSERT")}
    arrow_blocks.update({"_ARCHTICK", "_CLOSEDBLANK"})
    for block in doc.blocks:
        for e in block:
            if e.dxf.layer.casefold() == "defpoints":
                layer = "Defpoints"  # Non-plotting dimension definition points.
            elif block.name in dimension_blocks | arrow_blocks:
                layer = "DIM"
            elif e.dxftype() == "DIMENSION":
                layer = "DIM"
            elif e.dxftype() in {"TEXT", "MTEXT"}:
                layer = "TEXT"
            elif e.dxftype() == "LINE" and e.dxf.color == 1:
                layer = "CENTER"
            elif e.dxftype() in {"LWPOLYLINE", "CIRCLE"}:
                layer = "OUTLINE"
            elif e.dxftype() == "LINE" and e.dxf.layer == "CENTER":
                layer = "CENTER"
            else:
                raise ValueError(f"Unclassified entity: {e.dxftype()} #{e.dxf.handle}")
            set_bylayer(e, layer)
            expected_layers[e.dxf.handle] = layer
            if e.dxftype() == "INSERT" and e.seqend is not None:
                set_bylayer(e.seqend, layer)

    # Keep future dimension regeneration consistent with the normalized blocks.
    style_changes = {"dimclrd": 256, "dimclre": 256, "dimclrt": 256,
                     "dimlwd": -1, "dimlwe": -1,
                     "dimltype": "BYLAYER", "dimltex1": "BYLAYER", "dimltex2": "BYLAYER"}
    for name in {e.dxf.dimstyle for e in doc.modelspace().query("DIMENSION")}:
        doc.dimstyles.get(name).update_dxf_attribs(style_changes)

    used_layers = {e.dxf.layer.casefold() for e in doc.entitydb.values()
                   if isinstance(e, DXFGraphic) and e.is_alive}
    deleted_layers = []
    for layer in list(doc.layers):
        name = layer.dxf.name
        if name.casefold() not in used_layers | {"0", "defpoints"}:
            deleted_layers.append(name)
            doc.layers.remove(name)

    removed_handles = {item["handle"] for item in deleted}

    def verify(path):
        loaded = ezdxf.readfile(path)
        after = {e.dxf.handle: signature(e) for e in entities(loaded)}
        assert after == {h: s for h, s in before.items() if h not in removed_handles}, \
            "Geometry, dimension data or text changed."
        assert loaded.units == 4
        assert set(l.dxf.name for l in loaded.layers) == set(STANDARDS) | {"0", "Defpoints"}
        for name, values in STANDARDS.items():
            layer = loaded.layers.get(name)
            assert (layer.dxf.color, layer.dxf.linetype, layer.dxf.lineweight) == values
        for e in loaded.entitydb.values():
            if not isinstance(e, DXFGraphic) or not e.is_alive:
                continue
            assert (e.dxf.color, e.dxf.linetype.upper(), e.dxf.lineweight) == (256, "BYLAYER", -1)
            assert not e.dxf.hasattr("true_color") and not e.dxf.hasattr("color_name")
            if e.dxf.handle in expected_layers:
                assert e.dxf.layer == expected_layers[e.dxf.handle]
        for block in loaded.blocks:
            seen = set()
            edges = set().union(*(polyline_edges(e) for e in block)) if len(block) else set()
            for e in block:
                key = signature(e, identity=False)
                if e.dxftype() == "LINE":
                    assert tuple(e.dxf.start) != tuple(e.dxf.end)
                    assert line_key(e.dxf.start, e.dxf.end) not in edges
                    key = ("LINE", line_key(e.dxf.start, e.dxf.end), e.dxf.extrusion, e.dxf.thickness)
                assert key not in seen
                seen.add(key)
        measurements = {e.dxf.handle: e.get_measurement()
                        for e in loaded.modelspace().query("DIMENSION")}
        assert measurements == measurements_before
        for name, attrs in style_before.items():
            now = loaded.dimstyles.get(name).dxf.all_existing_dxf_attribs()
            assert {k: v for k, v in attrs.items() if k not in style_changes} == \
                   {k: v for k, v in now.items() if k not in style_changes}
        audit = loaded.audit()
        assert not audit.errors and not audit.fixes
        outline = loaded.modelspace().query("LWPOLYLINE")[0]
        assert outline.closed and list(outline.get_points("xy")) == [(0, 0), (200, 0), (200, 100), (0, 100)]
        holes = sorted((tuple(e.dxf.center), e.dxf.radius * 2)
                       for e in loaded.modelspace().query("CIRCLE"))
        assert holes == [((20, 20, 0), 12), ((20, 80, 0), 12), ((100, 50, 0), 40),
                         ((180, 20, 0), 12), ((180, 80, 0), 12)]
        counts = dict(Counter(e.dxf.layer for e in loaded.modelspace()))
        assert counts == {"OUTLINE": 6, "CENTER": 10, "DIM": 4, "TEXT": 2}
        return {"units": "mm", "modelspace_count": len(loaded.modelspace()),
                "modelspace_by_layer": counts, "dimensions_mm": list(measurements.values()),
                "holes_center_and_diameter_mm": holes,
                "geometry_dimension_text_tags_unchanged": True,
                "all_graphic_entities_bylayer": True, "audit_errors": 0, "audit_fixes": 0}

    doc.saveas(CANDIDATE)
    checks = verify(CANDIDATE)
    CANDIDATE.replace(SOURCE)
    assert verify(SOURCE) == checks
    report = {"source": SOURCE.name, "backup": BACKUP.name,
              "deleted_entities": deleted, "deleted_layers": deleted_layers,
              "dimension_style_display_changes": style_changes, "verification": checks,
              "output_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest()}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
