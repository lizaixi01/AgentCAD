"""Undo exactly round 2, retaining round 1, round 3 and unrelated DXF bytes."""
from pathlib import Path
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round4.before.dxf'
CANDIDATE = ROOT / 'part.round4.candidate.dxf'
HOLES = ('92', '93', '94', '95')
ATTRS = {
    **{h: ('radius',) for h in HOLES},
    'D2': ('defpoint', 'defpoint4'),
    'D6': ('insert',), 'D8': ('insert',),
    'DA': ('start', 'end'), 'DB': ('start',),
    'DD': (), 'DF': ('location',),
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def tags(entity):
    return list(TagCollector.dxftags(entity))


def records(data):
    lines = data.splitlines(keepends=True)
    require(len(lines) % 2 == 0, 'Invalid DXF pairs')
    codes = [int(lines[i].strip()) for i in range(0, len(lines), 2)]
    starts = [i for i, code in enumerate(codes) if code == 0] + [len(codes)]
    result = {}
    for start, end in zip(starts, starts[1:]):
        handles = [lines[2*i+1].strip().decode('ascii')
                   for i in range(start, end) if codes[i] == 5]
        if handles:
            require(len(handles) == 1 and handles[0] not in result,
                    'Unexpected handle structure')
            result[handles[0]] = (start, end)
    return lines, codes, result


def record_bytes(parsed, handle):
    lines, _, recs = parsed
    start, end = recs[handle]
    return b''.join(lines[2*start:2*end])


def verify(path, baseline, expected_indices):
    before = ezdxf.readfile(BACKUP)
    after = ezdxf.readfile(path)
    require(after.units == before.units == 4, 'Units changed')
    require(set(before.entitydb) == set(after.entitydb), 'Entity set changed')
    changed = {h for h in before.entitydb
               if tags(before.entitydb[h]) != tags(after.entitydb[h])}
    require(changed == set(ATTRS), f'Unexpected entity edits: {changed}')
    for handle in changed:
        require(tags(after.entitydb[handle]) == tags(baseline.entitydb[handle]),
                f'Round 2 state not fully restored: {handle}')
    old = records(BACKUP.read_bytes())
    new = records(path.read_bytes())
    baseline_raw = records((ROOT / 'part.round2.before.dxf').read_bytes())
    require(old[1:] == new[1:], 'Raw DXF structure changed')
    actual = {i for i, (a, b) in enumerate(zip(old[0], new[0])) if a != b}
    require(actual == expected_indices and len(actual) == 21,
            'Unexpected byte edits')
    require(len(old[0]) == len(new[0]), 'Line count changed')
    for handle in new[2]:
        reference = baseline_raw if handle in ATTRS else old
        require(record_bytes(new, handle) == record_bytes(reference, handle),
                f'Unexpected raw record: {handle}')

    centers = [(12, 12, 0), (138, 12, 0), (12, 68, 0), (138, 68, 0)]
    for handle, center in zip(HOLES, centers):
        hole = after.entitydb[handle]
        require(hole.dxftype() == 'CIRCLE' and hole.dxf.radius == 5
                and hole.dxf.center.isclose(center), 'Mounting hole mismatch')
    require(len(after.modelspace().query('CIRCLE[layer=="HOLES"]')) == 5,
            'Hole count changed')
    dim = after.entitydb['D2']
    require(math.isclose(dim.get_measurement(), 10, abs_tol=1e-10),
            'Diameter measurement mismatch')
    require(after.entitydb['DD'].text == '4X %%c10', 'Display mismatch')
    center = after.entitydb['95'].dxf.center
    for point in (dim.dxf.defpoint, dim.dxf.defpoint4):
        require(math.isclose((point-center).magnitude, 5, abs_tol=1e-10),
                'Diameter endpoint detached')
    require(after.entitydb['D6'].dxf.insert == dim.dxf.defpoint4
            and after.entitydb['D8'].dxf.insert == dim.dxf.defpoint,
            'Arrows detached')
    plate = after.entitydb['91']
    bounds = bbox.extents([plate])
    require(math.isclose(bounds.size.x, 150) and math.isclose(bounds.size.y, 80),
            'Round 1 plate size lost')
    radii = []
    points = list(plate.get_points())
    for i, point in enumerate(points):
        bulge = point[4]
        if bulge:
            next_point = points[(i+1) % len(points)]
            chord = math.hypot(next_point[0]-point[0], next_point[1]-point[1])
            radii.append(chord*(1+bulge*bulge)/(4*abs(bulge)))
    require(len(radii) == 4 and all(math.isclose(r, 5) for r in radii),
            'Corner radius mismatch')
    require(math.isclose(after.entitydb['96'].get_measurement(), 150)
            and after.entitydb['A1'].text == '150', 'Width dimension mismatch')
    require(after.entitydb['FF'].dxf.center.isclose((75, 40, 0))
            and after.entitydb['FF'].dxf.radius == 15, 'Round 3 hole lost')
    central_dim = after.entitydb['100']
    require(math.isclose(central_dim.get_measurement(), 30),
            'Round 3 dimension changed')
    center_text = [e.text for e in after.blocks[central_dim.dxf.geometry]
                   if e.dxftype() == 'MTEXT']
    require(center_text == ['%%c30'], 'Round 3 display mismatch')
    audit = after.audit()
    require(not audit.errors and not audit.fixes, 'DXF audit failed')
    return {
        'file': 'part.dxf', 'ezdxf_version': ezdxf.__version__, 'units': 'mm',
        'mounting_hole_centers': centers, 'mounting_hole_diameters': [10]*4,
        'diameter_dimension_measurement': dim.get_measurement(),
        'diameter_dimension_display': after.entitydb['DD'].text,
        'restored_records_exactly_match_round2_before': True,
        'diameter_endpoints_and_arrows_on_circle': True,
        'plate_size': [bounds.size.x, bounds.size.y], 'corner_radii': radii,
        'width_dimension': after.entitydb['96'].get_measurement(),
        'center_hole_center': list(after.entitydb['FF'].dxf.center),
        'center_hole_diameter': 30, 'center_dimension_raw_text': center_text[0],
        'center_dimension_display': 'Ø30',
        'round1_and_round3_preserved': True,
        'modified_entity_handles': sorted(changed), 'modified_tag_values': len(actual),
        'all_other_bytes_unchanged': True,
        'audit_errors': len(audit.errors), 'audit_fixes': len(audit.fixes),
        'source_sha256': hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
        'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'errors_and_resolution': [
            'PowerShell displayed old UTF-8 records incorrectly; explicit UTF-8 reading resolved it. No drawing data was affected.',
            'Candidate verification expected literal Ø30 but the preserved DXF text is %%c30. Corrected the assertion and reverified before replacing part.dxf.'
        ],
        'limitation': 'Existing overlap with customer logo remains unchanged.',
    }


