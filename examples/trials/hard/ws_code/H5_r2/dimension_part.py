"""Dimension the supplied bracket with ezdxf only; preserve source entities."""
from pathlib import Path
import json
import math
import shutil

import ezdxf
from ezdxf.disassemble import recursive_decompose

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part_original.dxf'
if not BACKUP.exists():
    shutil.copy2(SOURCE, BACKUP)
doc = ezdxf.readfile(BACKUP)
msp = doc.modelspace()
original_handles = [e.dxf.handle for e in msp]

# A separate style avoids changing any existing drawing or text style.
doc.styles.new('SB_DIM_TEXT', dxfattribs={'font': 'arial.ttf'})
doc.dimstyles.new('SB_MM', dxfattribs={
    'dimtxsty': 'SB_DIM_TEXT', 'dimtxt': 3.5, 'dimasz': 2.5,
    'dimscale': 1.0, 'dimlfac': 1.0, 'dimdec': 2, 'dimzin': 8,
    'dimexo': 1.0, 'dimexe': 1.5, 'dimgap': 1.0,
    'dimtad': 1, 'dimtih': 0, 'dimtoh': 0, 'dimtmove': 1,
    'dimclrd': 0, 'dimclre': 0, 'dimclrt': 0,
    'dimlwd': 18, 'dimlwe': 18, 'dimdsep': 46,
    'dimcen': 0.0, 'dimblk': '',
})
records = []

def finish(label, dim, expected):
    dim.render()
    entity = dim.dimension
    value = float(entity.get_measurement())
    assert math.isclose(value, expected, abs_tol=1e-8), (label, value, expected)
    # Persist the actual measurement as well as the definition points and block.
    entity.dxf.actual_measurement = value
    records.append({'label': label, 'handle': entity.dxf.handle,
                    'expected': expected, 'type': entity.dimtype})

def linear(label, p1, p2, base, angle=0, text='<>', location=None):
    dim = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                             text=text, dimstyle='SB_MM',
                             dxfattribs={'layer': 'DIM'})
    if location is not None:
        dim.set_location(location, leader=True)
    axis = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    expected = abs((p2[0]-p1[0])*axis[0] + (p2[1]-p1[1])*axis[1])
    finish(label, dim, expected)

outline = next(iter(msp.query('LWPOLYLINE')))
verts = list(outline.get_points('xy'))
assert verts == [(0, 0), (160, 0), (160, 80), (150, 90), (0, 90)]
holes = sorted(msp.query('CIRCLE'), key=lambda e: e.dxf.center.x)
assert [(tuple(e.dxf.center), e.dxf.radius) for e in holes] == [
    ((25.0, 25.0, 0.0), 7.0), ((135.0, 25.0, 0.0), 7.0)]
arcs = sorted(msp.query('ARC'), key=lambda e: e.dxf.center.x)
assert [(tuple(e.dxf.center), e.dxf.radius, e.dxf.start_angle,
         e.dxf.end_angle) for e in arcs] == [
    ((66., 62., 0.), 6., 90., 270.), ((94., 62., 0.), 6., 270., 90.)]

# Short dimensions nearest the contour; overall dimensions farther away.
linear('overall_length', (0, 0), (160, 0), (0, -27))
linear('overall_height', (0, 0), (0, 90), (-30, 0), 90)
linear('hole_x_from_left', (0, 0), (25, 25), (0, -12))
linear('hole_pitch', (25, 25), (135, 25), (0, -12))
linear('hole_y_from_bottom', (0, 0), (25, 25), (-12, 0), 90)
diam = msp.add_diameter_dim(center=holes[0].dxf.center,
    radius=holes[0].dxf.radius, location=(45, 40),
    dimstyle='SB_MM', text='2×<>',
    override={'dimtoh': 1, 'dimtad': 1, 'dimtofl': 0},
    dxfattribs={'layer': 'DIM'})
finish('two_holes_diameter', diam, 14)

# Slot length is the full end-to-end extent, not the arc-center spacing.
# Locate its left tangent and horizontal axis from the same left/bottom datums.
linear('slot_overall_length', (60, 62), (100, 62), (0, 101))
linear('slot_width', (66, 56), (66, 68), (46, 0), 90)
linear('slot_left_tangent_from_left', (0, 90), (60, 62), (0, 115))
linear('slot_axis_from_bottom', (160, 0), (100, 62), (178, 0), 90)

