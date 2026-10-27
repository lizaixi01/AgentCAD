"""Undo only round 2, retaining round 1, round 3, and all unrelated bytes."""
from io import StringIO
from pathlib import Path
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round4.before.dxf'
TEMP = ROOT / 'part.round4.checked.dxf'
REPORT = ROOT / 'round4_check.json'
HOLES = ('92', '93', '94', '95')
FIELDS = {
    **{h: ('radius',) for h in HOLES},
    'D2': ('defpoint', 'defpoint4'),
    'D6': ('insert',), 'D8': ('insert',),
    'DA': ('start', 'end'), 'DB': ('start',), 'DF': ('location',),
    'DD': (),  # MTEXT content is stored outside the DXF attribute namespace.
}


def records(data):
    lines = data.splitlines(keepends=True)
    assert len(lines) % 2 == 0
    result, current = [], []
    for i in range(0, len(lines), 2):
        code, value = lines[i:i + 2]
        code = int(code.strip())
        if code == 0 and current:
            result.append(current)
            current = []
        current.append((code, value.strip(), lines[i] + lines[i + 1]))
    if current:
        result.append(current)
    return result


def raw(record):
    return b''.join(pair for _, _, pair in record)


def handle(record):
    if record[0][1] in (b'SECTION', b'ENDSEC', b'EOF'):
        return None
    return next((v.decode('ascii') for c, v, _ in record if c in (5, 105)), None)


def indexed(data):
    result = {handle(r): r for r in records(data) if handle(r)}
    assert len(result) == sum(handle(r) is not None for r in records(data))
    return result


def near(a, b):
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


