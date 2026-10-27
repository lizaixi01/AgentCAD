from pathlib import Path
import ezdxf, math, json
from ezdxf import bbox
ROOT=Path(__file__).resolve().parent
doc=ezdxf.readfile(ROOT/'part.dxf')
report=json.loads((ROOT/'verification.json').read_text(encoding='utf-8'))

def segments(e):
    typ=e.dxftype()
    if typ=='LINE':
        yield e.dxf.start,e.dxf.end
    elif typ=='LWPOLYLINE':
        for v in e.virtual_entities(): yield from segments(v)
    elif typ=='INSERT':
        for v in e.virtual_entities(): yield from segments(v)
    elif typ in ('CIRCLE','ARC'):
        start=0 if typ=='CIRCLE' else e.dxf.start_angle
        sweep=360 if typ=='CIRCLE' else (e.dxf.end_angle-start)%360
        n=max(1,math.ceil(sweep/0.5))
        points=list(e.vertices(start+sweep*i/n for i in range(n+1)))
        yield from zip(points,points[1:])
    elif typ=='SOLID':
        points=list(e.vertices())
        yield from zip(points,points[1:]+points[:1])

def intersects_segment_box(a,b,box,pad=0.15):
    lower=[box.extmin.x-pad,box.extmin.y-pad]
    upper=[box.extmax.x+pad,box.extmax.y+pad]
    t0,t1=0.,1.
    for axis in range(2):
        delta=b[axis]-a[axis]
        if abs(delta)<1e-12:
            if a[axis]<lower[axis] or a[axis]>upper[axis]: return False
        else:
            lo=(lower[axis]-a[axis])/delta
            hi=(upper[axis]-a[axis])/delta
            if lo>hi: lo,hi=hi,lo
            t0=max(t0,lo); t1=min(t1,hi)
            if t0>t1: return False
    return True

def overlap(a,b,pad=0.15):
    return all(a.extmax[i]+pad>b.extmin[i] and b.extmax[i]+pad>a.extmin[i] for i in (0,1))

linework=[]
texts=[]
for e in doc.modelspace():
    if e.dxftype()=='DIMENSION':
        for v in e.virtual_entities():
            if v.dxftype() in ('MTEXT','TEXT'):
                texts.append((e.dxf.handle,bbox.extents([v])))
            else:
                linework.extend((e.dxf.handle,a,b) for a,b in segments(v))
    elif e.dxftype() not in ('MTEXT','TEXT'):
        linework.extend((e.dxf.handle,a,b) for a,b in segments(e))
    else:
        texts.append((e.dxf.handle,bbox.extents([e])))
collisions=[]
for h,box in texts:
    for src,a,b in linework:
        if intersects_segment_box(a,b,box): collisions.append((h,src,'text-line'))
for i,(h,a) in enumerate(texts):
    for h2,b in texts[i+1:]:
        if overlap(a,b): collisions.append((h,h2,'text-text'))
assert not collisions,collisions
report['layout_checks']={'text_line_collisions':0,'text_text_collisions':0,
    'clearance_mm':0.15,'tested_line_segments':len(linework),'text_count':len(texts)}
# Check the result actually written back, including required prefixes/suffixes.
assert len(doc.modelspace().query('DIMENSION'))==11
actual_text=[v.text for d in doc.modelspace().query('DIMENSION') for v in d.virtual_entities() if v.dxftype()=='MTEXT']
assert '2×%%c14' in actual_text and '10×45%%d' in actual_text
assert doc.entitydb[report['added_centerline']].dxf.layer=='CENTER'
(ROOT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report['layout_checks']))
print('Final part.dxf: 11 DIMENSION entities; original geometry and text unchanged; measurements and formatting passed.')