# The dimension measures the horizontal chamfer leg (10), with the verified
# 45-degree angle as the conventional chamfer suffix. <> stays live.
assert math.degrees(math.atan2(90-80, 160-150)) == 45
linear('chamfer_leg_x_angle', (150, 90), (160, 80), (0, 104),
       text='<>×45%%d', location=(181, 108))

# Only DIMENSION entities are added to model space, no loose text/line labels.
assert all(e.dxftype() == 'DIMENSION' and e.dxf.layer == 'DIM'
           for e in msp if e.dxf.handle not in original_handles)
doc.set_modelspace_vport(height=185, center=(78, 38))
doc.saveas(SOURCE)

# Reopen both files and compare complete serialized source entity tags.
from ezdxf.lldxf.tagwriter import TagCollector
before = ezdxf.readfile(BACKUP)
after = ezdxf.readfile(SOURCE)
for ent in before.modelspace():
    other = after.entitydb[ent.dxf.handle]
    assert TagCollector.dxftags(ent) == TagCollector.dxftags(other), ent.dxf.handle
assert len(after.modelspace()) == len(before.modelspace()) + 11
assert after.units == 4
for item in records:
    ent = after.entitydb[item['handle']]
    assert ent.dxftype() == 'DIMENSION' and ent.dxf.layer == 'DIM'
    assert math.isclose(float(ent.get_measurement()), item['expected'], abs_tol=1e-8)
    assert '<>' in ent.dxf.text
    assert ent.dxf.geometry in after.blocks
    rendered_text = [e.plain_text() for e in ent.virtual_entities()
                     if e.dxftype() == 'MTEXT']
    assert len(rendered_text) == 1, (item, rendered_text)
    if item['label'] == 'two_holes_diameter':
        assert rendered_text == ['2×Ø14'], rendered_text
    if item['label'] == 'chamfer_leg_x_angle':
        assert rendered_text == ['10×45°'], rendered_text
    item['rendered_text'] = rendered_text[0]
    item['value'] = float(ent.get_measurement())

auditor = after.audit()
assert not auditor.errors and not auditor.fixes, (auditor.errors, auditor.fixes)
report = {'units': 'mm', 'original_entities_unchanged': len(original_handles),
          'dimension_count': len(records), 'dimensions': records,
          'audit_errors': len(auditor.errors), 'audit_fixes': len(auditor.fixes),
          'slot_center': [80, 62], 'slot_left_tangent': [60, 62]}
(ROOT / 'dimension_check.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

# Dependency-free preview data, including the actual rendered DIM blocks.
preview = []
for e in recursive_decompose(after.modelspace()):
    t = e.dxftype()
    item = {'type': t, 'layer': e.dxf.layer}
    if t == 'LINE':
        item.update(points=[list(e.dxf.start)[:2], list(e.dxf.end)[:2]])
    elif t == 'LWPOLYLINE':
        points = [list(p) for p in e.get_points('xy')]
        if e.closed:
            points.append(points[0])
        item.update(points=points)
    elif t in ('CIRCLE', 'ARC'):
        start = e.dxf.start_angle if t == 'ARC' else 0
        end = e.dxf.end_angle if t == 'ARC' else 360
        if end <= start:
            end += 360
        cx, cy, _ = e.dxf.center
        item['points'] = [[cx+e.dxf.radius*math.cos(math.radians(a)),
                           cy+e.dxf.radius*math.sin(math.radians(a))]
                          for a in [start+(end-start)*i/128 for i in range(129)]]
    elif t == 'SOLID':
        item['points'] = [list(v)[:2] for v in e.vertices()]
    elif t in ('TEXT', 'MTEXT'):
        item.update(text=e.plain_text(), insert=list(e.dxf.insert)[:2],
                    height=e.dxf.height if t == 'TEXT' else e.dxf.char_height,
                    rotation=e.dxf.rotation if t == 'TEXT' else e.get_rotation())
        item['attachment'] = 0 if t == 'TEXT' else e.dxf.attachment_point
    else:
        continue
    preview.append(item)
(ROOT / 'preview_data.json').write_text(json.dumps(preview, ensure_ascii=False), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
