"""Post-run sampled boundary comparison. Never included in a model workspace."""
import hashlib
import json
from pathlib import Path
from freecad_validator._freecad_loader import import_freecad
F = import_freecad()
import Part


def load(path):
    doc = F.openDocument(str(path))
    shape = next(o for o in doc.Objects if o.TypeId == 'PartDesign::Body').Shape.Solids[0].copy()
    F.closeDocument(doc.Name)
    return shape


def points(shape):
    out = {}
    for edge in shape.Edges:
        for p in edge.discretize(Number=5):
            out[tuple(round(c, 7) for c in (p.x, p.y, p.z))] = p
    return list(out.values())


source = Path(r'D:\Projects\bench-ws\cadbench-v3-section-retest-20261030\freecad-686f17ce17\answer.FCStd')
reference_path = Path(r'D:\Projects\bench-data\cadbench-v3\cad-bench\freecad-686f17ce17\tests\grader\reference.FCStd')
reference, candidate = load(reference_path), load(source)
ref_pts = points(reference)
box = candidate.optimalBoundingBox(False, False)
middle_y = (box.YMin + box.YMax) / 2
rows = []
for sign in [-1, 1]:
    # Map vertical Z to reference Y, reach X to reference -Z, and centered Y to +/- reference X.
    values = [0, sign, 0, -sign * middle_y, 0, 0, 1, 0, -1, 0, 0, 0, 0, 0, 0, 1]
    matrix = F.Matrix(*values)
    transformed = candidate.copy()
    transformed.transformShape(matrix, True)
    candidate_pts = points(transformed)
    forward = [Part.Vertex(p).distToShape(reference)[0] for p in candidate_pts]
    reverse = [Part.Vertex(p).distToShape(transformed)[0] for p in ref_pts]
    rows.append({'determinant': -sign, 'matrix_row_major': values,
        'candidate_points': len(forward), 'reference_points': len(reverse),
        'candidate_to_reference_max': max(forward), 'reference_to_candidate_max': max(reverse),
        'bidirectional_mean': sum(forward + reverse) / (len(forward) + len(reverse)),
        'volume_before': candidate.Volume, 'volume_after': transformed.Volume})
result = {'posthoc_only': True, 'units': 'mm', 'official_score': False,
    'method': 'Five points per B-rep edge, deduplicated; bidirectional point-to-surface distances. Not full Hausdorff.',
    'alignment': 'Axis correspondence from bend planes; two declared transforms, not exhaustive optimization.',
    'candidate_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'reference_sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
    'candidate_faces': len(candidate.Faces), 'reference_faces': len(reference.Faces), 'transforms': rows}
Path(__file__).with_suffix('.json').write_text(json.dumps(result, indent=2), 'utf-8')
print(json.dumps(result, indent=2))
