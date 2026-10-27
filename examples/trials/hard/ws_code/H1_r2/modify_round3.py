"""Add the central hole and its native diameter dimension, preserving old DXF bytes."""
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
BACKUP = ROOT / 'part.round3.before.dxf'
CANDIDATE = ROOT / 'part.round3.candidate.dxf'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def pairs(data):
    lines = data.splitlines(keepends=True)
    require(len(lines) % 2 == 0, 'Incomplete DXF tag pair')
    return [(int(lines[i].strip()), lines[i+1].strip(),
             lines[i] + lines[i+1]) for i in range(0, len(lines), 2)]


def records(data):
    tags = pairs(data)
    starts = [i for i, tag in enumerate(tags) if tag[0] == 0] + [len(tags)]
    result = []
    for start, end in zip(starts, starts[1:]):
        group = tags[start:end]
        kind = group[0][1]
        handle_codes = (105,) if kind == b'DIMSTYLE' else (5,)
        handles = [t[1].decode('ascii') for t in group if t[0] in handle_codes]
        # HEADER contains $HANDSEED (group 5), which is not an entity handle.
        handle = handles[0] if handles and kind != b'SECTION' else None
        result.append((kind, handle, b''.join(t[2] for t in group)))
    return result


def export(callback, version, newline):
    stream = StringIO()
    callback(TagWriter(stream, dxfversion=version))
    return stream.getvalue().replace('\n', newline.decode('ascii')).encode('utf-8')


def metadata_indices(tags):
    seed = [i+1 for i, t in enumerate(tags)
            if t[0] == 9 and t[1] == b'$HANDSEED']
    table = [i for i, t in enumerate(tags)
             if t[0] == 2 and t[1] == b'BLOCK_RECORD']
    require(len(seed) == len(table) == 1, 'Ambiguous DXF metadata')
    end = next(i for i in range(table[0]+1, len(tags)) if tags[i][0] == 0)
    count = [i for i in range(table[0]+1, end) if tags[i][0] == 70]
    require(len(count) == 1, 'Missing block table counter')
    return seed[0], count[0]


def splice(original, block_record, block_definition, entities, seed, block_count):
    tags = pairs(original)
    seed_i, count_i = metadata_indices(tags)
    newline = b'\r\n' if tags[0][2].endswith(b'\r\n') else b'\n'
    replacements = {seed_i: seed.encode('ascii'), count_i: str(block_count).encode('ascii')}
    section = table = None
    out = []
    additions = 0
    for i, (code, value, raw) in enumerate(tags):
        if code == 0 and value == b'SECTION':
            section = tags[i+1][1]
        if code == 0 and value == b'TABLE':
            table = tags[i+1][1]
        if code == 0 and value == b'ENDTAB' and table == b'BLOCK_RECORD':
            out.append(block_record)
            additions += 1
        if code == 0 and value == b'ENDSEC' and section == b'BLOCKS':
            out.append(block_definition)
            additions += 1
        if code == 0 and value == b'ENDSEC' and section == b'ENTITIES':
            out.append(entities)
            additions += 1
        if i in replacements:
            code_line = raw.splitlines(keepends=True)[0]
            out.append(code_line + replacements[i] + newline)
        else:
            out.append(raw)
    require(additions == 3, 'Missing insertion position')
    return b''.join(out)


