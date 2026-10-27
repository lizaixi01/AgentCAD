"""Normalize this installation plate without changing surviving geometry or text.
Run with the supplied Python interpreter; uses only ezdxf and the standard library.
"""
from pathlib import Path
from collections import Counter
import json
import shutil
import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector

SOURCE = Path('part.dxf')
BACKUP = Path('part.original.dxf')
CANDIDATE = Path('part.cleaned.dxf')
STANDARDS = {
    'OUTLINE': (7, 'Continuous', 50),
    'CENTER': (1, 'CENTER', 25),
    'DIM': (3, 'Continuous', 25),
    'TEXT': (4, 'Continuous', 25),
}
PRESENTATION_CODES = {6, 8, 62, 370, 420, 430}


def payload(entity):
    # Exported tags also cover polyline vertices, MTEXT content, and XDATA.
    return tuple((tag.code, repr(tag.value)) for tag in
                 TagCollector.dxftags(entity, dxfversion='AC1024')
                 if tag.code not in PRESENTATION_CODES)


def all_entities(doc):
    return [entity for block in doc.blocks for entity in block]


def measurements(doc):
    return {e.dxf.handle: e.get_measurement()
            for e in doc.modelspace().query('DIMENSION')}


def text_contents(doc):
    return {e.dxf.handle: (e.dxf.text if e.dxftype() == 'TEXT' else e.text)
            for e in all_entities(doc) if e.dxftype() in ('TEXT', 'MTEXT')}


def edge_key(start, end):
    return tuple(sorted((tuple(start), tuple(end))))


def assert_no_duplicates(doc):
    for block in doc.blocks:
        seen = set()
        edges = set()
        for e in block.query('LWPOLYLINE'):
            for edge in e.virtual_entities():
                if edge.dxftype() == 'LINE':
                    edges.add(edge_key(edge.dxf.start, edge.dxf.end))
        for e in block:
            if e.dxftype() == 'LINE':
                assert e.dxf.start != e.dxf.end, ('zero length', e.dxf.handle)
                key = ('LINE', edge_key(e.dxf.start, e.dxf.end))
                assert key[1] not in edges, ('redundant outline edge', e.dxf.handle)
            elif e.dxftype() == 'CIRCLE':
                key = ('CIRCLE', tuple(e.dxf.center), e.dxf.radius,
                       tuple(e.dxf.extrusion))
            else:
                # Ignore entity identity but retain geometry/content.
                key = (e.dxftype(), tuple(t for t in payload(e) if t[0] not in (5, 330)))
            assert key not in seen, ('duplicate', block.name, e.dxf.handle)
            seen.add(key)


if BACKUP.exists():
    raise RuntimeError('Backup already exists; refusing to overwrite the original backup.')
shutil.copy2(SOURCE, BACKUP)
doc = ezdxf.readfile(SOURCE)
assert doc.units == 4, 'Input must be millimeters.'
original_payloads = {e.dxf.handle: payload(e) for e in all_entities(doc)}
original_dimensions = measurements(doc)
original_text = text_contents(doc)
original_blocks = {b.name: (payload(b.block), payload(b.endblk)) for b in doc.blocks}
original_dimstyles = {s.dxf.name: s.dxfattribs() for s in doc.dimstyles}
original_entity_count = len(doc.modelspace())
deleted = []

# Compare only within each block/layout, because equal local coordinates in
# different block definitions do not imply duplicated drawing objects.
for block in doc.blocks:
    outline_edges = {}
    for poly in block.query('LWPOLYLINE'):
        if poly.dxf.get('const_width', 0) != 0:
            continue
        if any(p[2] != 0 or p[3] != 0 for p in poly.get_points()):
            continue
        for edge in poly.virtual_entities():
            if edge.dxftype() == 'LINE':
                outline_edges[edge_key(edge.dxf.start, edge.dxf.end)] = poly.dxf.handle
    seen = {}
    for e in list(block):
        reason = None
        duplicate_of = None
        kind = e.dxftype()
        if kind == 'LINE':
            if e.dxf.start == e.dxf.end:
                reason = '零长度直线'
            edge = edge_key(e.dxf.start, e.dxf.end)
            key = ('LINE', edge, tuple(e.dxf.extrusion), e.dxf.get('thickness', 0))
            if not reason and edge in outline_edges:
                reason = '与闭合轮廓的一整条直线边完全重合'
                duplicate_of = outline_edges[edge]
        elif kind == 'CIRCLE':
            key = ('CIRCLE', tuple(e.dxf.center), e.dxf.radius,
                   tuple(e.dxf.extrusion), e.dxf.get('thickness', 0))
        else:
            key = (kind, tuple(t for t in payload(e) if t[0] not in (5, 330)))
        if not reason and key in seen:
            reason = '完全重复的对象'
            duplicate_of = seen[key]
        if reason:
            item = {'handle': e.dxf.handle, 'type': kind, 'block': block.name,
                    'reason': reason, 'duplicate_of': duplicate_of}
            if kind == 'LINE':
                item.update(start=list(e.dxf.start), end=list(e.dxf.end))
            if kind == 'CIRCLE':
                item.update(center=list(e.dxf.center), radius=e.dxf.radius)
            deleted.append(item)
            block.delete_entity(e)
        else:
            seen[key] = e.dxf.handle

