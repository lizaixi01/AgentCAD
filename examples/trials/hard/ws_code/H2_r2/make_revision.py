"""Focused DXF revision and independent read-back checks; no third-party additions."""
from collections import Counter
from hashlib import sha256
from math import isclose
from pathlib import Path
import json
import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.entities import DXFGraphic

SOURCE = Path('part.dxf')
OUTPUT = Path('part_rev.dxf')
SCALE = 0.325
NOTE = 'REV B: Ø10.2→Ø10.5, Ø25→Ø26'

def tags(e):
    return [(t.code, t.value) for t in TagCollector.dxftags(e, dxfversion='AC1032')]

def same(a, b):
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return isclose(a, b, rel_tol=1e-14, abs_tol=1e-12)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b

def counts(layout, scale=1):
    return dict(sorted(Counter(round(2 * c.dxf.radius / scale, 6) for c in layout.query('CIRCLE')).items()))

def bounds(e):
    b=bbox.extents([e], fast=True)
    return (list(b.extmin), list(b.extmax))

def persistent_graphic(e):
    if not e.is_alive or not isinstance(e,DXFGraphic):
        return False
    # ezdxf synthesizes empty INSERT SEQEND sentinels on load; these are not
    # DXF content and are assigned fresh handles on each subsequent read.
    if e.dxftype() == 'SEQEND':
        owner=e.doc.entitydb.get(e.dxf.owner)
        if owner is not None and owner.dxftype() == 'INSERT' and not owner.attribs:
            return False
    return True

source_hash = sha256(SOURCE.read_bytes()).hexdigest()
doc = ezdxf.readfile(SOURCE)
assert doc.units == 4 and doc.dxfversion == 'AC1032'
model = doc.modelspace()
paper = doc.layouts.get('Base Plate')
before = counts(model)
assert before == {8.5:12, 10.0:12, 10.2:18, 10.5:28, 12.0:6, 25.0:6, 40.0:2}, before

# Prove the paper geometry is a separate, uniformly scaled copy, not a viewport.
pairs = {}
for c in model.query('CIRCLE'):
    matches = [p for p in paper.query('CIRCLE')
               if p.dxf.center.isclose(c.dxf.center*SCALE, abs_tol=1e-9)
               and isclose(p.dxf.radius, c.dxf.radius*SCALE, abs_tol=1e-9)]
    assert len(matches) == 1, c.dxf.handle
    pairs[c.dxf.handle] = matches[0].dxf.handle
assert len(set(pairs.values())) == 84

original_blocks = {b.name:[e.dxf.handle for e in b] for b in doc.blocks}
original_tags = {e.dxf.handle:tags(e) for e in doc.entitydb.values()
                 if persistent_graphic(e)}
original_resources = {name: {e.dxf.handle:tags(e) for e in getattr(doc,name)}
                      for name in ('layers','styles','linetypes','dimstyles')}
changed = {}
for c in model.query('CIRCLE'):
    new_radius = next((new for old,new in ((5.1,5.25),(12.5,13.0))
                       if isclose(c.dxf.radius,old,abs_tol=1e-9)),None)
    if new_radius is not None:
        p = doc.entitydb[pairs[c.dxf.handle]]
        for entity,r in ((c,new_radius),(p,new_radius*SCALE)):
            changed[entity.dxf.handle] = (entity.dxf.radius,r)
            entity.dxf.radius = r
assert len(changed) == 48

# Existing dimensions all live on this paper layout. Add exactly two native
# diameter dimensions, with the inverse drawing scale for a displayed Ø40.
new_dimensions = []
for c in sorted(paper.query('CIRCLE'),key=lambda e:e.dxf.center.x):
    if not isclose(c.dxf.radius,20*SCALE,abs_tol=1e-9):
        continue
    dim = paper.add_diameter_dim(
        center=c.dxf.center, radius=c.dxf.radius,
        location=(c.dxf.center.x+11,c.dxf.center.y+0.5,0),
        dimstyle='2dTranslator Dimension Style',
        override={'dimlfac':1/SCALE,'dimtxt':2.0,'dimasz':1.25,
                  'dimgap':0.4,'dimtad':1,'dimdec':0,'dimzin':8,
                  'dimtoh':1,'dimtih':0,'dimtmove':0,'dimcen':0},
        dxfattribs={'layer':'Dimensions','color':7,'lineweight':25},
    )
    dim.render()
    dim.dimension.dxf.actual_measurement = 2*c.dxf.radius
    new_dimensions.append((dim.dimension.dxf.handle,c.dxf.handle))
