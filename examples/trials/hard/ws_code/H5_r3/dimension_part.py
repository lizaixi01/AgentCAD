from pathlib import Path
import ezdxf, math, shutil, json
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf import bbox

ROOT=Path(__file__).resolve().parent
BACKUP=ROOT/'part_original.dxf'
TARGET=ROOT/'part.dxf'
if not BACKUP.exists():
    shutil.copy2(TARGET, BACKUP)
doc=ezdxf.readfile(BACKUP)
msp=doc.modelspace()
assert len(msp.query('DIMENSION'))==0

def fingerprint(e):
    return [(t.code, str(t.value)) for t in TagCollector.dxftags(e)]
original={e.dxf.handle:fingerprint(e) for e in msp}
outline=msp.query('LWPOLYLINE')[0]
pts=[tuple(map(float,p[:2])) for p in outline.get_points()]
assert pts==[(0,0),(160,0),(160,80),(150,90),(0,90)]
holes=sorted(msp.query('CIRCLE'),key=lambda e:e.dxf.center.x)
a,b=holes
assert all(math.isclose(e.dxf.radius,7) for e in holes)
assert tuple(a.dxf.center)==(25,25,0) and tuple(b.dxf.center)==(135,25,0)
arcs=sorted(msp.query('ARC'),key=lambda e:e.dxf.center.x)
assert [(tuple(e.dxf.center),e.dxf.radius,e.dxf.start_angle,e.dxf.end_angle) for e in arcs]==[((66,62,0),6,90,270),((94,62,0),6,270,90)]
chamfer=pts[2:4]
angle=math.degrees(math.atan2(chamfer[1][1]-chamfer[0][1],chamfer[0][0]-chamfer[1][0]))
assert math.isclose(angle,45)

if 'SB_DIM_TEXT' not in doc.styles:
    doc.styles.new('SB_DIM_TEXT',dxfattribs={'font':'arial.ttf'})
style=doc.dimstyles.duplicate_entry('Standard','SB_MM')
style.dxf.update(dict(dimtxsty='SB_DIM_TEXT', dimscale=1, dimlfac=1,
    dimtxt=2.5, dimasz=2, dimexo=1, dimexe=1.5, dimgap=0.8,
    dimtad=1, dimtih=0, dimtoh=0, dimdec=2, dimzin=8, dimdsep=46,
    dimtmove=2, dimcen=0, dimclrd=0, dimclre=0, dimclrt=0,
    dimlwd=18, dimlwe=18))
records=[]
def linear(name,p1,p2,base,expected,angle=0,override=None):
    d=msp.add_linear_dim(p1=p1,p2=p2,base=base,angle=angle,
        dimstyle='SB_MM',override=override or {},dxfattribs={'layer':'DIM'})
    d.render()
    records.append(dict(name=name,handle=d.dimension.dxf.handle,expected=expected))
    return d

# Inner chains first, overall dimensions outermost; no closed dimension chains.
linear('hole_left_offset',(0,0),(25,25),(0,-11),25)
linear('hole_pitch',(25,25),(135,25),(0,-11),110)
linear('overall_length',(0,0),(160,0),(0,-25),160)
linear('hole_axis_height',(0,0),(25,25),(-11,0),25,90)
linear('slot_axis_height',(0,0),(60,62),(-22,0),62,90)
linear('overall_height',(0,0),(0,90),(-34,0),90,90)
linear('slot_overall_length',(60,62),(100,62),(0,101),40)
linear('slot_left_offset',(0,90),(60,62),(0,114),60)
linear('slot_width',(94,56),(94,68),(112,0),12,90)
linear('chamfer',(150,90),(160,80),(0,102),10,
       override={'dimpost':'<>×45%%d'})
d=msp.add_diameter_dim(center=a.dxf.center,radius=a.dxf.radius,
    location=(37,43),text='2×<>',dimstyle='SB_MM',override={'dimtad':0,'dimtoh':1,'dimtmove':1},
    dxfattribs={'layer':'DIM'})
d.render()
records.append(dict(name='two_hole_diameters',handle=d.dimension.dxf.handle,expected=14))
# The added centreline makes the single height dimension apply clearly to both holes.
center=msp.add_line((36,25),(124,25),dxfattribs={'layer':'CENTER'})

# Save to a temporary file, reload, and verify before replacing the requested file.
candidate=ROOT/'part_checked.dxf'
doc.saveas(candidate)
check=ezdxf.readfile(candidate)
for h,fp in original.items():
    assert fingerprint(check.entitydb[h])==fp, f'Original entity changed: {h}'
assert check.units==4
assert len(check.modelspace().query('DIMENSION'))==11
all_text=[]
for rec in records:
    e=check.entitydb[rec['handle']]
    assert e.dxftype()=='DIMENSION' and e.dxf.layer=='DIM'
    measurement=float(e.get_measurement())
    assert math.isclose(measurement,rec['expected'],abs_tol=1e-8),(rec,measurement)
    assert e.dxf.text==('2×<>' if rec['name']=='two_hole_diameters' else '<>')
    assert check.dimstyles.get(e.dxf.dimstyle).dxf.dimlfac==1
    rec['measurement']=measurement
    assert e.dxf.geometry in check.blocks
    text=[]
    for v in e.virtual_entities():
        if v.dxftype() in ('TEXT','MTEXT'):
            box=bbox.extents([v])
            item={'text':v.dxf.text if v.dxftype()=='TEXT' else v.text,
                  'min':list(box.extmin),'max':list(box.extmax)}
            text.append(item)
            all_text.append((rec['name'],box,v))
    assert text
    rec['rendered_text']=text

audit=check.audit()
assert not audit.errors and not audit.fixes, (audit.errors,audit.fixes)
report={'original_entities_unchanged':len(original),'dimension_count':len(records),
        'audit_errors':len(audit.errors),'audit_fixes':len(audit.fixes),
        'units':'mm','dimensions':records,
        'added_centerline':center.dxf.handle,'chamfer_angle':angle}
(ROOT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile(candidate,TARGET)
print(json.dumps(report,ensure_ascii=True,indent=2))
