"""Final revision: change the title-block REV and add one revision note only."""
from io import StringIO
from pathlib import Path
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox

# Reuse the byte-preserving DXF record helpers from the previous round.
from modify_round4 import records, raw, handle, indexed

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round5.before.dxf'
TEMP = ROOT / 'part.round5.checked.dxf'
REPORT = ROOT / 'round5_check.json'
NOTE = 'REV C: 宽度 150，增加中心孔 Ø30'


def main():
    assert not BACKUP.exists(), 'Round 5 backup exists; inspect before rerunning.'
    original = TARGET.read_bytes()
    before = ezdxf.readfile(TARGET)
    doc = ezdxf.readfile(TARGET)
    assert doc.units == 4
    title_blocks = [e for e in doc.modelspace().query('INSERT')
                    if e.dxf.name == 'TB' and e.has_attrib('REV')]
    assert len(title_blocks) == 1
    rev = title_blocks[0].get_attrib('REV')
    old_revision = rev.dxf.text
    assert old_revision == 'A'
    rev.dxf.text = 'C'
    # Explicit installed Chinese font without changing any existing text style.
    note = doc.modelspace().add_mtext(
        r'{\fMicrosoft YaHei|b0|i0;' + NOTE + '}',
        dxfattribs={'layer': 'NOTES', 'insert': (0, -22, 0),
                    'char_height': 3.0, 'width': 120.0,
                    'attachment_point': 1, 'style': 'Standard'},
    )
    note_handle = note.dxf.handle
    next_handle = str(doc.entitydb.handles)
    assert int(note_handle, 16) >= int(before.header['$HANDSEED'], 16)
    stream = StringIO()
    doc.write(stream)
    exported = indexed(stream.getvalue().encode(doc.output_encoding, errors='dxfreplace'))
    newline = b'\r\n' if b'\r\n' in original else b'\n'

    def normalize(data):
        return data.replace(b'\r\n', b'\n').replace(b'\n', newline)

    # Preserve every original record, including comments and custom data.
    source_records = records(original)
    result = []
    section = None
    inserted = False
    for record in source_records:
        if record[0][1] == b'SECTION':
            section = next(v for c, v, _ in record if c == 2)
        if section == b'ENTITIES' and record[0][1] == b'ENDSEC':
            result.append(normalize(raw(exported[note_handle])))
            inserted = True
        if handle(record) == rev.dxf.handle:
            # ezdxf normalizes the existing ATTRIB owner on export. Retain
            # its original owner bytes and take only the edited text value.
            text_value = next(v for c, v, _ in exported[rev.dxf.handle] if c == 1)
            assert text_value == b'C'
            replacement = b''.join(
                pair.splitlines(keepends=True)[0] + text_value + newline
                if code == 1 else pair for code, _, pair in record)
            # Exactly one group value changes inside the existing attribute.
            old = [(c, v) for c, v, _ in record]
            new = [(c, v) for c, v, _ in records(replacement)[0]]
            assert len(old) == len(new)
            assert [(a, b) for a, b in zip(old, new) if a != b] == [
                ((1, b'A'), (1, b'C'))]
            result.append(replacement)
        elif section == b'HEADER' and record[0][1] == b'SECTION':
            patched = []
            pending = False
            replacements = 0
            for code, value, pair in record:
                if pending:
                    assert code == 5
                    code_line = pair.splitlines(keepends=True)[0]
                    pair = code_line + next_handle.encode('ascii') + newline
                    pending = False
                    replacements += 1
                patched.append(pair)
                if code == 9 and value == b'$HANDSEED':
                    pending = True
            assert replacements == 1 and not pending
            result.append(b''.join(patched))
        else:
            result.append(raw(record))
        if record[0][1] == b'ENDSEC':
            section = None
    assert inserted
    candidate = b''.join(result)

    def verify(path):
        checked = ezdxf.readfile(path)
        assert checked.units == 4
        assert checked.entitydb[rev.dxf.handle].dxf.text == 'C'
        assert checked.entitydb[rev.dxf.handle].dxf.tag == 'REV'
        new_note = checked.entitydb[note_handle]
        assert new_note.dxftype() == 'MTEXT'
        assert new_note.plain_text() == NOTE
        assert '\\P' not in new_note.text and '\n' not in new_note.text
        assert new_note.dxf.layer == 'NOTES'
        assert new_note.dxf.insert.isclose((0, -22, 0))
        assert new_note.dxf.char_height == 3
        assert len(checked.modelspace()) == len(before.modelspace()) + 1 == 18
        assert len(checked.entitydb) == len(before.entitydb) + 1
        assert checked.header['$HANDSEED'] == next_handle
        # All existing entities other than REV remain byte-for-byte identical.
        old_index = indexed(original)
        new_index = indexed(path.read_bytes())
        assert set(new_index) - set(old_index) == {note_handle}
        assert set(old_index) - set(new_index) == set()
        changed = [h for h in old_index if raw(old_index[h]) != raw(new_index[h])]
        assert changed == [rev.dxf.handle]
        # Also compare all non-entity records, allowing only the handle seed.
        source_filtered = [raw(r) for r in source_records
                           if handle(r) != rev.dxf.handle]
        checked_filtered = [raw(r) for r in records(path.read_bytes())
                            if handle(r) not in (rev.dxf.handle, note_handle)]
        assert source_filtered[1:] == checked_filtered[1:]
        old_header = source_filtered[0]
        new_header = checked_filtered[0]
        seed_old = before.header['$HANDSEED'].encode('ascii') + newline
        seed_new = next_handle.encode('ascii') + newline
        assert old_header.replace(seed_old, seed_new, 1) == new_header
        bounds = bbox.extents([new_note])
        assert bounds.has_data
        assert bounds.extmin.x >= 0 and bounds.extmax.x <= 120
        assert bounds.extmin.y > -30 and bounds.extmax.y < -16.25
        # The whole reserved single-line strip is empty in the original drawing.
        overlaps = []
        for entity in before.modelspace():
            ext = bbox.extents([entity])
            if (ext.has_data and ext.extmin.x < 120 and ext.extmax.x > 0
                    and ext.extmin.y < -22 and ext.extmax.y > -26):
                overlaps.append(entity.dxf.handle)
        assert not overlaps, overlaps
        plate_bounds = bbox.extents([checked.entitydb['91']])
        assert plate_bounds.size.isclose((150, 80, 0))
        assert checked.entitydb['96'].get_measurement() == 150
        assert checked.entitydb['FF'].dxf.center.isclose((75, 40, 0))
        assert checked.entitydb['FF'].dxf.radius == 15
        assert math.isclose(checked.entitydb['100'].get_measurement(), 30,
                            rel_tol=0, abs_tol=1e-9)
        assert all(checked.entitydb[h].dxf.radius == 5 for h in ('92', '93', '94', '95'))
        audit = checked.audit()
        assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
        return bounds, changed

    TEMP.write_bytes(candidate)
    bounds, changed = verify(TEMP)
    BACKUP.write_bytes(original)
    TARGET.write_bytes(candidate)
    verify(TARGET)
    assert BACKUP.read_bytes() == original and TARGET.read_bytes() == candidate
    TEMP.unlink()
    report = {
        'drawing': TARGET.name, 'backup': BACKUP.name, 'units': 'mm',
        'title_block': 'TB', 'attribute_tag': 'REV',
        'old_revision': old_revision, 'new_revision': 'C',
        'changed_existing_entity_handles': changed,
        'added_entity_handle': note_handle, 'added_text': NOTE,
        'text_insertion_mm': [0, -22, 0], 'text_height_mm': 3,
        'text_font': 'Microsoft YaHei',
        'text_estimated_bounds_mm': [list(bounds.extmin), list(bounds.extmax)],
        'single_line_and_clear_of_existing_content': True,
        'plate_size_mm': [150, 80], 'center_hole_diameter_mm': 30,
        'center_hole_center_mm': [75, 40, 0], 'mounting_hole_diameters_mm': [10] * 4,
        'all_other_existing_entity_records_byte_identical': True,
        'other_header_change': {'$HANDSEED': [before.header['$HANDSEED'], next_handle]},
        'all_remaining_records_byte_identical': True,
        'modelspace_entity_count': 18, 'audit_errors': 0, 'audit_fixes': 0,
        'errors_encountered': [
            'Initial preflight caught ezdxf normalizing the ATTRIB owner from 17 to ED. '
            'Resolved by transferring only group 1 text into the original record; '
            'the original drawing was not written during the failed preflight.'
            , 'Diameter dimension uses floating-point coordinates; replaced exact '
            'equality with a 1e-9 mm tolerance in verification.'
        ],
        'before_sha256': hashlib.sha256(original).hexdigest(),
        'after_sha256': hashlib.sha256(candidate).hexdigest(),
        'limitations': 'Text bounds use font metrics; final CAD rendering depends on font availability. Existing customer logo overlap is preserved.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