assert len(new_dimensions) == 2

# Free strip below the existing general notes and above the border/title text.
note = paper.add_text(NOTE, dxfattribs={
    'insert':(25,12.5,0), 'height':5, 'style':'Standard',
    'layer':'Text', 'color':7, 'lineweight':25,
})
note_handle = note.dxf.handle
doc.saveas(OUTPUT)

# Keep original graphic records byte-for-byte. ezdxf's normal writer suppresses
# some explicit default tags; restoring the original records also preserves any
# exporter-specific fields. Only target CIRCLE group 40 values are replaced.
def records(data):
    lines=data.splitlines(keepends=True)
    assert len(lines)%2==0
    result=[]
    current=[]
    for i in range(0,len(lines),2):
        pair=lines[i:i+2]
        if int(pair[0].strip())==0 and current:
            result.append(current)
            current=[]
        current.extend(pair)
    if current:
        result.append(current)
    return result

def record_handle(lines):
    for i in range(0,len(lines),2):
        if int(lines[i].strip())==5:
            return lines[i+1].strip().decode('ascii')
    return None

raw_graphics={record_handle(r):r for r in records(SOURCE.read_bytes())
              if record_handle(r) in original_tags}
assert len(raw_graphics)==len(original_tags)
preserved_records=[]
for r in records(OUTPUT.read_bytes()):
    h=record_handle(r)
    if h in raw_graphics:
        r=list(raw_graphics[h])
        if h in changed:
            indices=[i+1 for i in range(0,len(r),2) if int(r[i].strip())==40]
            assert len(indices)==1
            i=indices[0]
            newline=b'\r\n' if r[i].endswith(b'\r\n') else b'\n'
            r[i]=format(changed[h][1],'.16g').encode('ascii')+newline
    preserved_records.extend(r)
OUTPUT.write_bytes(b''.join(preserved_records))
saved_records={record_handle(r):r for r in records(OUTPUT.read_bytes())
               if record_handle(r) in original_tags}
assert set(saved_records)==set(raw_graphics)
for h, original in raw_graphics.items():
    saved=saved_records[h]
    if h in changed:
        # Apart from the radius value line, even original raw formatting survives.
        old_without_radius=[v for i,v in enumerate(original)
                            if not (i%2 and int(original[i-1].strip())==40)]
        new_without_radius=[v for i,v in enumerate(saved)
                            if not (i%2 and int(saved[i-1].strip())==40)]
        assert old_without_radius==new_without_radius
    else:
        assert original==saved

# Read from disk rather than validating only the in-memory result.
out = ezdxf.readfile(OUTPUT)
assert sha256(SOURCE.read_bytes()).hexdigest() == source_hash
assert out.units == 4 and out.dxfversion == doc.dxfversion
expected = {8.5:12, 10.0:12, 10.5:46, 12.0:6, 26.0:6, 40.0:2}
assert counts(out.modelspace()) == expected
assert counts(out.layouts.get('Base Plate'),SCALE) == expected

# Every original graphic entity, including block contents and polyline vertices,
# must survive with identical serialized DXF tags, except the 48 radius values.
for handle, old_tags in original_tags.items():
    e=out.entitydb.get(handle)
    assert e is not None and e.is_alive, ('missing',handle)
    new_tags=tags(e)
    if handle in changed:
        assert e.dxftype() == 'CIRCLE'
        assert isclose(e.dxf.radius,changed[handle][1],abs_tol=1e-12)
        old_tags=[t for t in old_tags if t[0]!=40]
        new_tags=[t for t in new_tags if t[0]!=40]
    assert same(old_tags,new_tags), ('unexpected entity change',handle)

for name, handles in original_blocks.items():
    actual=[e.dxf.handle for e in out.blocks[name]]
    if name == '*Paper_Space':
        assert actual[:len(handles)] == handles
        assert actual[len(handles):] == [h for h,_ in new_dimensions]+[note_handle]
    else:
        assert actual == handles, ('block membership changed',name)
for name, entries in original_resources.items():
    for handle, old in entries.items():
        assert same(old,tags(out.entitydb[handle])), ('resource changed',name,handle)

