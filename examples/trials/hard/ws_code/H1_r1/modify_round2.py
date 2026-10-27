"""Round 2: change the four mounting holes and their existing callout to 12 mm.

Use ezdxf to edit and validate entities; retain every other DXF record verbatim.
The round 1 drawing and all its accompanying files remain the baseline.
"""
from io import StringIO
from pathlib import Path
import json
import math

import ezdxf


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round2.before.dxf'
TEMP = ROOT / 'part.round2.checked.dxf'
REPORT = ROOT / 'round2_check.json'


def records(data):
    lines = data.splitlines(keepends=True)
    assert len(lines) % 2 == 0
    result, current = [], []
    for i in range(0, len(lines), 2):
        code, value = lines[i:i + 2]
        if int(code.strip()) == 0 and current:
            result.append(current)
            current = []
        current.append((int(code.strip()), value.strip(), code + value))
    if current:
        result.append(current)
    return result


def handle(record):
    return next((v.decode('ascii') for c, v, _ in record if c == 5), None)


def raw(record):
    return b''.join(pair for _, _, pair in record)


def near(a, b):
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


def same_point(a, b):
    return all(near(x, y) for x, y in zip(a, b))


original = TARGET.read_bytes()
before = ezdxf.readfile(TARGET)
doc = ezdxf.readfile(TARGET)
assert doc.units == 4, 'Drawing must be in millimetres'
hole_handles = ('92', '93', '94', '95')
expected_centers = ((12, 12, 0), (138, 12, 0), (12, 68, 0), (138, 68, 0))
assert {e.dxf.handle for e in doc.modelspace().query('CIRCLE[layer=="HOLES"]')} == set(hole_handles)
for h, center in zip(hole_handles, expected_centers):
    hole = doc.entitydb[h]
    assert hole.dxftype() == 'CIRCLE' and near(hole.dxf.radius, 5)
    assert same_point(hole.dxf.center, center)
    hole.dxf.radius = 6

dim = doc.entitydb['D2']
assert dim.dimtype == 3 and near(dim.get_measurement(), 10)
assert dim.dxf.text == '4X <>'
assert doc.entitydb['DD'].text == '4X %%c10'
center = doc.entitydb['95'].dxf.center
assert same_point((dim.dxf.defpoint + dim.dxf.defpoint4) / 2, center)
direction = (dim.dxf.defpoint - center).normalize()
assert near((dim.dxf.defpoint - center).magnitude, 5)

# Extend the existing diameter endpoints radially by 1 mm. Keep the text,
# leader elbow, arrow sizes, angles, and annotation style in their places.
dim.dxf.defpoint += direction
dim.dxf.defpoint4 -= direction
doc.entitydb['D6'].dxf.insert -= direction
doc.entitydb['D8'].dxf.insert += direction
doc.entitydb['DA'].dxf.start -= direction
doc.entitydb['DA'].dxf.end += direction
doc.entitydb['DB'].dxf.start -= direction
doc.entitydb['DF'].dxf.location -= direction
doc.entitydb['DD'].text = '4X %%c12'

changed_handles = {*hole_handles, 'D2', 'D6', 'D8', 'DA', 'DB', 'DD', 'DF'}
stream = StringIO()
doc.write(stream)
exported = stream.getvalue().encode(doc.output_encoding, errors='dxfreplace')
exported_by_handle = {handle(r): r for r in records(exported) if handle(r)}
source_records = records(original)
assert changed_handles <= exported_by_handle.keys()
newline = b'\r\n' if b'\r\n' in original else b'\n'
output = []
for record in source_records:
    h = handle(record)
    if h in changed_handles:
        replacement = raw(exported_by_handle[h])
        if newline == b'\r\n':
            replacement = replacement.replace(b'\r\n', b'\n').replace(b'\n', newline)
        output.append(replacement)
    else:
        output.append(raw(record))
candidate = b''.join(output)
new_records = records(candidate)
assert len(new_records) == len(source_records)
actual_changes = []
for old, new in zip(source_records, new_records):
    assert handle(old) == handle(new)
    if raw(old) != raw(new):
        actual_changes.append(handle(old))
