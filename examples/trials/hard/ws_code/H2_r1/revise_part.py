"""Revise with ezdxf while preserving all unrelated source DXF bytes."""
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3

SOURCE = Path('part.dxf')
OUTPUT = Path('part_rev.dxf')
NOTE = 'REV B: Ø10.2→Ø10.5, Ø25→Ø26'
SCALE = 0.325


@dataclass
class Pair:
    code: int
    value: str
    start: int
    end: int


def pairs(data):
    lines = data.splitlines(keepends=True)
    assert len(lines) % 2 == 0
    result, offset = [], 0
    for i in range(0, len(lines), 2):
        size = len(lines[i]) + len(lines[i + 1])
        result.append(Pair(int(lines[i]), lines[i + 1].decode('utf-8').strip(), offset, offset + size))
        offset += size
    return result


def records(data):
    ps = pairs(data)
    starts = [i for i, p in enumerate(ps) if p.code == 0] + [len(ps)]
    section, table = '', ''
    result = []
    for a, b in zip(starts, starts[1:]):
        group = ps[a:b]
        kind = group[0].value
        value = lambda code: next((p.value for p in group if p.code == code), None)
        if kind == 'SECTION':
            section = value(2)
        if kind == 'TABLE':
            table = value(2)
        handle = None if kind in ('SECTION', 'ENDSEC', 'EOF') else value(5) or value(105)
        result.append(dict(kind=kind, section=section, table=table, handle=handle,
                           pairs=group, start=group[0].start, end=group[-1].end))
        if kind == 'ENDTAB':
            table = ''
    return result


def hole_counts(layout, scale=1):
    return Counter(round(2 * e.dxf.radius / scale, 6)
                   for e in layout.query('CIRCLE') if e.dxf.layer == 'Visible Edges')


original = SOURCE.read_bytes()
source_hash = sha256(original).hexdigest()
doc = ezdxf.readfile(SOURCE)
known_handles = set(doc.entitydb)
model, paper = doc.modelspace(), doc.layouts.get('Base Plate')
before = hole_counts(model)
assert before == hole_counts(paper, SCALE)
assert before[10.2] == 18 and before[25] == 6 and before[40] == 2

# Infer translation from corresponding large holes; confirm every hole matches.
model_big = sorted((e for e in model.query('CIRCLE') if math.isclose(e.dxf.radius, 20)), key=lambda e: e.dxf.center.x)
paper_big = sorted((e for e in paper.query('CIRCLE') if math.isclose(e.dxf.radius, 6.5)), key=lambda e: e.dxf.center.x)
translation = paper_big[0].dxf.center - model_big[0].dxf.center * SCALE
matched = {}
for e in model.query('CIRCLE'):
    expected = e.dxf.center * SCALE + translation
    candidates = [p for p in paper.query('CIRCLE') if p.dxf.center.isclose(expected, abs_tol=1e-8)
                  and math.isclose(p.dxf.radius, e.dxf.radius * SCALE, abs_tol=1e-8)]
    assert len(candidates) == 1, (e.dxf.handle, candidates)
    matched[e.dxf.handle] = candidates[0]
assert len(matched) == 84 and len({e.dxf.handle for e in matched.values()}) == 84

changed_radii = {}
for e in model.query('CIRCLE'):
    diameter = 2 * e.dxf.radius
    new_diameter = 10.5 if math.isclose(diameter, 10.2, abs_tol=1e-8) else 26 if math.isclose(diameter, 25, abs_tol=1e-8) else None
    if new_diameter is not None:
        p = matched[e.dxf.handle]
        e.dxf.radius = new_diameter / 2
        p.dxf.radius = new_diameter * SCALE / 2
        changed_radii[e.dxf.handle] = e.dxf.radius
        changed_radii[p.dxf.handle] = p.dxf.radius
assert len(changed_radii) == 48

# Existing annotations are exclusively in paper space; follow that convention.
dimension_handles = []
for circle in paper_big:
    dim = paper.add_diameter_dim(
        center=circle.dxf.center, radius=circle.dxf.radius, angle=45,
        dimstyle='2dTranslator Dimension Style',
        override=dict(dimlfac=1 / SCALE, dimtxt=1.8, dimasz=1.8, dimgap=0.6,
                      dimtad=1, dimdec=0, dimzin=0, dimtih=0, dimtoh=0, dimdsep=46),
        dxfattribs={'layer': 'Dimensions'},
    )
    dim.render()
    dimension_handles.append(dim.dimension.dxf.handle)