def main():
    original = SOURCE.read_bytes()
    require(not (ROOT / 'round4_check.json').exists(),
            'Round 4 already completed; refuse repeated execution')
    if BACKUP.exists():
        require(BACKUP.read_bytes() == original and CANDIDATE.exists(),
                'Recovery requires unchanged source, backup and candidate')
    else:
        require(not CANDIDATE.exists(), 'Candidate exists without backup')
    baseline_data = (ROOT / 'part.round2.before.dxf').read_bytes()
    post_round2_data = (ROOT / 'part.round3.before.dxf').read_bytes()
    base_raw, post_raw, current_raw = map(records, (baseline_data, post_round2_data, original))
    require(base_raw[1:] == post_raw[1:], 'Historical round 2 structure mismatch')
    historical_changes = {h for h in base_raw[2]
                          if record_bytes(base_raw, h) != record_bytes(post_raw, h)}
    require(historical_changes == set(ATTRS), 'Unexpected round 2 changes')
    baseline = ezdxf.readfile(ROOT / 'part.round2.before.dxf')
    current = ezdxf.readfile(SOURCE)
    expected_lines = set()
    lines, codes, recs = current_raw
    for handle, attributes in ATTRS.items():
        require(record_bytes(current_raw, handle) == record_bytes(post_raw, handle),
                f'Later edit conflicts with round 2 rollback: {handle}')
        previous = tags(current.entitydb[handle])
        for name in attributes:
            setattr(current.entitydb[handle].dxf, name,
                    getattr(baseline.entitydb[handle].dxf, name))
        if handle == 'DD':
            current.entitydb[handle].text = baseline.entitydb[handle].text
        restored = tags(current.entitydb[handle])
        require(restored == tags(baseline.entitydb[handle]), 'Incomplete ezdxf restore')
        start, end = recs[handle]
        ref_start, ref_end = base_raw[2][handle]
        require(codes[start:end] == [t.code for t in previous]
                and end-start == ref_end-ref_start, 'Tag structure mismatch')
        for offset, (old_tag, new_tag) in enumerate(zip(previous, restored)):
            require(old_tag.code == new_tag.code, 'Tag code changed')
            if old_tag.value != new_tag.value:
                index = 2*(start+offset)+1
                # Restore the exact historical serialization. All other bytes,
                # including round 3 additions, remain untouched.
                lines[index] = base_raw[0][2*(ref_start+offset)+1]
                expected_lines.add(index)
    require(len(expected_lines) == 21, 'Expected exactly 21 inverse tag edits')
    candidate_data = b''.join(lines)
    if CANDIDATE.exists():
        require(CANDIDATE.read_bytes() == candidate_data, 'Recovery candidate differs')
    if not BACKUP.exists():
        BACKUP.write_bytes(original)
    CANDIDATE.write_bytes(candidate_data)
    verify(CANDIDATE, baseline, expected_lines)
    CANDIDATE.replace(SOURCE)
    report = verify(SOURCE, baseline, expected_lines)
    (ROOT / 'round4_check.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (ROOT / 'round4_record.txt').write_text(
        '第4轮：仅撤回第2轮的四个安装孔及其孔径标注修改。\n'
        '当前有效图纸：part.dxf；单位mm；本轮前备份：part.round4.before.dxf。\n'
        '依据part.round2.before.dxf恢复四孔Ø10（半径5），孔心保持'
        '(12,12)、(138,12)、(12,68)、(138,68)。\n'
        '直径标注D2实测10，*D5显示4X %%c10；定义点、箭头及引线均精确恢复。\n'
        '第1轮板宽150、高80、R5及右侧孔位保留；第3轮中心(75,40)Ø30孔'
        '（FF）及其标注（100、*D6）逐字节保留。\n'
        '仅修改11个实体中的21个DXF值行，全部等同第2轮前的对应记录；'
        '其余字节完全不变，包括标题栏、技术要求及客户标识。\n'
        '候选及最终图纸均经ezdxf复读检查，审计错误0、修复0。\n'
        '首次候选检查误将中心孔显示文本按字面Ø30判断；实际DXF编码为%%c30，'
        '已修正断言后重新检查通过，原标注未修改。\n'
        '首次PowerShell显示旧记录有乱码，显式UTF-8读取后正常，原文件未改动。\n'
        '既有客户标识重叠仍保留，本轮未擅自调整。\n'
        '脚本modify_round4.py防重复执行；核对报告round4_check.json。\n',
        encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
