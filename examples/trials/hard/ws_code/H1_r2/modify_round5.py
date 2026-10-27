"""Round 5: change title REV and append one revision note, preserving other bytes."""
from pathlib import Path
from io import StringIO
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector, TagWriter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round5.before.dxf'
CANDIDATE = ROOT / 'part.round5.candidate.dxf'
REPORT = ROOT / 'round5_check.json'
NOTE = 'REV C: 宽度 150，增加中心孔 Ø30'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parse(data):
    lines = data.splitlines(keepends=True)
    require(len(lines) % 2 == 0, 'Invalid DXF pair count')
    codes = [int(lines[i].strip()) for i in range(0, len(lines), 2)]
    starts = [i for i, code in enumerate(codes) if code == 0] + [len(codes)]
    records = {}
    for start, end in zip(starts, starts[1:]):
        if lines[2*start+1].strip() in (b'SECTION', b'ENDSEC', b'EOF'):
            continue
        handles = [lines[2*i+1].strip().decode('ascii')
                   for i in range(start, end) if codes[i] in (5, 105)]
        if handles:
            require(len(handles) == 1 and handles[0] not in records,
                    'Duplicate record handles')
            records[handles[0]] = (start, end)
    return lines, codes, records


def raw_record(parsed, handle):
    lines, _, records = parsed
    start, end = records[handle]
    return b''.join(lines[2*start:2*end])


def tags(entity):
    exported = list(TagCollector.dxftags(entity))
    # INSERT export includes attached ATTRIB/SEQEND records, checked separately.
    end = next((i for i, tag in enumerate(exported) if i and tag.code == 0), len(exported))
    return exported[:end]


