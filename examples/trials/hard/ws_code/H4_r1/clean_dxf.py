"""Clean this supplier drawing and verify the saved DXF using ezdxf only."""
from collections import Counter
import json
import os
from pathlib import Path
import shutil

import ezdxf


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.original.dxf'
STAGED = ROOT / 'part.cleaned.dxf'
STANDARD = {
    'OUTLINE': (7, 'Continuous', 50),
    'CENTER': (1, 'CENTER', 25),
    'DIM': (3, 'Continuous', 25),
    'TEXT': (4, 'Continuous', 25),
}
APPEARANCE = {'layer', 'color', 'linetype', 'lineweight', 'true_color', 'color_name'}


def value(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return [value(x) for x in v]


def record(entity):
    result = {
        'type': entity.dxftype(),
        'attributes': {k: value(v) for k, v in entity.dxf.all_existing_dxf_attribs().items()
                       if k not in APPEARANCE},
    }
    if entity.dxftype() == 'LWPOLYLINE':
        result['vertices'] = value(entity.get_points())
    if entity.dxftype() == 'MTEXT':
        result['text'] = entity.text
    if entity.dxftype() == 'DIMENSION':
        result['overrides'] = entity.get_acad_dstyle({})
        result['measurement'] = entity.get_measurement()
    return result


def entities(doc):
    return [entity for block in doc.blocks for entity in block]


def segment(a, b):
    return tuple(sorted((tuple(a), tuple(b))))


def poly_edges(entity):
    points = list(entity.get_points())
    assert entity.dxf.get('const_width', 0) == 0
    assert entity.dxf.get('elevation', 0) == 0
    assert all(p[2] == p[3] == p[4] == 0 for p in points)
    pairs = list(zip(points, points[1:]))
    if entity.closed:
        pairs.append((points[-1], points[0]))
    return [segment((a[0], a[1], 0), (b[0], b[1], 0)) for a, b in pairs]


def geometry(doc):
    """Unique model-space geometric support, including polyline edge overlap."""
    result = set()
    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind == 'LINE':
            if entity.dxf.start != entity.dxf.end:
                result.add(('SEGMENT', segment(entity.dxf.start, entity.dxf.end)))
        elif kind == 'LWPOLYLINE':
            result.update(('SEGMENT', edge) for edge in poly_edges(entity))
        elif kind == 'CIRCLE':
            result.add(('CIRCLE', tuple(entity.dxf.center), entity.dxf.radius))
    return result


def model_layer(entity):
    kind = entity.dxftype()
    if kind in {'TEXT', 'MTEXT'}:
        return 'TEXT'
    if kind == 'DIMENSION':
        return 'DIM'
    if kind in {'CIRCLE', 'LWPOLYLINE'}:
        return 'OUTLINE'
    if kind == 'LINE':
        # The inspection established that the red crosshairs mark the five holes.
        return 'CENTER' if entity.dxf.color == 1 else 'OUTLINE'
    raise ValueError(f'Unclassified entity: {kind} {entity.dxf.handle}')


def by_layer(entity, layer):
    entity.dxf.layer = layer
    entity.dxf.color = 256
    entity.dxf.linetype = 'BYLAYER'
    entity.dxf.lineweight = -1
    entity.dxf.discard('true_color')
    entity.dxf.discard('color_name')


def main():
    doc = ezdxf.readfile(SOURCE)
    assert doc.units == 4, 'Expected millimetres'
    before = {e.dxf.handle: record(e) for e in entities(doc)}
    geometry_before = geometry(doc)
    original_count = len(doc.modelspace())
    deleted = []
    deleted_layers = []
    expected_layers = {}
    dimstyle_before = {
        s.dxf.name: dict(s.dxf.all_existing_dxf_attribs()) for s in doc.dimstyles
    }
    if BACKUP.exists():
        if BACKUP.read_bytes() != SOURCE.read_bytes():
            raise FileExistsError('Backup differs from source; refusing to overwrite original evidence')
    else:
        shutil.copy2(SOURCE, BACKUP)

    for name, (color, linetype, weight) in STANDARD.items():
        assert linetype in doc.linetypes
        layer = doc.layers.get(name) if name in doc.layers else doc.layers.new(name)
        layer.dxf.update({'color': color, 'linetype': linetype, 'lineweight': weight})

    # Deduplicate within each block/layout; never compare separate block instances.
    for block in doc.blocks:
        outline_edges = {}
        if block.name == '*Model_Space':
            for e in block.query('LWPOLYLINE'):
                for edge in poly_edges(e):
                    outline_edges[edge] = e.dxf.handle
        seen = {}
        for entity in list(block):
            kind = entity.dxftype()
            handle = entity.dxf.handle
            reason = None
            duplicate_of = None
            key = None
            if kind == 'LINE':
                if entity.dxf.start == entity.dxf.end:
                    reason = 'zero_length_line'
                else:
                    edge = segment(entity.dxf.start, entity.dxf.end)
                    if (block.name == '*Model_Space' and model_layer(entity) == 'OUTLINE'
                            and edge in outline_edges):
                        reason = 'line_coincident_with_closed_polyline_edge'
                        duplicate_of = outline_edges[edge]
                    key = ('LINE', edge, entity.dxf.get('extrusion', (0, 0, 1)),
                           entity.dxf.get('thickness', 0))
            elif kind == 'CIRCLE':
                key = ('CIRCLE', tuple(entity.dxf.center), entity.dxf.radius,
                       tuple(entity.dxf.get('extrusion', (0, 0, 1))),
                       entity.dxf.get('thickness', 0))
            if not reason and key is not None:
                if key in seen:
                    reason, duplicate_of = 'duplicate', seen[key]
                else:
                    seen[key] = handle
            if reason:
                deleted.append({'handle': handle, 'type': kind, 'block': block.name,
                                'reason': reason, 'duplicate_of': duplicate_of,
                                'original': before[handle]})
                block.delete_entity(entity)

    # Dimension graphics remain in DIM, including their generated text and arrows.
    # Defpoints construction points retain their non-plotting layer.
    for block in doc.blocks:
        for entity in block:
            if block.is_any_layout:
                layer = model_layer(entity)
            else:
                layer = 'Defpoints' if entity.dxftype() == 'POINT' else 'DIM'
            by_layer(entity, layer)
            expected_layers[entity.dxf.handle] = layer

    # Keep future dimension regeneration consistent with the layer standard too.
    used_styles = {e.dxf.dimstyle for e in doc.modelspace().query('DIMENSION')}
    style_changes = {'dimclrd': 256, 'dimclre': 256, 'dimclrt': 256,
                     'dimlwd': -1, 'dimlwe': -1}
    for name in used_styles:
        doc.dimstyles.get(name).dxf.update(style_changes)

    used_layers = {e.dxf.layer.casefold() for e in entities(doc)}
    for layer in list(doc.layers):
        name = layer.dxf.name
        if name.casefold() not in used_layers and name.casefold() not in {'0', 'defpoints'}:
            deleted_layers.append(name)
            doc.layers.remove(name)

    doc.saveas(STAGED)
    saved = ezdxf.readfile(STAGED)
    removed_handles = {item['handle'] for item in deleted}
    after = {e.dxf.handle: record(e) for e in entities(saved)}
    assert after == {h: r for h, r in before.items() if h not in removed_handles}, \
        'Entity geometry, text, or dimension data changed'
    assert geometry(saved) == geometry_before, 'Unique geometric support changed'
    assert saved.units == 4
    assert len(saved.modelspace()) == original_count - len(deleted)
    assert {l.dxf.name for l in saved.layers} == {*STANDARD, '0', 'Defpoints'}
    for name, (color, linetype, weight) in STANDARD.items():
        layer = saved.layers.get(name)
        assert (layer.dxf.color, layer.dxf.linetype.casefold(), layer.dxf.lineweight) == \
            (color, linetype.casefold(), weight)
    for entity in entities(saved):
        assert entity.dxf.layer == expected_layers[entity.dxf.handle]
        assert (entity.dxf.color, entity.dxf.linetype.upper(), entity.dxf.lineweight) == \
            (256, 'BYLAYER', -1)
        assert not entity.dxf.hasattr('true_color')
        assert not entity.dxf.hasattr('color_name')
        assert entity.dxftype() != 'LINE' or entity.dxf.start != entity.dxf.end
    for style in saved.dimstyles:
        expected = dimstyle_before[style.dxf.name].copy()
        if style.dxf.name in used_styles:
            expected.update(style_changes)
        assert style.dxf.all_existing_dxf_attribs() == expected
    model = saved.modelspace()
    assert Counter(e.dxf.layer for e in model) == {'OUTLINE': 6, 'CENTER': 10, 'DIM': 4, 'TEXT': 2}
    assert len(model.query('CIRCLE')) == 5
    assert sorted(round(e.get_measurement(), 9) for e in model.query('DIMENSION')) == [40, 100, 160, 200]
    circles = [(tuple(e.dxf.center), e.dxf.radius) for e in model.query('CIRCLE')]
    assert len(circles) == len(set(circles))
    lines = [segment(e.dxf.start, e.dxf.end) for e in model.query('LINE')]
    assert len(lines) == len(set(lines))
    edges = {edge for e in model.query('LWPOLYLINE') for edge in poly_edges(e)}
    assert not edges.intersection(lines), 'Duplicate polyline edges remain'
    audit = saved.audit()
    assert not audit.errors and not audit.fixes, 'DXF audit found errors or repairs'
    os.replace(STAGED, SOURCE)
    # Verify the final requested pathname as well as the staging file.
    final = ezdxf.readfile(SOURCE)
    assert {e.dxf.handle: record(e) for e in entities(final)} == after
    report = {
        'output': SOURCE.name, 'backup': BACKUP.name, 'units': 'mm',
        'model_entities_before': original_count, 'model_entities_after': len(model),
        'deleted_entities': deleted, 'deleted_layers': deleted_layers,
        'model_layer_counts': dict(Counter(e.dxf.layer for e in model)),
        'all_block_graphics_checked': len(after),
        'plate_size_mm': [200, 100], 'circles_center_radius_mm': circles,
        'dimension_measurements_mm': [e.get_measurement() for e in model.query('DIMENSION')],
        'text': [e.text if e.dxftype() == 'MTEXT' else e.dxf.text
                 for e in model if e.dxftype() in {'TEXT', 'MTEXT'}],
        'audit_errors': len(audit.errors), 'audit_repairs': len(audit.fixes),
        'verification': 'PASS: geometry, dimension definitions, measurements, text and block contents preserved; all graphics ByLayer',
    }
    (ROOT / 'cleanup_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