note = paper.add_text(NOTE, dxfattribs={'layer': 'Text', 'height': 5, 'style': 'Standard', 'insert': (15, 13, 0)})
note_handle = note.dxf.handle
note_box = bbox.extents([note])
assert note_box.extmax.y < 22 and note_box.extmax.x < 138 and note_box.extmin.y > 10

new_handles = set(doc.entitydb) - known_handles
doc.saveas('generated_entities.dxf')
generated = Path('generated_entities.dxf').read_bytes()
source_records, generated_records = records(original), records(generated)
additions = [r for r in generated_records if r['handle'] in new_handles]
assert {r['section'] for r in additions} <= {'TABLES', 'BLOCKS', 'ENTITIES'}
assert {r['table'] for r in additions if r['section'] == 'TABLES'} == {'BLOCK_RECORD'}
serialized_handles = {r['handle'] for r in additions}
unserialized_handles = new_handles - serialized_handles
assert all(doc.entitydb[h].dxftype() == 'SEQEND' for h in unserialized_handles)
new_handles = serialized_handles

newline = b'\r\n' if b'\r\n' in original else b'\n'


def replace_value(pair, value):
    old = original[pair.start:pair.end]
    code_line = old.splitlines(keepends=True)[0]
    return code_line + str(value).encode('utf-8') + newline


edits = []
allowed_pair_starts = set()
for r in source_records:
    if r['handle'] in changed_radii:
        assert r['kind'] == 'CIRCLE'
        radius = next(p for p in r['pairs'] if p.code == 40)
        edits.append((radius.start, radius.end, replace_value(radius, repr(changed_radii[r['handle']]))))
        allowed_pair_starts.add(radius.start)

# Preserve original tables/headers, updating only required count and handle seed.
new_block_count = sum(r['section'] == 'TABLES' for r in additions)
block_table = next(r for r in source_records if r['kind'] == 'TABLE' and r['table'] == 'BLOCK_RECORD')
count_pair = next(p for p in block_table['pairs'] if p.code == 70)
edits.append((count_pair.start, count_pair.end, replace_value(count_pair, int(count_pair.value) + new_block_count)))
allowed_pair_starts.add(count_pair.start)
ps = pairs(original)
seed_index = next(i for i, p in enumerate(ps) if p.code == 9 and p.value == '$HANDSEED') + 1
seed_pair = ps[seed_index]
seed = format(max(int(h, 16) for h in (known_handles | new_handles)) + 1, 'X')
edits.append((seed_pair.start, seed_pair.end, replace_value(seed_pair, seed)))
allowed_pair_starts.add(seed_pair.start)

for section in ('TABLES', 'BLOCKS', 'ENTITIES'):
    selected = [r for r in additions if r['section'] == section]
    if section == 'TABLES':
        boundary = next(r for r in source_records if r['kind'] == 'ENDTAB' and r['table'] == 'BLOCK_RECORD')
    else:
        boundary = next(r for r in source_records if r['kind'] == 'ENDSEC' and r['section'] == section)
    payload = b''.join(generated[r['start']:r['end']].replace(b'\r\n', b'\n').replace(b'\n', newline) for r in selected)
    edits.append((boundary['start'], boundary['start'], payload))

edits.sort(key=lambda item: (item[0], item[1]))
chunks, cursor = [], 0
for start, end, value in edits:
    assert start >= cursor
    chunks.extend((original[cursor:start], value))
    cursor = end
chunks.append(original[cursor:])
OUTPUT.write_bytes(b''.join(chunks))

# Independently compare all original records at the raw DXF tag level.
result_bytes = OUTPUT.read_bytes()
result_records = records(result_bytes)
old_by_handle = {r['handle']: r for r in source_records if r['handle']}
new_by_handle = {r['handle']: r for r in result_records if r['handle']}
assert old_by_handle.keys() <= new_by_handle.keys()
assert new_by_handle.keys() - old_by_handle.keys() == new_handles
retained_records = [r for r in result_records if r['handle'] not in new_handles]
assert len(retained_records) == len(source_records)
for old, new in zip(source_records, retained_records):
    assert old['kind'] == new['kind']
    assert len(old['pairs']) == len(new['pairs'])
    for old_pair, new_pair in zip(old['pairs'], new['pairs']):
        assert old_pair.code == new_pair.code
        if old_pair.start not in allowed_pair_starts:
            assert original[old_pair.start:old_pair.end] == result_bytes[new_pair.start:new_pair.end]