def verify(path, old_path, hole_handle, dim_handle, new_handles):
    original = old_path.read_bytes()
    result = path.read_bytes()
    old_records = records(original)
    old_handles = {h for _, h, _ in old_records if h}
    result_records = records(result)
    actual_new = {h for _, h, _ in result_records if h} - old_handles
    require(actual_new == new_handles, 'Unexpected added or missing records')
    # Remove only the newly serialized records, then restore the two metadata
    # values. The complete remaining file must match the original byte for byte.
    stripped = b''.join(raw for _, h, raw in result_records if h not in new_handles)
    original_tags = pairs(original)
    stripped_tags = pairs(stripped)
    oi = metadata_indices(original_tags)
    ni = metadata_indices(stripped_tags)
    require(oi == ni, 'Original record order changed')
    restored = b''.join(original_tags[i][2] if i in oi else t[2]
                        for i, t in enumerate(stripped_tags))
    require(restored == original, 'Original DXF content changed')

    before = ezdxf.readfile(old_path)
    after = ezdxf.readfile(path)
    require(before.units == after.units == 4, 'Units must be mm')
    for handle in old_handles:
        if before.entitydb.get(handle) is not None and handle != '9':
            require(list(TagCollector.dxftags(before.entitydb[handle])) ==
                    list(TagCollector.dxftags(after.entitydb[handle])),
                    f'Original entity changed: {handle}')
    old_model = [e.dxf.handle for e in before.modelspace()]
    new_model = [e.dxf.handle for e in after.modelspace()]
    require(new_model == old_model + [hole_handle, dim_handle],
            'Modelspace edits exceed the requested additions')
    plate_box = bbox.extents([after.entitydb['91']])
    center = (plate_box.extmin + plate_box.extmax) * 0.5
    require(center.isclose((75, 40, 0)), 'Unexpected plate center')
    require(plate_box.size.isclose((150, 80, 0)), 'Plate size changed')
    hole = after.entitydb[hole_handle]
    require(hole.dxftype() == 'CIRCLE' and hole.dxf.layer == 'HOLES', 'Invalid hole')
    require(hole.dxf.center.isclose(center) and hole.dxf.radius == 15,
            'Central hole is not centered or diameter is not 30')
    holes = list(after.modelspace().query('CIRCLE[layer=="HOLES"]'))
    require(len(holes) == 5, 'Incorrect hole count')
    for h in ('92', '93', '94', '95'):
        require(after.entitydb[h].dxf.radius == 6 and
                after.entitydb[h].dxf.center == before.entitydb[h].dxf.center,
                'Existing mounting hole changed')
    dim = after.entitydb[dim_handle]
    require(dim.dxf.dimtype & 15 == 3, 'Not a native diameter dimension')
    require(dim.dxf.layer == 'DIM' and dim.dxf.dimstyle == 'EZDXF',
            'Incorrect annotation layer/style')
    require(math.isclose(dim.get_measurement(), 30, abs_tol=1e-10), 'Wrong measurement')
    require(((dim.dxf.defpoint + dim.dxf.defpoint4) * 0.5).isclose(center),
            'Dimension is not centered on the new hole')
    for p in (dim.dxf.defpoint, dim.dxf.defpoint4):
        require(math.isclose((p-center).magnitude, 15, abs_tol=1e-10),
                'Dimension endpoint is not on the hole')
    graphics = after.blocks[dim.dxf.geometry]
    text = list(graphics.query('MTEXT'))
    require(len(text) == 1 and text[0].text == '%%c30' and dim.dxf.text == '<>',
            'Diameter symbol or displayed value incorrect')
    arrows = list(graphics.query('INSERT'))
    require(len(arrows) == 2 and all(math.isclose((a.dxf.insert-center).magnitude,
                                               15, abs_tol=1e-10) for a in arrows),
            'Dimension arrows detached from hole')
    dim_box = bbox.extents(graphics)
    require(0 < dim_box.extmin.x < dim_box.extmax.x < 150 and
            0 < dim_box.extmin.y < dim_box.extmax.y < 80,
            'New annotation falls outside the plate')
    for e in before.modelspace():
        if e.dxf.handle == '91':
            continue
        box = bbox.extents([e])
        if box.has_data:
            overlaps = (dim_box.extmin.x < box.extmax.x and dim_box.extmax.x > box.extmin.x
                        and dim_box.extmin.y < box.extmax.y and dim_box.extmax.y > box.extmin.y)
            require(not overlaps, f'New annotation overlaps existing entity {e.dxf.handle}')
    raw_tags = pairs(result)
    seed_i, count_i = metadata_indices(raw_tags)
    require(int(raw_tags[count_i][1]) == len(after.block_records), 'Incorrect block count')
    require(int(raw_tags[seed_i][1], 16) > max(int(h, 16) for h in actual_new),
            'HANDSEED is not beyond the new handles')
    audit = after.audit()
    require(not audit.errors and not audit.fixes, 'DXF audit reported errors or repairs')
    return {
        'file': 'part.dxf', 'units': 'mm', 'ezdxf_version': ezdxf.__version__,
        'plate_size': [plate_box.size.x, plate_box.size.y],
        'new_hole_center': list(hole.dxf.center), 'new_hole_diameter': hole.dxf.radius*2,
        'new_hole_handle': hole_handle, 'new_dimension_handle': dim_handle,
        'dimension_block': dim.dxf.geometry, 'dimension_measurement': dim.get_measurement(),
        'dimension_display': 'Ø30', 'dimension_endpoints_and_arrows_on_circle': True,
        'dimension_bounds': [list(dim_box.extmin), list(dim_box.extmax)],
        'new_annotation_overlaps_existing_content': False,
        'mounting_holes_unchanged': True, 'total_holes': len(holes),
        'added_raw_records': len(new_handles), 'added_record_handles': sorted(new_handles),
        'original_bytes_preserved_except_handseed_and_block_table_count': True,
        'audit_errors': len(audit.errors), 'audit_fixes': len(audit.fixes),
        'source_sha256': hashlib.sha256(original).hexdigest(),
        'result_sha256': hashlib.sha256(result).hexdigest(),
        'errors_and_resolution': ['A diagnostic text read used the Windows default GBK encoding; '
                                  'explicit UTF-8 fixed it. The DXF was unaffected.'],
        'limitation': 'Existing overlap with the client logo remains unchanged.',
    }


