"""Dimension the supplied bracket without changing its original entities."""
from pathlib import Path
import json
import math
import shutil

import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.original.dxf'


def entity_tags(entity):
    return [(tag.code, str(tag.value)) for tag in TagCollector.dxftags(entity)]


def main():
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
    doc = ezdxf.readfile(BACKUP)
    msp = doc.modelspace()
    original = {e.dxf.handle: entity_tags(e) for e in msp}
    assert len(original) == 15
    assert not msp.query('DIMENSION')
    assert doc.units == 4

    outline = list(msp.query('LWPOLYLINE'))[0]
    vertices = [(float(p[0]), float(p[1])) for p in outline.get_points()]
    assert vertices == [(0, 0), (160, 0), (160, 80), (150, 90), (0, 90)]
    circles = sorted(msp.query('CIRCLE'), key=lambda e: e.dxf.center.x)
    assert [(tuple(e.dxf.center), e.dxf.radius) for e in circles] == [
        ((25, 25, 0), 7), ((135, 25, 0), 7)]
    arcs = sorted(msp.query('ARC'), key=lambda e: e.dxf.center.x)
    assert [(tuple(e.dxf.center), e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
            for e in arcs] == [((66, 62, 0), 6, 90, 270), ((94, 62, 0), 6, 270, 90)]
    # Dimensions are derived from the checked geometry, including the slot's
    # rounded ends (overall length, rather than distance between arc centers).
    width = max(x for x, y in vertices)
    height = max(y for x, y in vertices)
    h1, h2 = circles
    a1, a2 = arcs
    slot_left = a1.dxf.center.x - a1.dxf.radius
    slot_right = a2.dxf.center.x + a2.dxf.radius
    slot_y = a1.dxf.center.y
    radius = a1.dxf.radius
    chamfer = width - vertices[3][0]
    assert math.isclose(chamfer, height - vertices[2][1])

    style_name = 'SB160_MM'
    doc.dimstyles.new(style_name, dxfattribs={
        'dimscale': 1, 'dimlfac': 1, 'dimtxt': 3, 'dimasz': 2.3,
        'dimexo': 1.5, 'dimexe': 1.5, 'dimgap': 0.9,
        'dimtad': 1, 'dimtih': 0, 'dimtoh': 0,
        'dimdec': 0, 'dimzin': 8, 'dimlunit': 2,
        'dimclrd': 0, 'dimclre': 0, 'dimclrt': 0,
        'dimtxsty': 'Standard', 'dimtmove': 1,
    })
    specs = []

    def linear(name, p1, p2, base, angle=0, text='<>', expected=None):
        dim = msp.add_linear_dim(
            base=base, p1=p1, p2=p2, angle=angle, text=text,
            dimstyle=style_name, dxfattribs={'layer': 'DIM'})
        dim.render()
        specs.append((name, dim.dimension.dxf.handle, expected))

    linear('overall_length', (0, 0), (width, 0), (0, -27), expected=width)
    linear('overall_height', (0, 0), (0, height), (-40, 0), 90, expected=height)
    linear('hole_x_from_left', (0, 0), h1.dxf.center, (0, -12), expected=h1.dxf.center.x)
    linear('hole_center_spacing', h1.dxf.center, h2.dxf.center, (0, -12),
           expected=h2.dxf.center.x-h1.dxf.center.x)
    linear('hole_y_from_bottom', (0, 0), h1.dxf.center, (-13, 0), 90,
           expected=h1.dxf.center.y)
    diameter = msp.add_diameter_dim(
        center=h1.dxf.center, radius=h1.dxf.radius, location=(48, 42),
        text='2×<>', dimstyle=style_name, dxfattribs={'layer': 'DIM'})
    diameter.render()
    specs.append(('two_hole_diameters', diameter.dimension.dxf.handle, 2*h1.dxf.radius))

    linear('slot_overall_length', (slot_left, slot_y), (slot_right, slot_y),
           (0, 103), expected=slot_right-slot_left)
    linear('slot_width', (a2.dxf.center.x, slot_y-radius),
           (a2.dxf.center.x, slot_y+radius), (112, 0), 90, expected=2*radius)
    linear('slot_left_end_from_left', (0, height), (slot_left, slot_y),
           (0, 117), expected=slot_left)
    linear('slot_axis_from_bottom', (0, 0), (slot_left, slot_y),
           (-27, 0), 90, expected=slot_y)
    linear('chamfer', vertices[3], vertices[2], (0, 103),
           text='<>×45°', expected=chamfer)

    # Every visible component of a dimension also belongs to DIM. DEFPOINTS
    # markers are non-plotting construction data and retain their own layer.
    for dim in msp.query('DIMENSION'):
        for entity in doc.blocks[dim.dxf.geometry]:
            if entity.dxftype() != 'POINT':
                entity.dxf.layer = 'DIM'

    audit = doc.audit()
    assert not audit.errors, audit.errors
    assert not audit.fixes, audit.fixes
    doc.saveas(TARGET)

    result = ezdxf.readfile(TARGET)
    result_msp = result.modelspace()
    for handle, tags in original.items():
        assert entity_tags(result.entitydb[handle]) == tags, f'Original changed: {handle}'
    added = [e for e in result_msp if e.dxf.handle not in original]
    assert len(added) == 11 and all(e.dxftype() == 'DIMENSION' for e in added)
    records = []
    for name, handle, expected in specs:
        entity = result.entitydb[handle]
        actual = float(entity.get_measurement())
        assert entity.dxf.layer == 'DIM'
        assert math.isclose(actual, expected, abs_tol=1e-8), (name, actual, expected)
        block = result.blocks[entity.dxf.geometry]
        texts = [e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                 for e in block if e.dxftype() in ('TEXT', 'MTEXT')]
        assert texts
        if name == 'two_hole_diameters':
            assert texts == ['2×Ø14'], texts
        elif name == 'chamfer':
            assert texts == ['10×45°'], texts
        else:
            assert texts == [str(round(expected))], texts
        records.append({'name': name, 'handle': handle, 'measurement_mm': actual,
                        'displayed_text': texts})
    audit = result.audit()
    assert not audit.errors and not audit.fixes

    # Export resolved geometry for a preview using Windows' built-in drawing API.
    primitives = []
    def export(entity):
        kind = entity.dxftype()
        if kind == 'INSERT':
            for child in entity.virtual_entities():
                export(child)
            return
        attrs = entity.dxf
        item = {'type': kind, 'layer': attrs.layer}
        if kind == 'LINE':
            item.update(start=list(attrs.start)[:2], end=list(attrs.end)[:2])
        elif kind in ('CIRCLE', 'ARC'):
            item.update(center=list(attrs.center)[:2], radius=attrs.radius)
            if kind == 'ARC':
                item.update(start_angle=attrs.start_angle, end_angle=attrs.end_angle)
        elif kind == 'LWPOLYLINE':
            item.update(points=[list(p)[:2] for p in entity.get_points()], closed=entity.closed)
        elif kind == 'SOLID':
            item.update(points=[list(v)[:2] for v in entity.wcs_vertices()])
        elif kind in ('TEXT', 'MTEXT'):
            item.update(insert=list(attrs.insert)[:2],
                        text=entity.plain_text() if kind == 'MTEXT' else attrs.text,
                        height=attrs.char_height if kind == 'MTEXT' else attrs.height,
                        rotation=attrs.get('rotation', 0),
                        attachment=attrs.attachment_point if kind == 'MTEXT' else 7)
        else:
            return
        primitives.append(item)
    for entity in result_msp:
        if entity.dxftype() == 'DIMENSION':
            for child in entity.virtual_entities():
                export(child)
        else:
            export(entity)
    (ROOT / 'preview_geometry.json').write_text(json.dumps(primitives, ensure_ascii=False), encoding='utf-8')
    report = {'units': 'mm', 'original_entities_unchanged': len(original),
              'added_dimension_entities': len(added), 'audit_errors': 0,
              'audit_fixes': 0, 'dimensions': records}
    (ROOT / 'dimension_check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
