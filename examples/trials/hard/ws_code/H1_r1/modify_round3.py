"""Add only a central 30 mm hole and a rendered diameter dimension.

Existing DXF entity records stay byte-identical. Only $HANDSEED and the
BLOCK_RECORD table count change, to register the new dimension graphics.
"""
from io import StringIO
from pathlib import Path
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round3.before.dxf'
TEMP = ROOT / 'part.round3.checked.dxf'
REPORT = ROOT / 'round3_check.json'


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


def raw(record):
    return b''.join(pair for _, _, pair in record)


def value(record, code):
    return next((v for c, v, _ in record if c == code), None)


def handle(record):
    if record[0][1] in (b'SECTION', b'ENDSEC', b'EOF'):
        return None
    return value(record, 5) or value(record, 105)


def near(a, b):
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


def set_value(record, index, new_value):
    code, _, pair = record[index]
    code_line, old_line = pair.splitlines(keepends=True)
    ending = b'\r\n' if old_line.endswith(b'\r\n') else b'\n'
    changed = list(record)
    changed[index] = (code, new_value, code_line + new_value + ending)
    return changed


def main():
    original = TARGET.read_bytes()
    assert not BACKUP.exists(), 'Round 3 backup already exists; inspect before rerunning'
    before = ezdxf.readfile(TARGET)
    doc = ezdxf.readfile(TARGET)
    assert doc.units == 4
    plate = doc.entitydb['91']
    assert plate.dxftype() == 'LWPOLYLINE' and plate.closed
    bounds = bbox.extents([plate])
    center = (bounds.extmin + bounds.extmax) / 2
    assert center.isclose((75, 40, 0))
    assert near(bounds.size.x, 150) and near(bounds.size.y, 80)
    holes_before = list(before.modelspace().query('CIRCLE[layer=="HOLES"]'))
    assert len(holes_before) == 4 and all(near(e.dxf.radius, 6) for e in holes_before)

    hole = doc.modelspace().add_circle(center, 15, dxfattribs={'layer': 'HOLES'})
    dim = doc.modelspace().add_diameter_dim(
        center=center, radius=15, location=(104, 60), dimstyle='EZDXF',
        override={'dimtoh': 1, 'dimtmove': 1}, dxfattribs={'layer': 'DIM'},
    )
    dim.render()
    dimension = dim.dimension
    block = doc.blocks[dimension.dxf.geometry]
    allowed = {e.dxf.handle.encode('ascii') for e in (
        hole, dimension, block.block_record, block.block, block.endblk, *block
    )}

    stream = StringIO()
    doc.write(stream)
    exported = records(stream.getvalue().encode(doc.output_encoding, errors='dxfreplace'))
    source = records(original)
    existing = {handle(r) for r in source if handle(r)}
    assert not (existing & allowed)
    generated = {handle(r): r for r in exported if handle(r) in allowed}
    assert generated.keys() == allowed
    newline = b'\r\n' if b'\r\n' in original else b'\n'

    def export_raw(record):
        return raw(record).replace(b'\r\n', b'\n').replace(b'\n', newline)

    br_handle = block.block_record.dxf.handle.encode('ascii')
    table_additions = [generated[br_handle]]
    model_additions = [generated[e.dxf.handle.encode('ascii')] for e in (hole, dimension)]
    block_handles = [e.dxf.handle.encode('ascii') for e in (block.block, *block, block.endblk)]
    block_additions = [generated[h] for h in block_handles]

    # Retain original records verbatim, including title attributes, notes,
    # customer graphics, existing dimensions, tables, and drawing metadata.
    output, expected_old = [], []
    section, table = None, None
    metadata_changes = []
    seed = str(doc.header['$HANDSEED']).encode('ascii')
    for index, record in enumerate(source):
        kind = record[0][1]
        if kind == b'SECTION':
            section = value(record, 2)
        if kind == b'TABLE':
            table = value(record, 2)
        changed = record
        if section == b'HEADER' and kind == b'SECTION':
            j = next(i + 1 for i, (c, v, _) in enumerate(record)
                     if c == 9 and v == b'$HANDSEED')
            assert record[j][0] == 5
            changed = set_value(record, j, seed)
            metadata_changes.append('$HANDSEED')
        if section == b'TABLES' and kind == b'TABLE' and table == b'BLOCK_RECORD':
            j = next(i for i, (c, _, _) in enumerate(record) if c == 70)
            count = int(record[j][1])
            assert count == len(before.block_records)
            changed = set_value(record, j, str(count + 1).encode('ascii'))
            metadata_changes.append('BLOCK_RECORD count')
        if section == b'TABLES' and table == b'BLOCK_RECORD' and kind == b'ENDTAB':
            output.extend(export_raw(r) for r in table_additions)
        if kind == b'ENDSEC' and section == b'BLOCKS':
            output.extend(export_raw(r) for r in block_additions)
        if kind == b'ENDSEC' and section == b'ENTITIES':
            output.extend(export_raw(r) for r in model_additions)
        output.append(raw(changed))
        expected_old.append(raw(changed))
        if kind == b'ENDTAB':
            table = None
        if kind == b'ENDSEC':
            section = None
    assert metadata_changes == ['$HANDSEED', 'BLOCK_RECORD count']
    candidate = b''.join(output)
    parsed = records(candidate)
    assert [raw(r) for r in parsed if handle(r) not in allowed] == expected_old
    assert len(parsed) == len(source) + len(allowed)
    assert len({handle(r) for r in parsed if handle(r)}) == len([
        r for r in parsed if handle(r)
    ]), 'Duplicate handles'
    original_entities = {handle(r): raw(r) for r in source if handle(r)}
    final_entities = {handle(r): raw(r) for r in parsed if handle(r)}
    for h, entity_bytes in original_entities.items():
        if entity_bytes != final_entities[h]:
            # The table header is the sole existing handle-bearing record changed.
            assert h == before.block_records.head.dxf.handle.encode('ascii')

    def verify(path):
        checked = ezdxf.readfile(path)
        assert checked.units == 4
        assert len(checked.modelspace()) == len(before.modelspace()) + 2 == 17
        assert [e.dxf.handle for e in checked.modelspace()][:-2] == [
            e.dxf.handle for e in before.modelspace()
        ]
        new_hole = checked.entitydb[hole.dxf.handle]
        assert new_hole.dxf.center.isclose(center)
        assert near(new_hole.dxf.radius * 2, 30)
        assert new_hole.dxf.layer == 'HOLES'
        new_dim = checked.entitydb[dimension.dxf.handle]
        assert new_dim.dimtype == 3 and near(new_dim.get_measurement(), 30)
        assert new_dim.dxf.dimstyle == 'EZDXF' and new_dim.dxf.layer == 'DIM'
        assert ((new_dim.dxf.defpoint + new_dim.dxf.defpoint4) / 2).isclose(center)
        for point in (new_dim.dxf.defpoint, new_dim.dxf.defpoint4):
            assert near((point - center).magnitude, 15)
        geometry = checked.blocks[new_dim.dxf.geometry]
        text = list(geometry.query('MTEXT'))
        assert len(text) == 1 and text[0].text == '%%c30'
        assert near(text[0].dxf.char_height, 3.5)
        assert len(geometry.query('LINE')) == 3, 'Leader and landing must be visible'
        arrow = list(geometry.query('INSERT'))
        assert len(arrow) == 1
        assert near((arrow[0].dxf.insert - center).magnitude, 15)
        for h in ('92', '93', '94', '95'):
            assert near(checked.entitydb[h].dxf.radius, 6)
            assert checked.entitydb[h].dxf.center == before.entitydb[h].dxf.center
        assert near(checked.entitydb['96'].get_measurement(), 150)
        assert near(checked.entitydb['A5'].get_measurement(), 80)
        assert near(checked.entitydb['D2'].get_measurement(), 12)
        ext = bbox.extents([e for e in geometry if e.dxftype() != 'POINT'])
        assert 55 < ext.extmin.x < ext.extmax.x < 125
        assert 20 < ext.extmin.y < ext.extmax.y < 70
        assert checked.entitydb['91'].closed
        assert list(checked.entitydb['91'].get_points()) == list(plate.get_points())
        # Loading synthesizes in-memory SEQENDs for INSERTs. HANDSEED must
        # exceed the handles persisted on disk, not those transient objects.
        assert int(checked.header['$HANDSEED'], 16) > max(
            int(handle(r), 16) for r in records(path.read_bytes()) if handle(r)
        )
        audit = checked.audit()
        assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
        return ext

    TEMP.write_bytes(candidate)
    ext = verify(TEMP)
    BACKUP.write_bytes(original)
    TARGET.write_bytes(candidate)
    verify(TARGET)
    assert TARGET.read_bytes() == candidate and BACKUP.read_bytes() == original
    TEMP.unlink()
    report = {
        'drawing': TARGET.name, 'backup': BACKUP.name, 'units': 'mm',
        'plate_size_mm': [150, 80], 'new_hole_center_mm': list(center),
        'new_hole_diameter_mm': 30, 'diameter_dimension_measurement_mm': 30,
        'diameter_dimension_display': '%%c30',
        'new_hole_handle': hole.dxf.handle, 'new_dimension_handle': dimension.dxf.handle,
        'new_dimension_graphics_block': dimension.dxf.geometry,
        'new_annotation_bounds_mm': [list(ext.extmin), list(ext.extmax)],
        'existing_four_holes_diameter_mm': 12,
        'existing_entity_records_byte_identical': True,
        'all_other_original_records_byte_identical_except': metadata_changes,
        'added_modelspace_entities': 2, 'modelspace_entity_count': 17,
        'audit_errors': 0, 'audit_fixes': 0,
        'errors_encountered': [{
            'error': 'Initial HANDSEED check included reader-generated in-memory SEQENDs.',
            'resolution': 'Check HANDSEED against persisted DXF record handles instead.',
        }],
        'before_sha256': hashlib.sha256(original).hexdigest(),
        'after_sha256': hashlib.sha256(candidate).hexdigest(),
        'layout_note': 'Existing customer logo overlap from earlier rounds is unchanged.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
