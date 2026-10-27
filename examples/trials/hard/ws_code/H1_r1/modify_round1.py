"""Round 1: widen only the plate and move its right-hand holes/dimensions.
Run with the supplied Python environment. No third-party package except ezdxf.
Preserves every DXF byte outside the explicitly changed entity records.
"""
from pathlib import Path
from io import StringIO
import json
import math
import ezdxf

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round1.before.dxf'
REPORT = ROOT / 'round1_check.json'


def records(data):
    lines = data.splitlines(keepends=True)
    assert len(lines) % 2 == 0, 'DXF must contain code/value pairs'
    result = []
    current = []
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
    return math.isclose(a, b, abs_tol=1e-9)


original = TARGET.read_bytes()
doc = ezdxf.readfile(TARGET)
assert doc.units == 4, 'Expected millimetres'
plate = doc.entitydb['91']
points = list(plate.get_points())
assert near(max(p[0] for p in points), 120), 'Expected unmodified 120 mm plate'
assert plate.closed
assert [(doc.entitydb[h].dxf.center.x, doc.entitydb[h].dxf.center.y) for h in ('93', '95')] == [(108, 12), (108, 68)]

# Keep all corner bulges, y coordinates, widths and left-hand vertices.
plate.set_points([(x + 30 if x > 60 else x, y, sw, ew, bulge)
                  for x, y, sw, ew, bulge in points])
for h in ('93', '95'):
    doc.entitydb[h].translate(30, 0, 0)

# Update both DIMENSION definition and its existing rendered graphics.
width = doc.entitydb['96']
assert near(width.get_measurement(), 120)
width.dxf.defpoint3 += (30, 0, 0)
width.dxf.text_midpoint += (15, 0, 0)
for h in ('9B', '9E', 'A4'):
    doc.entitydb[h].translate(30, 0, 0)
doc.entitydb['A0'].dxf.end += (30, 0, 0)
width_text = doc.entitydb['A1']
assert width_text.text == '120', repr(width_text.text)
width_text.text = '150'
width_text.translate(15, 0, 0)

# The 4X diameter callout must continue to point at the upper right hole.
diameter = doc.entitydb['D2']
diameter_block_handles = [e.dxf.handle for e in doc.blocks[diameter.dxf.geometry]]
diameter.translate(30, 0, 0)

changed_handles = {'91', '93', '95', '96', '9B', '9E', 'A0', 'A1', 'A4', 'D2', *diameter_block_handles}
# Export with ezdxf, then substitute only the authorized entity records into
# the original file. This also preserves untouched headers, objects and text.
stream = StringIO()
doc.write(stream)
exported = stream.getvalue().encode(doc.output_encoding, errors='dxfreplace')
source_records = records(original)
exported_by_handle = {handle(r): r for r in records(exported) if handle(r)}
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

# Read the actual output through ezdxf before replacing the working drawing.
TEMP = ROOT / 'part.round1.checked.dxf'
TEMP.write_bytes(candidate)
check = ezdxf.readfile(TEMP)
before = ezdxf.readfile(TARGET)
new_records = records(candidate)
assert len(new_records) == len(source_records)
actual_changes = []
for old, new in zip(source_records, new_records):
    assert handle(old) == handle(new)
    if raw(old) != raw(new):
        assert handle(old) in changed_handles, f'Unexpected change: {handle(old)}'
        actual_changes.append(handle(old))
assert set(actual_changes) == changed_handles
assert len(check.modelspace()) == len(before.modelspace()) == 15
assert check.units == before.units == 4
np = list(check.entitydb['91'].get_points())
assert check.entitydb['91'].closed
assert near(max(p[0] for p in np) - min(p[0] for p in np), 150)
assert near(max(p[1] for p in np) - min(p[1] for p in np), 80)
for old, new in zip(points, np):
    expected_x = old[0] + 30 if old[0] > 60 else old[0]
    assert near(new[0], expected_x)
    assert all(near(a, b) for a, b in zip(old[1:], new[1:]))
# Arc bulges and unchanged 5 mm tangent offsets retain R5 at all corners.
for index in (1, 3, 5, 7):
    p, q = np[index], np[(index + 1) % len(np)]
    chord = math.hypot(q[0] - p[0], q[1] - p[1])
    radius = chord * (1 + p[4] ** 2) / (4 * abs(p[4]))
    assert near(radius, 5)
holes = []
for h, expected in [('92', (12, 12)), ('93', (138, 12)), ('94', (12, 68)), ('95', (138, 68))]:
    hole = check.entitydb[h]
    assert near(hole.dxf.center.x, expected[0]) and near(hole.dxf.center.y, expected[1])
    assert near(hole.dxf.radius, 5)
    holes.append({'handle': h, 'center': list(hole.dxf.center), 'diameter_mm': 10})
for h in ('93', '95'):
    assert near(150 - check.entitydb[h].dxf.center.x, 12)
assert near(check.entitydb['96'].get_measurement(), 150)
assert check.entitydb['A1'].text == '150'
assert near(check.entitydb['A1'].dxf.insert.x, 75)
assert near(check.entitydb['9B'].dxf.start.x, 150)
assert near(check.entitydb['9E'].dxf.insert.x, 150)
assert near(check.entitydb['A0'].dxf.end.x, 147.5)
assert near(check.entitydb['D2'].get_measurement(), 10)
center = check.entitydb['95'].dxf.center
for attr in ('defpoint', 'defpoint4'):
    assert near((getattr(check.entitydb['D2'].dxf, attr) - center).magnitude, 5)
assert check.entitydb['DD'].text == before.entitydb['DD'].text
assert near(check.entitydb['DE'].dxf.location.x, 138)
audit = check.audit()
assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)

if BACKUP.exists():
    assert BACKUP.read_bytes() == original, 'Existing backup differs; refusing to overwrite'
else:
    BACKUP.write_bytes(original)
TARGET.write_bytes(candidate)
assert TARGET.read_bytes() == candidate
TEMP.unlink()
report = {
    'drawing': TARGET.name,
    'backup': BACKUP.name,
    'units': 'mm',
    'plate_size_mm': [150, 80],
    'corner_radius_mm': 5,
    'holes': holes,
    'right_hole_edge_distance_mm': 12,
    'width_dimension_measurement_mm': 150,
    'width_dimension_display': check.entitydb['A1'].text,
    'diameter_dimension_mm': check.entitydb['D2'].get_measurement(),
    'modelspace_entity_count': len(check.modelspace()),
    'changed_entity_handles': actual_changes,
    'all_other_dxf_records_byte_identical': True,
    'audit_errors': len(audit.errors),
    'audit_fixes': len(audit.fixes),
    'layout_note': '加宽后的板区域与原客户标识区域重叠；客户标识按要求保持不变。',
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