def main():
    require(not BACKUP.exists() and not CANDIDATE.exists(), 'Round 3 already started; do not repeat')
    original = SOURCE.read_bytes()
    doc = ezdxf.readfile(SOURCE)
    require(doc.units == 4, 'Expected millimeters')
    plate = bbox.extents([doc.entitydb['91']])
    center = (plate.extmin + plate.extmax) * 0.5
    require(center.isclose((75, 40, 0)), 'Unexpected plate geometry')
    require(not any(e.dxf.center.isclose(center) for e in doc.modelspace().query('CIRCLE')),
            'A central circle already exists')
    hole = doc.modelspace().add_circle(center, 15, dxfattribs={'layer': 'HOLES'})
    style = doc.modelspace().add_diameter_dim(
        center=center, radius=15, angle=45, dimstyle='EZDXF',
        override={'dimtoh': 1}, dxfattribs={'layer': 'DIM'})
    style.render()
    dim = style.dimension
    block = doc.blocks[dim.dxf.geometry].block_record
    newline = b'\r\n' if original.splitlines(keepends=True)[0].endswith(b'\r\n') else b'\n'
    block_record = export(block.export_dxf, doc.dxfversion, newline)
    block_definition = export(block.export_block_definition, doc.dxfversion, newline)
    entities = export(hole.export_dxf, doc.dxfversion, newline) + export(
        dim.export_dxf, doc.dxfversion, newline)
    new_handles = {h for _, h, _ in records(block_record + block_definition + entities) if h}
    candidate = splice(original, block_record, block_definition, entities,
                       str(doc.entitydb.handles), len(doc.block_records))
    BACKUP.write_bytes(original)
    CANDIDATE.write_bytes(candidate)
    verify(CANDIDATE, BACKUP, hole.dxf.handle, dim.dxf.handle, new_handles)
    CANDIDATE.replace(SOURCE)
    report = verify(SOURCE, BACKUP, hole.dxf.handle, dim.dxf.handle, new_handles)
    (ROOT / 'round3_check.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'round3_record.txt').write_text(
        '第3轮修改记录（后续会话请先读取）\n'
        '当前有效图纸：part.dxf；单位mm。备份：part.round3.before.dxf。\n'
        '板150×80的正中心(75,40)新增Ø30孔，HOLES图层，半径15。\n'
        f'新孔句柄{hole.dxf.handle}；原生直径标注句柄{dim.dxf.handle}；显示块{dim.dxf.geometry}。\n'
        '标注沿用EZDXF样式及DIM图层，实测30，显示Ø30；箭头及定义点均落在圆周。\n'
        '四个Ø12安装孔、板外形、已有尺寸、标题栏、技术要求、客户标识均未改动。\n'
        '仅新增孔、直径标注及其显示块，并更新HANDSEED及块表计数；其余原始字节完全一致。\n'
        '新标注与已有内容包围盒无交叠；原客户标识重叠仍保留，不得擅自调整。\n'
        '候选文件及最终文件复读核对通过，ezdxf审计错误0、修复0。\n'
        '诊断时默认GBK读取失败，改为显式UTF-8后解决；图纸未受影响。\n'
        '脚本modify_round3.py有防重复执行保护；核对报告round3_check.json。\n',
        encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