def main():
    assert not BACKUP.exists(), 'Round 4 already has a backup; inspect before rerunning'
    original = TARGET.read_bytes()
    baseline_bytes = (ROOT / 'part.round2.before.dxf').read_bytes()
    after2_bytes = (ROOT / 'part.round3.before.dxf').read_bytes()
    baseline = ezdxf.readfile(ROOT / 'part.round2.before.dxf')
    before = ezdxf.readfile(TARGET)
    doc = ezdxf.readfile(TARGET)
    old_records = records(baseline_bytes)
    round2_records = records(after2_bytes)
    assert len(old_records) == len(round2_records)
    round2_changes = set()
    for old, new in zip(old_records, round2_records):
        assert handle(old) == handle(new)
        if raw(old) != raw(new):
            round2_changes.add(handle(old))
    assert round2_changes == set(FIELDS), round2_changes
    current_index = indexed(original)
    baseline_index = indexed(baseline_bytes)
    after2_index = indexed(after2_bytes)
    for h in FIELDS:
        assert raw(current_index[h]) == raw(after2_index[h]), (
            'A later edit overlaps round 2; inspect before undoing', h
        )
    assert baseline.units == before.units == 4
    assert all(near(baseline.entitydb[h].dxf.radius, 5) for h in HOLES)
    assert all(near(before.entitydb[h].dxf.radius, 6) for h in HOLES)
    assert baseline.entitydb['DD'].text == '4X %%c10'
    assert before.entitydb['DD'].text == '4X %%c12'

    # Edit the current drawing through ezdxf, restoring only fields changed
    # by round 2. Existing annotation block entities retain their handles.
    for h, attributes in FIELDS.items():
        for name in attributes:
            setattr(doc.entitydb[h].dxf, name, getattr(baseline.entitydb[h].dxf, name))
    doc.entitydb['DD'].text = baseline.entitydb['DD'].text
    stream = StringIO()
    doc.write(stream)
    exported = indexed(stream.getvalue().encode(doc.output_encoding, errors='dxfreplace'))
    newline = b'\r\n' if b'\r\n' in original else b'\n'
    replacements = {}
    for h in FIELDS:
        replacement = raw(exported[h]).replace(b'\r\n', b'\n').replace(b'\n', newline)
        # Not just equivalent geometry: these records exactly match round 1.
        assert replacement == raw(baseline_index[h]), h
        replacements[h] = replacement
    source_records = records(original)
    candidate = b''.join(replacements.get(handle(r), raw(r)) for r in source_records)
    candidate_records = records(candidate)
    assert len(candidate_records) == len(source_records)
    changes = []
    for old, new in zip(source_records, candidate_records):
        assert handle(old) == handle(new)
        if raw(old) != raw(new):
            changes.append(handle(old))
    assert set(changes) == set(FIELDS)

    def verify(path):
        checked = ezdxf.readfile(path)
        assert checked.units == 4
        assert len(checked.modelspace()) == len(before.modelspace()) == 17
        assert len(checked.entitydb) == len(before.entitydb)
        expected_centers = ((12, 12, 0), (138, 12, 0), (12, 68, 0), (138, 68, 0))
        for h, center in zip(HOLES, expected_centers):
            hole = checked.entitydb[h]
            assert hole.dxftype() == 'CIRCLE' and near(hole.dxf.radius, 5)
            assert hole.dxf.center.isclose(center)
            assert hole.dxf.center == before.entitydb[h].dxf.center
        for h in FIELDS:
            assert checked.entitydb[h].dxf.all_existing_dxf_attribs() == (
                baseline.entitydb[h].dxf.all_existing_dxf_attribs()
            ), h
        dim = checked.entitydb['D2']
        assert dim.dimtype == 3 and near(dim.get_measurement(), 10)
        assert dim.dxf.text == '4X <>'
        assert checked.entitydb['DD'].text == '4X %%c10'
        center = checked.entitydb['95'].dxf.center
        assert ((dim.dxf.defpoint + dim.dxf.defpoint4) / 2).isclose(center)
        for endpoint, arrow in (('defpoint', 'D8'), ('defpoint4', 'D6')):
            point = getattr(dim.dxf, endpoint)
            assert near((point - center).magnitude, 5)
            assert checked.entitydb[arrow].dxf.insert.isclose(point)
        assert checked.entitydb['DF'].dxf.location.isclose(dim.dxf.defpoint4)
        plate = checked.entitydb['91']
        assert plate.closed
        assert list(plate.get_points()) == list(baseline.entitydb['91'].get_points())
        bounds = bbox.extents([plate])
        assert near(bounds.size.x, 150) and near(bounds.size.y, 80)
        assert near(checked.entitydb['96'].get_measurement(), 150)
        assert near(checked.entitydb['A5'].get_measurement(), 80)
        assert checked.entitydb['FF'].dxf.center.isclose((75, 40, 0))
        assert near(checked.entitydb['FF'].dxf.radius * 2, 30)
        new_dim = checked.entitydb['100']
        assert near(new_dim.get_measurement(), 30)
        assert [e.text for e in checked.blocks[new_dim.dxf.geometry].query('MTEXT')] == ['%%c30']
        disk_records = records(path.read_bytes())
        assert [raw(r) for r in disk_records if handle(r) not in FIELDS] == [
            raw(r) for r in source_records if handle(r) not in FIELDS
        ]
        audit = checked.audit()
        assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
        return checked, audit

    TEMP.write_bytes(candidate)
    verify(TEMP)
    BACKUP.write_bytes(original)
    TARGET.write_bytes(candidate)
    checked, audit = verify(TARGET)
    assert TARGET.read_bytes() == candidate and BACKUP.read_bytes() == original
    TEMP.unlink()
    report = {
        'drawing': TARGET.name, 'backup': BACKUP.name, 'units': 'mm',
        'restored_from': 'part.round2.before.dxf',
        'holes': [{'handle': h, 'center_mm': list(checked.entitydb[h].dxf.center),
                   'diameter_mm': 2 * checked.entitydb[h].dxf.radius} for h in HOLES],
        'diameter_dimension_measurement_mm': checked.entitydb['D2'].get_measurement(),
        'diameter_dimension_display': '4X %%c10',
        'round1_plate_size_mm': [150, 80],
        'round1_plate_and_width_dimension_unchanged': True,
        'round3_center_hole_mm': {'center': [75, 40, 0], 'diameter': 30},
        'round3_hole_and_dimension_records_byte_identical': True,
        'restored_records_exactly_match_pre_round2': True,
        'changed_entity_handles': changes,
        'all_other_dxf_records_byte_identical': True,
        'modelspace_entity_count': len(checked.modelspace()),
        'audit_errors': len(audit.errors), 'audit_fixes': len(audit.fixes),
        'errors_encountered': [],
        'before_sha256': hashlib.sha256(original).hexdigest(),
        'after_sha256': hashlib.sha256(candidate).hexdigest(),
        'layout_note': 'Existing customer logo overlap is preserved; no layout changes were authorized.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