new_graphics={e.dxf.handle for e in out.entitydb.values()
              if persistent_graphic(e)} - set(original_tags)
allowed_new = {note_handle}
dimension_report=[]
for h, circle_h in new_dimensions:
    dim=out.entitydb[h]
    assert dim.dxftype()=='DIMENSION' and dim.dimtype==3
    measurement=dim.get_measurement()
    factor=dim.override().get('dimlfac')
    assert isclose(measurement*factor,40,abs_tol=1e-9)
    circle=out.entitydb[circle_h]
    assert ((dim.dxf.defpoint+dim.dxf.defpoint4)/2).isclose(circle.dxf.center,abs_tol=1e-9)
    assert isclose((dim.dxf.defpoint-circle.dxf.center).magnitude,circle.dxf.radius,abs_tol=1e-9)
    block=out.blocks[dim.dxf.geometry]
    texts=[e.plain_text() for e in block.query('MTEXT TEXT')]
    assert texts==['Ø40'],texts
    allowed_new.add(h)
    allowed_new.update(e.dxf.handle for e in block)
    for ins in block.query('INSERT'):
        allowed_new.update(e.dxf.handle for e in out.blocks[ins.dxf.name])
    dimension_report.append({'handle':h,'circle_handle':circle_h,
        'paper_measurement':measurement,'dimlfac':factor,'displayed_diameter':measurement*factor,
        'rendered_text':texts,'bounds':bounds(dim)})
assert new_graphics == allowed_new, ('unexpected additions',new_graphics-allowed_new)
new_note=out.entitydb[note_handle]
assert new_note.dxf.text==NOTE and new_note.dxf.height==5
note_box=bbox.extents([new_note],fast=True)
assert note_box.extmax.y < 18.5 and note_box.extmin.y > 10
assert note_box.extmin.x > 14 and note_box.extmax.x < 138

# Compare the added note with every original flattened paper entity, including
# the border/title block contents. No existing entity bounds may overlap it.
from ezdxf.disassemble import recursive_decompose
obstacles=[]
for e in recursive_decompose(e for e in paper if e.dxf.handle in original_tags and e.dxftype()!='VIEWPORT'):
    primitives=e.virtual_entities() if e.dxftype() in ('POLYLINE','LWPOLYLINE') else [e]
    for primitive in primitives:
        b=bbox.extents([primitive],fast=True)
        if b.has_data and b.extmin.x < note_box.extmax.x and b.extmax.x > note_box.extmin.x and b.extmin.y < note_box.extmax.y and b.extmax.y > note_box.extmin.y:
            obstacles.append(primitive.dxftype())
assert not obstacles,('note overlaps original content',obstacles)

# Also keep the new diameter lettering clear of the dense existing dimensions.
original_primitives=[]
for e in recursive_decompose(e for e in paper if e.dxf.handle in original_tags and e.dxftype()!='VIEWPORT'):
    original_primitives.extend(e.virtual_entities() if e.dxftype() in ('POLYLINE','LWPOLYLINE') else [e])
for h,_ in new_dimensions:
    for t in out.entitydb[h].virtual_entities():
        if t.dxftype() not in ('TEXT','MTEXT'):
            continue
        q=bbox.extents([t],fast=True)
        for e in original_primitives:
            b=bbox.extents([e],fast=True)
            assert not (b.has_data and b.extmin.x<q.extmax.x and b.extmax.x>q.extmin.x
                        and b.extmin.y<q.extmax.y and b.extmax.y>q.extmin.y), ('diameter text overlap',h,e.dxftype())

audit=out.audit()
assert not audit.errors and not audit.fixes, (audit.errors,audit.fixes)
report={
    'input_sha256':source_hash,'source_unchanged':True,'dxf_version':out.dxfversion,'units':'mm',
    'paper_scale':SCALE,'holes_before':before,'holes_after':expected,'holes_total':84,
    'model_holes_changed':24,'paper_copy_circles_changed':24,
    'original_graphic_entities_preserved':len(original_tags),
    'original_graphic_raw_records_preserved_except_target_radii':True,
    'added_diameter_text_overlaps':0,
    'only_radius_changed_handles':changed,'dimensions':dimension_report,
    'note':{'text':NOTE,'height':5,'handle':note_handle,'bounds':bounds(new_note),'overlaps':obstacles},
    'audit_errors':0,'audit_fixes':0,
}
Path('verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