def verify(path, original, revision_handle, new_handle, seed_line, rev_line,
           inserted_bytes, insertion_line):
    old = ezdxf.readfile(BACKUP)
    new = ezdxf.readfile(path)
    before_raw, after_raw = parse(original), parse(path.read_bytes())
    stored_before = set(before_raw[2]) & set(old.entitydb)
    stored_after = set(after_raw[2]) & set(new.entitydb)
    require(new.units == old.units == 4, 'Units must remain mm')
    # The reader synthesizes missing SEQENDs for existing arrow INSERTs. Their
    # in-memory handles depend on HANDSEED; compare all serialized entities.
    require(stored_after - stored_before == {new_handle},
            'Unexpected added entities')
    require(not stored_before - stored_after, 'Existing entities deleted')
    for drawing, stored in ((old, stored_before), (new, stored_after)):
        require(all(drawing.entitydb[h].dxftype() == 'SEQEND'
                    for h in set(drawing.entitydb) - stored),
                'Unexpected unserialized entities')
    changed = {h for h in stored_before if tags(old.entitydb[h]) != tags(new.entitydb[h])}
    require(changed == {revision_handle}, f'Unexpected existing entity edits: {changed}')
    expected = old.entitydb[revision_handle].copy()
    expected.dxf.handle = revision_handle
    expected.dxf.owner = old.entitydb[revision_handle].dxf.owner
    expected.dxf.text = 'C'
    require(tags(expected) == tags(new.entitydb[revision_handle]),
            'REV contains other changes')
    titles = [e for e in new.modelspace().query('INSERT') if e.dxf.name == 'TB']
    require(len(titles) == 1 and titles[0].get_attrib_text('REV') == 'C',
            'Title block REV mismatch')
    note = new.entitydb[new_handle]
    require(note.dxftype() == 'TEXT' and note.dxf.text == NOTE,
            'Revision text mismatch')
    require(note.dxf.insert.isclose((0, -24, 0)) and note.dxf.height == 3.5
            and note.dxf.layer == 'NOTES' and note.dxf.style == 'Standard'
            and note.dxf.rotation == 0, 'Revision text placement mismatch')
    require(sum(e.dxftype() == 'TEXT' and e.dxf.text == NOTE
                for e in new.modelspace()) == 1, 'Duplicate revision note')
    note_box = bbox.extents([note])
    # Reserve one full em per character, wider than the measured fallback box.
    envelope = (0, -26, len(NOTE)*3.5, -19.5)
    require(note_box.extmin.x >= envelope[0] and note_box.extmax.x <= envelope[2]
            and note_box.extmin.y >= envelope[1] and note_box.extmax.y <= envelope[3],
            'Text exceeds reserved placement envelope')
    for entity in new.modelspace():
        if entity.dxf.handle == new_handle:
            continue
        b = bbox.extents([entity])
        if b.has_data:
            overlaps = (envelope[0] < b.extmax.x and envelope[2] > b.extmin.x
                        and envelope[1] < b.extmax.y and envelope[3] > b.extmin.y)
            require(not overlaps, f'Revision envelope intersects {entity.dxf.handle}')

    for handle in before_raw[2]:
        if handle != revision_handle:
            require(raw_record(before_raw, handle) == raw_record(after_raw, handle),
                    f'Existing raw entity changed: {handle}')
    # Reverse only the approved edits and new handle seed; every other byte must match.
    restored = path.read_bytes().splitlines(keepends=True)
    insertion_lines = len(inserted_bytes.splitlines(keepends=True))
    require(b''.join(restored[insertion_line:insertion_line+insertion_lines])
            == inserted_bytes, 'Inserted entity serialization differs')
    del restored[insertion_line:insertion_line+insertion_lines]
    restored[seed_line] = before_raw[0][seed_line]
    restored[rev_line] = before_raw[0][rev_line]
    require(b''.join(restored) == original, 'Unapproved DXF bytes changed')

    plate = bbox.extents([new.entitydb['91']])
    require(math.isclose(plate.size.x, 150) and math.isclose(plate.size.y, 80),
            'Plate dimensions changed')
    require(new.entitydb['FF'].dxf.center.isclose((75, 40, 0))
            and new.entitydb['FF'].dxf.radius == 15, 'Center hole changed')
    require(all(new.entitydb[h].dxf.radius == 5 for h in ('92', '93', '94', '95')),
            'Mounting holes changed')
    require(math.isclose(new.entitydb['96'].get_measurement(), 150)
            and math.isclose(new.entitydb['100'].get_measurement(), 30),
            'Dimension measurements changed')
    audit = new.audit()
    require(not audit.errors and not audit.fixes, 'DXF audit errors or fixes')
    return {
        'file': 'part.dxf', 'ezdxf_version': ezdxf.__version__, 'units': 'mm',
        'title_block': 'TB', 'rev_before': old.entitydb[revision_handle].dxf.text,
        'rev_after': 'C', 'revision_attribute_handle': revision_handle,
        'revision_note': NOTE, 'note_handle': new_handle,
        'note_insert': list(note.dxf.insert), 'note_height': note.dxf.height,
        'note_bbox': [list(note_box.extmin), list(note_box.extmax)],
        'reserved_note_envelope': envelope, 'note_has_no_overlap': True,
        'plate_size': [plate.size.x, plate.size.y], 'center_hole_diameter': 30,
        'center_hole_center': list(new.entitydb['FF'].dxf.center),
        'mounting_hole_diameters': [10]*4,
        'existing_entities_modified': [revision_handle], 'entities_added': [new_handle],
        'all_other_bytes_unchanged': True,
        'header_change': '$HANDSEED advanced for the added text entity',
        'audit_errors': len(audit.errors), 'audit_fixes': len(audit.fixes),
        'source_sha256': hashlib.sha256(original).hexdigest(),
        'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'errors_and_resolution': [
            'Initial candidate check compared reader-generated SEQEND handles; '
            'corrected to compare serialized entities and all original bytes. '
            'Also handled DIMSTYLE group 105, HEADER HANDSEED, and nested INSERT/ATTRIB exports. '
            'The source was not replaced until the corrected checks passed.'
        ],
        'limitations': ['Existing customer logo overlap is preserved.',
                        'Actual Chinese glyph rendering depends on CAD font availability.'],
    }