unchanged_records = 0
for handle, old in old_by_handle.items():
    new = new_by_handle[handle]
    if handle in changed_radii or handle == block_table['handle']:
        old_tags = [(p.code, p.value) for p in old['pairs'] if p.start not in allowed_pair_starts]
        excluded_code = 40 if handle in changed_radii else 70
        new_tags = [(p.code, p.value) for p in new['pairs'] if p.code != excluded_code]
        assert old_tags == new_tags, handle
    else:
        assert original[old['start']:old['end']] == result_bytes[new['start']:new['end']], handle
        unchanged_records += 1

# Independently re-read output and validate geometry, dimensions, and text.
result = ezdxf.readfile(OUTPUT)
after = hole_counts(result.modelspace())
expected_counts = before.copy()
expected_counts[10.5] += expected_counts.pop(10.2)
expected_counts[26] += expected_counts.pop(25)
assert after == expected_counts == hole_counts(result.layouts.get('Base Plate'), SCALE)
for layout in (model, paper):
    reread_layout = result.layouts.get(layout.name)
    assert len(reread_layout) == len(layout)
    for circle in layout.query('CIRCLE'):
        reread = result.entitydb[circle.dxf.handle]
        assert reread.dxf.center == circle.dxf.center
        assert math.isclose(reread.dxf.radius, circle.dxf.radius, abs_tol=1e-12)
for handle, circle in zip(dimension_handles, paper_big):
    dim = result.entitydb[handle]
    assert dim.dimtype == 3
    assert math.isclose(dim.get_measurement(), 13, abs_tol=1e-8)
    assert ((dim.dxf.defpoint + dim.dxf.defpoint4) / 2).isclose(circle.dxf.center, abs_tol=1e-8)
    assert math.isclose(dim.get_measurement() * dim.override()['dimlfac'], 40, abs_tol=1e-8)
    assert dim.dxf.geometry in result.blocks
    labels = [e.plain_text() for e in result.blocks[dim.dxf.geometry] if e.dxftype() == 'MTEXT']
    assert len(labels) == 1 and labels[0] in ('Ø40', '⌀40', '%%c40'), labels
assert result.entitydb[note_handle].dxf.text == NOTE
assert result.entitydb[note_handle].dxf.height == 5
new_texts = [result.entitydb[note_handle]]
for handle in dimension_handles:
    new_texts.extend(e for e in result.blocks[result.entitydb[handle].dxf.geometry] if e.dxftype() == 'MTEXT')
source_paper = ezdxf.readfile(SOURCE).layouts.get('Base Plate')
for text in new_texts:
    text_bounds = bbox.extents([text])
    assert all(not bbox.extents([e]).has_intersection(text_bounds)
               for e in source_paper if e.dxftype() != 'VIEWPORT')
audit = result.audit()
assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
assert sha256(SOURCE.read_bytes()).hexdigest() == source_hash

report = dict(
    output=str(OUTPUT), ezdxf_version=ezdxf.__version__, units='mm',
    source_sha256=source_hash, original_unchanged=True,
    model_holes_before=dict(sorted(before.items())), model_holes_after=dict(sorted(after.items())),
    total_model_holes=sum(after.values()), paper_scale=SCALE,
    modified_circle_entities=len(changed_radii), unchanged_raw_records=unchanged_records,
    added_dimensions=dimension_handles, dimension_values_mm=[40, 40],
    dimension_layout='Base Plate', note=NOTE, note_height_mm=5,
    note_insert=[15, 13, 0], note_bounds=[list(note_box.extmin), list(note_box.extmax)],
    added_entity_types=dict(Counter(r['kind'] for r in additions)),
    removed_original_records=0, audit_errors=len(audit.errors), audit_fixes=len(audit.fixes),
    preserved_source_records=len(source_records), original_pair_changes=len(allowed_pair_starts),
    new_text_overlap_with_original=False,
)
Path('verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
Path('generated_entities.dxf').unlink()
print(json.dumps(report, indent=2, ensure_ascii=False))
