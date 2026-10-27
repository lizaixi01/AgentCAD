"""Change only the four mounting hole diameters and their diameter annotation."""
from pathlib import Path
import hashlib
import json
import math

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round2.before.dxf'
CANDIDATE = ROOT / 'part.round2.candidate.dxf'
HOLES = ('92', '93', '94', '95')
ALLOWED = {
    **{h: {'radius'} for h in HOLES},
    'D2': {'defpoint', 'defpoint4'},
    'D6': {'insert'},
    'D8': {'insert'},
    'DA': {'start', 'end'},
    'DB': {'start'},
    'DD': set(),  # MTEXT content is stored outside dxfattribs().
    'DF': {'location'},
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def tags(entity):
    return list(TagCollector.dxftags(entity))


def raw_records(data):
    lines = data.splitlines(keepends=True)
    require(len(lines) % 2 == 0, 'Invalid DXF code/value pairs')
    codes = [int(lines[i].strip()) for i in range(0, len(lines), 2)]
    starts = [i for i, code in enumerate(codes) if code == 0] + [len(codes)]
    records = {}
    for start, end in zip(starts, starts[1:]):
        handles = [lines[2*i+1].strip().decode('ascii')
                   for i in range(start, end) if codes[i] == 5]
        if handles:
            require(len(handles) == 1 and handles[0] not in records,
                    'Unexpected DXF handle layout')
            records[handles[0]] = (start, end)
    return lines, codes, records


def verify(path, original, expected_line_changes):
    before = ezdxf.readfile(original)
    after = ezdxf.readfile(path)
    require(after.units == before.units == 4, 'Units must remain mm')
    require(set(before.entitydb) == set(after.entitydb), 'Entity set changed')
    changed = {h for h in before.entitydb
               if tags(before.entitydb[h]) != tags(after.entitydb[h])}
    require(changed == set(ALLOWED), f'Unexpected changed entities: {changed}')
    for handle, attrs in ALLOWED.items():
        old = before.entitydb[handle].dxfattribs()
        new = after.entitydb[handle].dxfattribs()
        require(set(old) == set(new), f'Attribute set changed: {handle}')
        changed_attrs = {key for key in old if old[key] != new[key]}
        require(changed_attrs == attrs, f'Unexpected attribute edits: {handle}')

    old_lines, old_codes, old_records = raw_records(original.read_bytes())
    new_lines, new_codes, new_records = raw_records(path.read_bytes())
    require(old_codes == new_codes and old_records == new_records,
            'DXF record structure changed')
    require(len(old_lines) == len(new_lines), 'DXF line count changed')
    actual_lines = {i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b}
    require(actual_lines == set(expected_line_changes), 'Unexpected byte changes')
    # All lines except the explicit edited tag values must be byte-identical,
    # including header, title block, client logo, notes and unused definitions.
    for i in range(len(old_lines)):
        if i not in expected_line_changes:
            require(old_lines[i] == new_lines[i], f'Unrelated bytes changed: {i}')

    centers = []
    for handle in HOLES:
        hole = after.entitydb[handle]
        require(hole.dxf.center == before.entitydb[handle].dxf.center,
                f'Hole center moved: {handle}')
        require(hole.dxf.radius == 6, f'Hole diameter is not 12: {handle}')
        centers.append(list(hole.dxf.center))
    dim = after.entitydb['D2']
    center = after.entitydb['95'].dxf.center
    require(dim.dxf.dimtype & 15 == 3, 'Expected diameter dimension')
    require(math.isclose(dim.get_measurement(), 12, abs_tol=1e-10),
            'Diameter dimension does not measure 12')
    require(((dim.dxf.defpoint + dim.dxf.defpoint4) * 0.5).isclose(center),
            'Diameter dimension center moved')
    direction = (before.entitydb['D2'].dxf.defpoint - center).normalize()
    require((dim.dxf.defpoint - center).normalize().isclose(direction),
            'Diameter annotation angle changed')
    for point in (dim.dxf.defpoint, dim.dxf.defpoint4):
        require(math.isclose((point - center).magnitude, 6, abs_tol=1e-10),
                'Dimension endpoint is not on circle')
    require(after.entitydb['D6'].dxf.insert == dim.dxf.defpoint4,
            'First arrow detached')
    require(after.entitydb['D8'].dxf.insert == dim.dxf.defpoint,
            'Second arrow detached')
    require(after.entitydb['DF'].dxf.location == dim.dxf.defpoint4,
            'Definition point detached')
    arrow_offset = direction * 2.5
    require(after.entitydb['DA'].dxf.start.isclose(dim.dxf.defpoint4 - arrow_offset),
            'Diameter line start does not match arrow base')
    require(after.entitydb['DA'].dxf.end.isclose(dim.dxf.defpoint - arrow_offset),
            'Diameter line end does not match arrow base')
    require(after.entitydb['DB'].dxf.start == after.entitydb['DA'].dxf.start,
            'Leader is disconnected')
    require(after.entitydb['DB'].dxf.end == after.entitydb['DC'].dxf.start,
            'Text leader is disconnected')
    require(dim.dxf.text == before.entitydb['D2'].dxf.text == '4X <>',
            'Dimension override changed')
    require(after.entitydb['DD'].text == '4X %%c12', 'Rendered diameter label stale')
    require(after.entitydb['DD'].dxf.insert == before.entitydb['DD'].dxf.insert,
            'Diameter text position changed')
    plate = after.entitydb['91']
    bounds = bbox.extents([plate])
    require(math.isclose(bounds.size.x, 150) and math.isclose(bounds.size.y, 80),
            'Plate envelope changed')
    require(math.isclose(after.entitydb['96'].get_measurement(), 150),
            'Width dimension changed')
    require(after.entitydb['A1'].text == '150', 'Displayed width changed')
    audit = after.audit()
    require(not audit.errors and not audit.fixes,
            f'Audit failed: {audit.errors}, {audit.fixes}')
    return {
        'file': 'part.dxf', 'ezdxf_version': ezdxf.__version__, 'units': 'mm',
        'hole_centers': centers, 'hole_diameters': [12.0] * 4,
        'diameter_dimension_measurement': dim.get_measurement(),
        'diameter_dimension_display': after.entitydb['DD'].text,
        'diameter_dimension_points_and_arrows_on_circle': True,
        'diameter_text_position_unchanged': True,
        'plate_width': bounds.size.x, 'plate_height': bounds.size.y,
        'width_dimension_measurement': after.entitydb['96'].get_measurement(),
        'modified_entity_handles': sorted(changed),
        'modified_tag_values': len(actual_lines),
        'all_other_bytes_unchanged': True,
        'audit_errors': len(audit.errors), 'audit_fixes': len(audit.fixes),
        'source_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'limitation': 'Existing overlap with client logo remains unchanged.',
    }


def main():
    require(not BACKUP.exists() and not CANDIDATE.exists(),
            'Round 2 output exists; refuse to repeat modification')
    original = SOURCE.read_bytes()
    doc = ezdxf.readfile(SOURCE)
    require(doc.units == 4, 'Expected mm units')
    for handle in HOLES:
        e = doc.entitydb[handle]
        require(e.dxftype() == 'CIRCLE' and e.dxf.layer == 'HOLES'
                and e.dxf.radius == 5, f'Unexpected original hole: {handle}')
    require({e.dxf.handle for e in doc.modelspace().query('CIRCLE[layer=="HOLES"]')}
            == set(HOLES), 'Unexpected mounting hole count')
    dim = doc.entitydb['D2']
    require(dim.dxf.geometry == '*D5' and math.isclose(dim.get_measurement(), 10),
            'Unexpected original diameter annotation')
    require(doc.entitydb['DD'].text == '4X %%c10', 'Unexpected diameter text')
    old_tags = {h: tags(doc.entitydb[h]) for h in ALLOWED}
    center = doc.entitydb['95'].dxf.center
    delta = (dim.dxf.defpoint - center).normalize()  # One mm radial increase.
    for handle in HOLES:
        doc.entitydb[handle].dxf.radius = 6
    dim.dxf.defpoint += delta
    dim.dxf.defpoint4 -= delta
    doc.entitydb['D6'].dxf.insert -= delta
    doc.entitydb['D8'].dxf.insert += delta
    doc.entitydb['DA'].dxf.start -= delta
    doc.entitydb['DA'].dxf.end += delta
    doc.entitydb['DB'].dxf.start -= delta
    doc.entitydb['DF'].dxf.location -= delta
    doc.entitydb['DD'].text = '4X %%c12'

    # Use ezdxf for the edits and serialization, replacing only changed tag
    # values to preserve every unrelated byte, including opaque custom data.
    lines, codes, records = raw_records(original)
    changed_lines = set()
    for handle in ALLOWED:
        previous, current = old_tags[handle], tags(doc.entitydb[handle])
        require(len(previous) == len(current), f'Tag count changed: {handle}')
        start, end = records[handle]
        require(codes[start:end] == [t.code for t in previous],
                f'Raw/exported tag mismatch: {handle}')
        for offset, (a, b) in enumerate(zip(previous, current)):
            require(a.code == b.code, f'Tag code changed: {handle}')
            if a.value != b.value:
                index = 2 * (start + offset) + 1
                ending = b'\r\n' if lines[index].endswith(b'\r\n') else b'\n'
                lines[index] = str(b.value).encode('utf-8') + ending
                changed_lines.add(index)
    BACKUP.write_bytes(original)
    CANDIDATE.write_bytes(b''.join(lines))
    verify(CANDIDATE, BACKUP, changed_lines)
    CANDIDATE.replace(SOURCE)
    report = verify(SOURCE, BACKUP, changed_lines)
    (ROOT / 'round2_check.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'round2_record.txt').write_text(
        '第2轮修改记录（后续会话请先读取）\n'
        '当前有效图纸：part.dxf；单位mm。备份：part.round2.before.dxf。\n'
        '四孔直径10改为12，半径6；孔心(12,12)、(138,12)、(12,68)、(138,68)不变。\n'
        '直径尺寸D2实测12；显示块*D5文字改为4X %%c12，定义点、箭头及相接线同步更新。\n'
        '标注文字位置不变；板150×80、R5和其余尺寸不变。\n'
        f'仅修改{len(ALLOWED)}个实体中的{len(changed_lines)}个DXF值行，其他字节全部不变。\n'
        '标题栏、技术要求、客户标识保持原样；上轮已存在的客户标识重叠仍保留。\n'
        '候选文件及最终文件均复读检查通过；ezdxf审计错误0、修复0。运行无错误。\n'
        '脚本modify_round2.py有防重复执行保护，不要再次运行；核对报告round2_check.json。\n',
        encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