assert set(actual_changes) == changed_handles, actual_changes


def verify(drawing):
    assert drawing.units == before.units == 4
    assert len(drawing.entitydb) == len(before.entitydb)
    assert len(drawing.modelspace()) == len(before.modelspace()) == 15
    for h in hole_handles:
        hole = drawing.entitydb[h]
        assert near(hole.dxf.radius, 6)
        assert same_point(hole.dxf.center, before.entitydb[h].dxf.center)
        old_attrs = before.entitydb[h].dxf.all_existing_dxf_attribs()
        new_attrs = hole.dxf.all_existing_dxf_attribs()
        assert {k: v for k, v in old_attrs.items() if k != 'radius'} == {
            k: v for k, v in new_attrs.items() if k != 'radius'
        }
    checked_dim = drawing.entitydb['D2']
    assert near(checked_dim.get_measurement(), 12)
    assert checked_dim.dxf.text == '4X <>'
    assert drawing.entitydb['DD'].text == '4X %%c12'
    assert same_point(checked_dim.dxf.text_midpoint, before.entitydb['D2'].dxf.text_midpoint)
    assert same_point(drawing.entitydb['DD'].dxf.insert, before.entitydb['DD'].dxf.insert)
    for attr, arrow in [('defpoint', 'D8'), ('defpoint4', 'D6')]:
        p = getattr(checked_dim.dxf, attr)
        assert near((p - center).magnitude, 6)
        assert same_point(drawing.entitydb[arrow].dxf.insert, p)
        assert near(drawing.entitydb[arrow].dxf.rotation, before.entitydb[arrow].dxf.rotation)
    assert same_point(drawing.entitydb['DF'].dxf.location, checked_dim.dxf.defpoint4)
    assert same_point(drawing.entitydb['DE'].dxf.location, center)
    # Both arrow bases retain their original 2.5 mm offsets along the leader.
    assert same_point(drawing.entitydb['DA'].dxf.start, checked_dim.dxf.defpoint4 - 2.5 * direction)
    assert same_point(drawing.entitydb['DA'].dxf.end, checked_dim.dxf.defpoint - 2.5 * direction)
    assert same_point(drawing.entitydb['DB'].dxf.start, drawing.entitydb['DA'].dxf.start)
    assert same_point(drawing.entitydb['DB'].dxf.end, before.entitydb['DB'].dxf.end)
    plate = list(drawing.entitydb['91'].get_points())
    assert plate == list(before.entitydb['91'].get_points())
    assert near(max(p[0] for p in plate) - min(p[0] for p in plate), 150)
    assert near(max(p[1] for p in plate) - min(p[1] for p in plate), 80)
    assert near(drawing.entitydb['96'].get_measurement(), 150)
    audit = drawing.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return audit


TEMP.write_bytes(candidate)
verify(ezdxf.readfile(TEMP))
if BACKUP.exists():
    assert BACKUP.read_bytes() == original, 'Existing round 2 backup differs'
else:
    BACKUP.write_bytes(original)
TARGET.write_bytes(candidate)
# Reopen the final delivered file, not just the in-memory edited document.
audit = verify(ezdxf.readfile(TARGET))
assert TARGET.read_bytes() == candidate
TEMP.unlink()
report = {
    'drawing': TARGET.name,
    'backup': BACKUP.name,
    'units': 'mm',
    'holes': [
        {'handle': h, 'center_mm': list(c), 'diameter_mm': 12}
        for h, c in zip(hole_handles, expected_centers)
    ],
    'diameter_dimension_measurement_mm': ezdxf.readfile(TARGET).entitydb['D2'].get_measurement(),
    'diameter_dimension_display': '4X %%c12',
    'hole_centers_unchanged': True,
    'plate_size_mm': [150, 80],
    'changed_entity_handles': actual_changes,
    'all_other_dxf_records_byte_identical': True,
    'entity_count_unchanged': True,
    'modelspace_entity_count': 15,
    'audit_errors': len(audit.errors),
    'audit_fixes': len(audit.fixes),
    'errors_encountered': [],
    'layout_note': '第一轮已记录的客户标识与板区域重叠保持原样；本轮仅修改孔径及对应标注。',
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
