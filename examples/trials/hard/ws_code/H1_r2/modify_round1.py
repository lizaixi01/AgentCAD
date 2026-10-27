"""Round 1: widen only the plate and its dependent geometry; preserve other DXF bytes."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf import bbox
from ezdxf.math import Vec3

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'part.dxf'
BACKUP = ROOT / 'part.round1.before.dxf'
REPORT = ROOT / 'round1_check.json'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def tags(entity):
    return list(TagCollector.dxftags(entity))


def raw_records(data):
    lines = data.splitlines(keepends=True)
    require(len(lines) % 2 == 0, 'DXF must contain code/value pairs')
    codes = [int(lines[i].strip()) for i in range(0, len(lines), 2)]
    starts = [i for i, c in enumerate(codes) if c == 0] + [len(codes)]
    records = {}
    for start, end in zip(starts, starts[1:]):
        handles = [lines[2*i+1].strip().decode('ascii') for i in range(start, end) if codes[i] == 5]
        if handles:
            require(len(handles) == 1, 'Unexpected multiple handles in a record')
            require(handles[0] not in records, 'Duplicate raw handle')
            records[handles[0]] = (start, end)
    return lines, codes, records


def verify(path, original_path, expected_handles, expected_line_changes=None):
    before = ezdxf.readfile(original_path)
    after = ezdxf.readfile(path)
    require(after.units == before.units == 4, 'Units changed')
    original_handles = set(before.entitydb.keys())
    require(set(after.entitydb.keys()) == original_handles, 'Entity handles added or removed')
    differences = []
    for handle in sorted(original_handles):
        if tags(before.entitydb[handle]) != tags(after.entitydb[handle]):
            differences.append(handle)
    require(set(differences) == set(expected_handles), f'Unexpected semantic differences: {differences}')
    a_lines, a_codes, a_records = raw_records(original_path.read_bytes())
    b_lines, b_codes, b_records = raw_records(path.read_bytes())
    require(a_codes == b_codes and a_records == b_records, 'Raw DXF structure changed')
    actual_lines = [i for i, (a, b) in enumerate(zip(a_lines, b_lines)) if a != b]
    require(len(a_lines) == len(b_lines), 'DXF line count changed')
    if expected_line_changes is not None:
        require(set(actual_lines) == set(expected_line_changes), 'Unexpected raw byte changes')
    for handle, (start, end) in a_records.items():
        if handle not in expected_handles:
            require(a_lines[start*2:end*2] == b_lines[start*2:end*2], f'Untouched record changed: {handle}')

    plate = after.entitydb['91']
    old_plate = before.entitydb['91']
    pts = list(plate.get_points())
    old_pts = list(old_plate.get_points())
    require(plate.closed, 'Plate is no longer closed')
    require(len(pts) == len(old_pts) == 8, 'Outline topology changed')
    for old, new in zip(old_pts, pts):
        target_x = float(old[0]) + (30 if old[0] > 100 else 0)
        require(math.isclose(new[0], target_x) and tuple(old[1:]) == tuple(new[1:]), 'Unexpected outline modification')
    bounds = bbox.extents([plate])
    require(math.isclose(bounds.size.x, 150) and math.isclose(bounds.size.y, 80), 'Wrong plate envelope')
    radii = [arc.dxf.radius for arc in plate.virtual_entities() if arc.dxftype() == 'ARC']
    require(len(radii) == 4 and all(math.isclose(r, 5, abs_tol=1e-8) for r in radii), 'Corner radii changed')
    centers = []
    for h, center in [('92', (12,12,0)), ('93', (138,12,0)), ('94', (12,68,0)), ('95', (138,68,0))]:
        hole = after.entitydb[h]
        require(hole.dxf.center.isclose(Vec3(center)), f'Wrong hole center: {h}')
        require(hole.dxf.radius == 5, 'Hole diameter changed')
        centers.append(list(hole.dxf.center))
    for h in ('93', '95'):
        require(math.isclose(bounds.extmax.x - after.entitydb[h].dxf.center.x, 12), 'Wrong right edge distance')
    width = after.entitydb['96']
    require(math.isclose(width.get_measurement(), 150), 'Width dimension measurement incorrect')
    require(width.dxf.defpoint3.isclose(Vec3(150,5,0)), 'Width extension point incorrect')
    require(after.entitydb['A1'].text == '150', 'Rendered width text is stale')
    require(after.entitydb['A1'].dxf.insert.isclose(Vec3(75,-12.625,0)), 'Width text not centered')
    require(after.entitydb['9B'].dxf.start.x == after.entitydb['9B'].dxf.end.x == 150, 'Right extension line incorrect')
    require(after.entitydb['9E'].dxf.insert.x == 150 and after.entitydb['A0'].dxf.end.x == 147.5, 'Width arrow/line incorrect')
    diameter = after.entitydb['D2']
    require(math.isclose(diameter.get_measurement(), 10), 'Diameter dimension changed')
    midpoint = (diameter.dxf.defpoint + diameter.dxf.defpoint4) * 0.5
    require(midpoint.isclose(after.entitydb['95'].dxf.center), 'Diameter dimension detached from upper right hole')
    require(after.entitydb['DD'].text == before.entitydb['DD'].text == '4X %%c10', 'Diameter label changed')
    for entity in before.blocks['*D5']:
        moved = after.entitydb[entity.dxf.handle]
        attrs = {'LINE': ('start','end'), 'INSERT': ('insert',), 'MTEXT': ('insert',), 'POINT': ('location',)}[entity.dxftype()]
        for attr in attrs:
            require(moved.dxf.get(attr).isclose(entity.dxf.get(attr) + Vec3(30,0,0)), 'Diameter graphics did not follow hole')
    audit = after.audit()
    require(not audit.errors and not audit.fixes, f'Audit errors/fixes: {audit.errors}, {audit.fixes}')
    return {
        'file': path.name,
        'ezdxf_version': ezdxf.__version__,
        'units': 'mm',
        'plate_width': bounds.size.x,
        'plate_height': bounds.size.y,
        'corner_radii': radii,
        'hole_centers': centers,
        'hole_diameter': 10,
        'right_hole_center_to_right_edge': [12,12],
        'width_dimension_measured': width.get_measurement(),
        'width_dimension_displayed': after.entitydb['A1'].text,
        'hole_diameter_dimension_measured': diameter.get_measurement(),
        'modified_entity_handles': differences,
        'modified_tag_values': len(actual_lines),
        'all_other_bytes_unchanged': True,
        'audit_errors': len(audit.errors),
        'audit_fixes': len(audit.fixes),
        'source_sha256': hashlib.sha256(original_path.read_bytes()).hexdigest(),
        'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'limitation': 'Existing customer logo remains at its original coordinates and overlaps the widened plate/right upper hole; not moved as requested.',
    }


def main():
    require(not BACKUP.exists(), 'Round 1 backup already exists; refuse to repeat the modification')
    original = SOURCE.read_bytes()
    doc = ezdxf.readfile(SOURCE)
    plate = doc.entitydb['91']
    require(plate.dxftype() == 'LWPOLYLINE' and plate.dxf.layer == 'OUTLINE', 'Plate identity mismatch')
    require(math.isclose(bbox.extents([plate]).size.x, 120), 'Expected original width of 120')
    width = doc.entitydb['96']
    require(width.get_measurement() == 120, 'Expected width dimension of 120')
    touched = ['91','93','95','96','9B','9E','A0','A1','A4','D2']
    touched += [e.dxf.handle for e in doc.blocks['*D5']]
    old_tags = {h: tags(doc.entitydb[h]) for h in touched}

    plate.set_points([(x+30 if x>100 else x,y,sw,ew,b) for x,y,sw,ew,b in plate.get_points()])
    for h in ('93','95'):
        hole = doc.entitydb[h]
        require(hole.dxf.layer == 'HOLES' and hole.dxf.center.x == 108, 'Hole identity mismatch')
        hole.dxf.center += Vec3(30,0,0)
    width.dxf.defpoint3 += Vec3(30,0,0)
    width.dxf.text_midpoint += Vec3(15,0,0)
    for attr in ('start','end'):
        line = doc.entitydb['9B']
        line.dxf.set(attr, line.dxf.get(attr) + Vec3(30,0,0))
    doc.entitydb['9E'].dxf.insert += Vec3(30,0,0)
    doc.entitydb['A0'].dxf.end += Vec3(30,0,0)
    doc.entitydb['A1'].dxf.insert += Vec3(15,0,0)
    doc.entitydb['A1'].text = '150'
    doc.entitydb['A4'].dxf.location += Vec3(30,0,0)
    diameter = doc.entitydb['D2']
    for attr in ('defpoint','defpoint4','text_midpoint'):
        diameter.dxf.set(attr, diameter.dxf.get(attr) + Vec3(30,0,0))
    for e in doc.blocks['*D5']:
        attrs = {'LINE': ('start','end'), 'INSERT': ('insert',), 'MTEXT': ('insert',), 'POINT': ('location',)}[e.dxftype()]
        for attr in attrs:
            e.dxf.set(attr, e.dxf.get(attr) + Vec3(30,0,0))

    # Export edited entities through ezdxf, then replace only changed tag values
    # in the original ASCII DXF. This avoids rewriting unrelated drawing data,
    # metadata, handles, title attributes, hatch loops or client graphics.
    lines, codes, records = raw_records(original)
    changed_lines = []
    for handle in touched:
        previous, current = old_tags[handle], tags(doc.entitydb[handle])
        require(len(previous) == len(current), f'Tag count changed for {handle}')
        start, end = records[handle]
        raw_codes = codes[start:end]
        require(raw_codes == [t.code for t in previous], f'Raw/exported tag layout mismatch for {handle}')
        for offset, (a,b) in enumerate(zip(previous,current)):
            require(a.code == b.code, f'Tag code changed for {handle}')
            if a.value != b.value:
                index = 2*(start+offset)+1
                ending = b'\r\n' if lines[index].endswith(b'\r\n') else b'\n'
                lines[index] = str(b.value).encode('utf-8') + ending
                changed_lines.append(index)
    candidate = ROOT / 'part.round1.candidate.dxf'
    candidate.write_bytes(b''.join(lines))
    BACKUP.write_bytes(original)
    # Verify before replacing the working drawing.
    verify(candidate, BACKUP, touched, changed_lines)
    candidate.replace(SOURCE)
    report = verify(SOURCE, BACKUP, touched, changed_lines)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
