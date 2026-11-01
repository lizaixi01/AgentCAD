import FreeCAD as App
import Mesh, MeshPart, json, os, time

base = os.environ['SHAHE_NATIVE_OUT']
start = time.time()
doc = App.openDocument(os.path.join(base, 'shahe-native-b.FCStd'))
mesh = Mesh.Mesh()
for obj in doc.Objects:
    # Deflections in mm and radians; export separate material groups into one mesh.
    part = MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=100.0,
                                  AngularDeflection=0.35, Relative=False)
    mesh.addMesh(part)
path = os.path.join(base, 'shahe-native-b.stl')
mesh.write(path)
App.closeDocument(doc.Name)
check = Mesh.Mesh(path)
b = check.BoundBox
result = {'file': path, 'format': 'STL', 'units_assumed': 'mm',
          'facets': check.CountFacets, 'points': check.CountPoints,
          'bbox_mm': {'x': b.XLength, 'y': b.YLength, 'z': b.ZLength},
          'is_solid': check.isSolid(),
          'elapsed_seconds': round(time.time() - start, 3)}
with open(os.path.join(base, 'mesh-validation.json'), 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False))