def main():
    require(not REPORT.exists(), 'Round 5 already completed; refuse duplicate execution')
    original = SOURCE.read_bytes()
    if BACKUP.exists():
        require(BACKUP.read_bytes() == original and CANDIDATE.exists(),
                'Recovery requires unchanged source and matching backup/candidate')
    else:
        require(not CANDIDATE.exists(), 'Candidate exists without backup')
    doc = ezdxf.readfile(SOURCE)
    titles = [e for e in doc.modelspace().query('INSERT') if e.dxf.name == 'TB']
    require(len(titles) == 1, 'Expected exactly one title block TB')
    revision = titles[0].get_attrib('REV')
    require(revision is not None and revision.dxf.text == 'A', 'Unexpected REV baseline')
    revision.dxf.text = 'C'
    note = doc.modelspace().add_text(NOTE, dxfattribs={
        'insert': (0, -24, 0), 'height': 3.5, 'layer': 'NOTES', 'style': 'Standard',
    })
    lines, codes, records = parse(original)
    start, end = records[revision.dxf.handle]
    text_pairs = [i for i in range(start, end) if codes[i] == 1]
    require(len(text_pairs) == 1, 'Unexpected REV text structure')
    rev_line = 2*text_pairs[0]+1
    newline = b'\r\n' if lines[rev_line].endswith(b'\r\n') else b'\n'
    lines[rev_line] = revision.dxf.text.encode('utf-8') + newline
    seed_pairs = [i+1 for i, code in enumerate(codes)
                  if code == 9 and lines[2*i+1].strip() == b'$HANDSEED']
    require(len(seed_pairs) == 1 and codes[seed_pairs[0]] == 5, 'Missing handle seed')
    seed_line = 2*seed_pairs[0]+1
    lines[seed_line] = f'{int(note.dxf.handle, 16)+1:X}'.encode('ascii') + newline
    section = None
    insertion_line = None
    for i, code in enumerate(codes):
        value = lines[2*i+1].strip()
        if code == 0 and value == b'SECTION':
            section = lines[2*(i+1)+1].strip()
        elif code == 0 and value == b'ENDSEC' and section == b'ENTITIES':
            insertion_line = 2*i
            break
    require(insertion_line is not None, 'Missing ENTITIES section')
    stream = StringIO()
    note.export_dxf(TagWriter(stream, dxfversion=doc.dxfversion))
    inserted = stream.getvalue().replace('\n', newline.decode('ascii')).encode('utf-8')
    result = b''.join(lines[:insertion_line]) + inserted + b''.join(lines[insertion_line:])
    if CANDIDATE.exists():
        require(CANDIDATE.read_bytes() == result, 'Recovery candidate differs')
    if not BACKUP.exists():
        BACKUP.write_bytes(original)
    CANDIDATE.write_bytes(result)
    args = (original, revision.dxf.handle, note.dxf.handle, seed_line,
            rev_line, inserted, insertion_line)
    verify(CANDIDATE, *args)
    require(SOURCE.read_bytes() == original, 'Source changed during verification')
    CANDIDATE.replace(SOURCE)
    report = verify(SOURCE, *args)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (ROOT / 'round5_record.txt').write_text(
        '第5轮已完成，交付文件：part.dxf；单位 mm。\n'
        '仅将标题栏 TB 的 REV 属性从 A 改为 C；新增一行：'+NOTE+'。\n'
        '新增文字位于 (0,-24)，字高3.5，NOTES层、Standard字体；位于板下方尺寸线与技术要求之间。\n'
        '仅修改既有属性 F0、新增文字和推进句柄种子；其他所有原有DXF字节保持不变。\n'
        '板150×80，中心孔(75,40) Ø30，四个安装孔Ø10及所有原标注均保留。\n'
        '候选及最终文件均复读核对通过：无文字包围区重叠，审计错误0、修复0。\n'
        '检查脚本曾误判读取时补建的SEQEND、DIMSTYLE的105组码、头部HANDSEED及INSERT内嵌属性；已修正实体解析和比较，全部复查通过后才替换原图。\n'
        '原有客户标识重叠保留；中文字形显示依赖CAD字体支持。\n'
        '备份：part.round5.before.dxf；脚本：modify_round5.py；核对报告：round5_check.json。\n',
        encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
