"""Parent-only deterministic surface-distance probe; not a benchmark score."""
import json
from pathlib import Path
from freecad_validator._freecad_loader import import_freecad
F = import_freecad()
import Part

def load(path):
    doc=F.openDocument(str(path))
    shape=next(o for o in doc.Objects if o.TypeId=='PartDesign::Body').Shape.Solids[0].copy()
    F.closeDocument(doc.Name)
    return shape

def points(shape):
    out={}
    for edge in shape.Edges:
        for p in edge.discretize(Number=5):
            out[tuple(round(c,7) for c in (p.x,p.y,p.z))]=p
    return list(out.values())

reference=load(next(Path(r'D:\Projects\bench-data\cadbench-v3\cad-bench\freecad-686f17ce17\tests').rglob('reference.FCStd')))
ref_pts=points(reference)
rows=[]
for run in ['cadbench-v3-drawing-retest-20261030','cadbench-v3-drawing-retest2-20261030']:
    shape=load(Path(r'D:\Projects\bench-ws')/run/'freecad-686f17ce17/answer.FCStd')
    for sign in [-1,1]:
        # Axis correspondence from the bend planes and vertical direction; match inlet at the left/right leg.
        middle_y=(shape.optimalBoundingBox(False,False).YMin+shape.optimalBoundingBox(False,False).YMax)/2
        matrix=F.Matrix(0,sign,0,-sign*middle_y,0,0,1,0,-1,0,0,0,0,0,0,1)
        transformed=shape.copy(); transformed.transformShape(matrix,True)
        candidate_pts=points(transformed)
        values=[Part.Vertex(p).distToShape(reference)[0] for p in candidate_pts]
        reverse=[Part.Vertex(p).distToShape(transformed)[0] for p in ref_pts]
        row={'run':run,'determinant':-sign,'reference_faces':len(reference.Faces),'candidate_faces':len(shape.Faces),
             'candidate_points':len(values),'reference_points':len(reverse),
             'candidate_to_reference_max':max(values),'reference_to_candidate_max':max(reverse),
             'bidirectional_mean':sum(values+reverse)/(len(values)+len(reverse)),
             'volume_before':shape.Volume,'volume_after':transformed.Volume}
        rows.append(row); print(json.dumps(row),flush=True)
Path(__file__).with_suffix('.json').write_text(json.dumps(rows,indent=2),'utf-8')
