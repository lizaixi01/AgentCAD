"""Revise this drawing with ezdxf while retaining untouched DXF records verbatim.

No additional packages are required. Base Plate contains an independent 0.325
scale paper-space copy, not a model viewport. Dimensions belong to that layout.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from io import StringIO
from math import cos, sin, radians, isclose
from pathlib import Path
import json

import ezdxf
from ezdxf import bbox
from ezdxf.disassemble import recursive_decompose
from ezdxf.lldxf.tagwriter import TagWriter
from ezdxf.math import Vec3

SOURCE = Path('part.dxf')
OUTPUT = Path('part_rev.dxf')
SCALE = 0.325
NOTE = 'REV B: Ø10.2→Ø10.5, Ø25→Ø26'


def pairs(data):
    lines = data.splitlines(keepends=True)
    assert len(lines) % 2 == 0
    return [(int(lines[i].strip()), lines[i + 1].strip(),
             lines[i] + lines[i + 1]) for i in range(0, len(lines), 2)]


def records(tags):
    result = []
    for tag in tags:
        if tag[0] == 0 or not result:
            result.append([])
        result[-1].append(tag)
    return result


def value(rec, code):
    return next((v.decode('utf-8') for c, v, _ in rec if c == code), None)


def export(entities):
    stream = StringIO()
    writer = TagWriter(stream, dxfversion='AC1032')
    for entity in entities:
        entity.export_dxf(writer)
    return stream.getvalue().replace('\n', '\r\n').encode('utf-8')


def overlap(a, b, gap=0):
    return (a.extmin.x < b.extmax.x + gap and
            a.extmax.x > b.extmin.x - gap and
            a.extmin.y < b.extmax.y + gap and
            a.extmax.y > b.extmin.y - gap)


def segment_hits_box(start, end, box, gap=0.2):
    # Liang-Barsky clipping; zero-length and vertical lines are supported.
    lo, hi = 0.0, 1.0
    for a, b, minimum, maximum in (
        (start.x, end.x, box.extmin.x-gap, box.extmax.x+gap),
        (start.y, end.y, box.extmin.y-gap, box.extmax.y+gap),
    ):
        delta = b-a
        if abs(delta) < 1e-12:
            if a < minimum or a > maximum:
                return False
        else:
            t1, t2 = sorted(((minimum-a)/delta, (maximum-a)/delta))
            lo, hi = max(lo, t1), min(hi, t2)
            if lo > hi:
                return False
    return True


def make_dimension(layout, circle, location):
    dim = layout.add_diameter_dim(
        center=circle.dxf.center, radius=circle.dxf.radius,
        location=location, dimstyle='2dTranslator Dimension Style',
        override={'dimtxt': 2.5, 'dimasz': 1.2, 'dimgap': 0.65,
                  'dimlfac': 1/SCALE, 'dimdec': 0, 'dimtad': 1,
                  'dimcen': 0, 'dimtoh': 1, 'dimtxsty': 'Standard'},
        dxfattribs={'layer': 'Dimensions', 'lineweight': 25},
    )
    dim.render()
    # ezdxf emits optional POINT markers on an implicitly created Defpoints
    # layer. The source has no such serialized layer; the DIMENSION already
    # stores its definition points, so omit these non-plotting helper entities.
    block = layout.doc.blocks[dim.dimension.dxf.geometry]
    for point in list(block.query('POINT')):
        block.delete_entity(point)
    return dim.dimension


def choose_locations():
    """Place each label in clear space without moving existing drawing content."""
    trial = ezdxf.readfile(SOURCE)
    paper = trial.layout('Base Plate')
    existing = list(recursive_decompose(paper))
    obstacles = [(e, bbox.extents([e])) for e in existing
                 if e.dxftype() in ('LINE', 'ARC', 'CIRCLE', 'TEXT', 'MTEXT')]
    holes = [e for e in paper.query('CIRCLE')
             if e.dxf.layer == 'Visible Edges' and isclose(e.dxf.radius, 6.5)]
    choices = []
    for hole in holes:
        options = []
        for distance in (12, 16, 20):
            for angle in range(0, 360, 15):
                v = Vec3(cos(radians(angle))*distance,
                         sin(radians(angle))*distance, 0)
                location = hole.dxf.center + v
                dim = make_dimension(paper, hole, location)
                block = trial.blocks[dim.dxf.geometry]
                text = block.query('MTEXT')[0]
                bb = bbox.extents([text])
                collisions = []
                for entity, eb in obstacles:
                    if not eb.has_data or not overlap(bb, eb, 0.4):
                        continue
                    if entity.dxftype() == 'LINE':
                        if not segment_hits_box(entity.dxf.start, entity.dxf.end, bb, 0.4):
                            continue
                    collisions.append(entity.dxftype())
                # Clear text is the priority; then prefer short leaders.
                score = 1000*len(collisions) + distance
                options.append((score, angle, tuple(location), len(collisions)))
        best = min(options)
        assert best[3] == 0, ('No clear dimension text location', best)
        choices.append({'hole': hole.dxf.handle, 'angle': best[1],
                        'location': best[2], 'text_collisions': best[3]})
    return choices


def main():
    original = SOURCE.read_bytes()
    source_hash = sha256(original).hexdigest()
    doc = ezdxf.readfile(SOURCE)
    original_blocks = set(b.name for b in doc.blocks)
    original_handles = set(doc.entitydb)
    model, paper = doc.modelspace(), doc.layout('Base Plate')
    original_audit = doc.audit()
    assert not original_audit.errors and not original_audit.fixes
    assert doc.units == 4 and doc.dxfversion == 'AC1032'

    # Prove that paper entities are a uniform scaled copy, including centers.
    model_circles = list(model.query('CIRCLE'))
    paper_circles = list(paper.query('CIRCLE'))
    assert len(model_circles) == len(paper_circles) == 84
    offset = paper_circles[0].dxf.center - model_circles[0].dxf.center*SCALE
    for m, p in zip(model_circles, paper_circles):
        assert p.dxf.center.isclose(m.dxf.center*SCALE+offset, abs_tol=1e-9)
        assert isclose(p.dxf.radius, m.dxf.radius*SCALE, abs_tol=1e-9)

    changes = {}
    for layout, scale in ((model, 1.0), (paper, SCALE)):
        counts = Counter()
        for circle in layout.query('CIRCLE'):
            if circle.dxf.layer != 'Visible Edges':
                continue
            for old, new in ((10.2, 10.5), (25.0, 26.0)):
                if isclose(circle.dxf.radius*2/scale, old, abs_tol=1e-8):
                    changes[circle.dxf.handle] = new*scale/2
                    circle.dxf.radius = new*scale/2
                    counts[old] += 1
                    break
        assert counts == {10.2: 18, 25.0: 6}, counts

    placements = choose_locations()
    dims = [make_dimension(paper, doc.entitydb[p['hole']], p['location'])
            for p in placements]
    assert len(dims) == 2
    note = paper.add_text(NOTE, dxfattribs={
        'layer': 'Text', 'style': 'Standard', 'height': 5,
        'insert': (20, 12, 0), 'lineweight': 25,
    })
    note_box = bbox.extents([note])
    flat = list(recursive_decompose(paper))
    note_conflicts = []
    for e in flat:
        if e is note or e.dxftype() not in ('LINE','ARC','CIRCLE','TEXT','MTEXT'):
            continue
        eb = bbox.extents([e])
        if not eb.has_data or not overlap(note_box, eb, 0.1):
            continue
        if e.dxftype() == 'LINE' and not segment_hits_box(e.dxf.start,e.dxf.end,note_box,0.1):
            continue
        note_conflicts.append(e.dxftype())
    assert not note_conflicts, note_conflicts
    assert note_box.extmax.y < 44.06900770229585

    new_blocks = [b for b in doc.blocks if b.name not in original_blocks]
    block_data = b''.join(export([b.block, *b, b.endblk]) for b in new_blocks)
    record_data = export([b.block_record for b in new_blocks])
    entity_data = export([*dims, note])
    assert all(e.dxf.handle not in original_handles for e in [*dims, note])

    # Surgical merge: only 48 radius values and allocation metadata change.
    # This retains native AutoCAD objects, extension data, sketches, block
    # definitions, text, plot settings, layouts, and all original handles.
    chunks = records(pairs(original))
    out = []
    section = table = None
    patched = set()
    insertions = Counter()
    metadata_edits = []
    for rec in chunks:
        kind = value(rec, 0)
        if kind == 'SECTION':
            section = value(rec, 2)
        if kind == 'TABLE':
            table = value(rec, 2)
        if kind == 'ENDTAB' and table == 'BLOCK_RECORD':
            out.append(record_data)
            insertions['block_records'] += len(new_blocks)
        if kind == 'ENDSEC' and section == 'BLOCKS':
            out.append(block_data)
            insertions['blocks'] += len(new_blocks)
        if kind == 'ENDSEC' and section == 'ENTITIES':
            out.append(entity_data)
            insertions['entities'] += 3
        handle = value(rec, 5)
        result = []
        variable = None
        for code, val, raw in rec:
            if section == 'HEADER' and code == 9:
                variable = val.decode('ascii')
            replacement = None
            if kind == 'CIRCLE' and handle in changes and code == 40:
                replacement = repr(changes[handle])
                patched.add(handle)
            elif section == 'HEADER' and variable == '$HANDSEED' and code == 5:
                replacement = format(max(int(h,16) for h in doc.entitydb)+1,'X')
                metadata_edits.append('$HANDSEED')
            elif kind == 'TABLE' and table == 'BLOCK_RECORD' and code == 70:
                replacement = str(len(doc.block_records))
                metadata_edits.append('BLOCK_RECORD count')
            if replacement is not None:
                line = raw.splitlines(keepends=True)[0]
                raw = line + replacement.encode('ascii') + b'\r\n'
            result.append(raw)
        out.append(b''.join(result))
        if kind == 'ENDTAB':
            table = None
        if kind == 'ENDSEC':
            section = None
    assert patched == set(changes)
    assert insertions == {'entities':3,'blocks':3,'block_records':3}, insertions
    OUTPUT.write_bytes(b''.join(out))

    revised = ezdxf.readfile(OUTPUT)
    audit = revised.audit()
    assert not audit.errors and not audit.fixes, (audit.errors,audit.fixes)
    assert sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    assert revised.units == 4 and revised.dxfversion == doc.dxfversion

    # Verify byte-for-byte retention of every original record, allowing only
    # requested circle radii and the two required allocation metadata fields.
    def keyed(data):
        def handle(r):
            return value(r,105) if value(r,0)=='DIMSTYLE' else value(r,5)
        return {handle(r):r for r in records(pairs(data))
                if handle(r) is not None and value(r,0) != 'SECTION'}
    before, after = keyed(original), keyed(OUTPUT.read_bytes())
    unchanged = 0
    for h, old in before.items():
        assert h in after, ('Missing original entity',h)
        new = after[h]
        if h in changes:
            assert [(c,v,raw) for c,v,raw in old if c!=40] == [
                (c,v,raw) for c,v,raw in new if c!=40], h
            assert isclose(float(value(new,40)),changes[h],abs_tol=1e-12)
        elif value(old,0)=='TABLE' and value(old,2)=='BLOCK_RECORD':
            assert [x for x in old if x[0]!=70] == [x for x in new if x[0]!=70]
        else:
            assert old==new, ('Unexpected change',h,value(old,0))
            unchanged += 1

    counts = {}
    for name, scale in (('Model',1.0),('Base Plate',SCALE)):
        old = ezdxf.readfile(SOURCE).layouts.get(name)
        new = revised.layouts.get(name)
        def holes(layout):
            return Counter(round(e.dxf.radius*2/scale,8) for e in layout.query('CIRCLE')
                           if e.dxf.layer=='Visible Edges')
        expected = holes(old)
        expected[10.2]-=18; expected[10.5]+=18
        expected[25.0]-=6; expected[26.0]+=6
        assert +expected == holes(new)
        for circle in old.query('CIRCLE'):
            other=revised.entitydb[circle.dxf.handle]
            assert circle.dxf.center == other.dxf.center
        counts[name] = {'before':dict(sorted(holes(old).items())),
                        'after':dict(sorted(holes(new).items()))}
        assert len(new) == len(old) + (3 if name=='Base Plate' else 0)

    for dim, placement in zip(revised.layout('Base Plate').query('DIMENSION'),placements):
        assert dim.dxf.dimtype & 15 == 3
        center=(dim.dxf.defpoint+dim.dxf.defpoint4)/2
        assert center.isclose(revised.entitydb[placement['hole']].dxf.center,abs_tol=1e-9)
        assert isclose(dim.get_measurement()*dim.override().get('dimlfac'),40,abs_tol=1e-9)
        assert [e.plain_text() for e in revised.blocks[dim.dxf.geometry].query('MTEXT')]==['Ø40']
    raw_revised = records(pairs(OUTPUT.read_bytes()))
    raw_layers = {value(rec,2) for rec in raw_revised if value(rec,0)=='LAYER'}
    raw_styles = {value(rec,2) for rec in raw_revised if value(rec,0)=='DIMSTYLE'}
    for block in new_blocks:
        for entity in block:
            assert entity.dxf.layer in raw_layers
    for dim in dims:
        assert dim.dxf.dimstyle in raw_styles
    actual_note = revised.entitydb[note.dxf.handle]
    assert actual_note.dxf.text==NOTE and actual_note.dxf.height==5
    report = {
        'output':str(OUTPUT), 'source_sha256':source_hash,
        'source_unchanged':True, 'units':'mm', 'version':revised.dxfversion,
        'physical_holes':counts['Model'], 'paper_copy_real_diameters':counts['Base Plate'],
        'paper_scale':SCALE, 'radius_entity_changes':len(changes),
        'original_records_unchanged':unchanged,
        'original_records_deleted':0, 'metadata_edits':metadata_edits,
        'serialized_original_handles_retained':set(before).issubset(after),
        'new_dimension_dependencies_defined_in_raw_dxf':True,
        'added_layout_entities':{'DIMENSION':2,'TEXT':1},
        'new_blocks':[b.name for b in new_blocks],
        'diameter_dimensions_mm':[40,40], 'dimension_placements':placements,
        'revision_text':NOTE,'revision_text_height_mm':5,
        'revision_text_bbox':[list(note_box.extmin),list(note_box.extmax)],
        'revision_text_collisions':note_conflicts,
        'audit_errors':len(audit.errors),'audit_fixes':len(audit.fixes),
        'limitations':['AutoCAD DWG conversion and final AutoCAD visual display were not run.'],
    }
    Path('verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