assert {x['handle'] for x in deleted} == {'93', '9E', '9F', 'A0', 'A1'}
for name, (color, linetype, lineweight) in STANDARDS.items():
    assert linetype in doc.linetypes
    layer = doc.layers.get(name) if name in doc.layers else doc.layers.new(name)
    layer.dxf.color = color
    layer.dxf.linetype = linetype
    layer.dxf.lineweight = lineweight

# Dimension graphics and arrow blocks belong to DIM, including their text.
# Definition points remain on the non-plotting Defpoints layer.
dimension_blocks = {e.dxf.geometry for e in doc.modelspace().query('DIMENSION')}
arrow_blocks = {e.dxf.name for name in dimension_blocks
                for e in doc.blocks[name].query('INSERT')}
arrow_blocks.update({'_ARCHTICK', '_CLOSEDBLANK'})
for block in doc.blocks:
    is_dim_block = block.name in dimension_blocks | arrow_blocks
    for e in block:
        if is_dim_block:
            layer = 'Defpoints' if e.dxftype() == 'POINT' else 'DIM'
        elif e.dxftype() == 'DIMENSION':
            layer = 'DIM'
        elif e.dxftype() in ('TEXT', 'MTEXT'):
            layer = 'TEXT'
        elif e.dxftype() == 'LINE' and e.dxf.color == 1:
            # Confirm center lines intersect a hole center at their midpoint.
            midpoint = (e.dxf.start + e.dxf.end) / 2
            assert any(midpoint == c.dxf.center for c in block.query('CIRCLE'))
            layer = 'CENTER'
        elif e.dxftype() in ('LINE', 'CIRCLE', 'LWPOLYLINE'):
            layer = 'OUTLINE'
        else:
            raise RuntimeError(f'Unclassified entity: {block.name}, {e.dxftype()}')
        e.dxf.layer = layer
        e.dxf.color = 256
        e.dxf.linetype = 'BYLAYER'
        e.dxf.lineweight = -1
        e.dxf.discard('true_color')
        e.dxf.discard('color_name')

used_layers = {e.dxf.layer.casefold() for e in all_entities(doc)}
deleted_layers = []
for layer in list(doc.layers):
    name = layer.dxf.name
    if name.casefold() not in used_layers and name.casefold() not in {'0', 'defpoints'}:
        deleted_layers.append(name)
        doc.layers.remove(name)

doc.saveas(CANDIDATE)


def verify(path):
    check = ezdxf.readfile(path)
    assert check.units == 4
    remaining = {e.dxf.handle: payload(e) for e in all_entities(check)}
    expected = {h: p for h, p in original_payloads.items()
                if h not in {x['handle'] for x in deleted}}
    assert remaining == expected, 'Geometry/content/metadata changed.'
    assert measurements(check) == original_dimensions
    assert text_contents(check) == original_text
    assert {b.name: (payload(b.block), payload(b.endblk)) for b in check.blocks} == original_blocks
    assert {s.dxf.name: s.dxfattribs() for s in check.dimstyles} == original_dimstyles
    assert set(check.layers.entries) == {n.casefold() for n in (*STANDARDS, '0', 'Defpoints')}
    for name, (color, linetype, lineweight) in STANDARDS.items():
        layer = check.layers.get(name)
        assert (layer.dxf.color, layer.dxf.linetype, layer.dxf.lineweight) == (color, linetype, lineweight)
    for e in all_entities(check):
        assert (e.dxf.color, e.dxf.linetype.upper(), e.dxf.lineweight) == (256, 'BYLAYER', -1)
        assert not e.dxf.hasattr('true_color') and not e.dxf.hasattr('color_name')
        if e.dxf.layer == 'Defpoints':
            assert e.dxftype() == 'POINT'
    assert_no_duplicates(check)
    assert Counter(e.dxf.layer for e in check.modelspace()) == Counter(OUTLINE=6, CENTER=10, DIM=4, TEXT=2)
    poly = next(iter(check.modelspace().query('LWPOLYLINE')))
    assert poly.closed and list(poly.get_points('xy')) == [(0, 0), (200, 0), (200, 100), (0, 100)]
    assert Counter(c.dxf.radius for c in check.modelspace().query('CIRCLE')) == {6.0: 4, 20.0: 1}
    audit = check.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return check

verify(CANDIDATE)
CANDIDATE.replace(SOURCE)
final = verify(SOURCE)
report = {
    'file': str(SOURCE), 'backup': str(BACKUP), 'units': 'mm',
    'modelspace_before': original_entity_count, 'modelspace_after': len(final.modelspace()),
    'deleted_entities': deleted, 'deleted_layers': deleted_layers,
    'modelspace_layers': dict(Counter(e.dxf.layer for e in final.modelspace())),
    'layer_standards': STANDARDS, 'dimensions_mm': original_dimensions,
    'text_content': original_text,
    'outline_mm': [200, 100], 'hole_diameters_mm': [12, 12, 12, 12, 40],
    'verification': {
        'all_surviving_geometry_and_content_tags_identical': True,
        'dimensions_and_text_unchanged': True, 'all_graphic_entities_by_layer': True,
        'no_duplicates_or_zero_length_lines': True, 'audit_errors': 0, 'audit_fixes': 0,
        'definition_points_preserved_on_nonplotting_Defpoints': True,
    },
    'limitations': '已完成代码回读和 DXF audit，未使用 CAD 软件进行屏幕渲染检查。',
}
Path('cleanup_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
