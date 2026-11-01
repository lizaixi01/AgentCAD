# Compare two saved solids in FreeCAD; this is not a comparison to Apple geometry.
import FreeCAD as App, json, sys
first=App.openDocument(sys.argv[1]); second=App.openDocument(sys.argv[2])
a=first.getObject('ScriptSolid').Shape; b=second.getObject('Phone').Shape
if not a.isValid() or not b.isValid(): raise ValueError('invalid solid')
result={'a_valid':a.isValid(),'b_valid':b.isValid(),'a_solids':len(a.Solids),'b_solids':len(b.Solids),'a_volume_mm3':a.Volume,'b_volume_mm3':b.Volume,'a_minus_b_mm3':a.cut(b).Volume,'b_minus_a_mm3':b.cut(a).Volume,'note':'A/B inter-model difference only; same author and shared specification, not an independent benchmark or ground-truth accuracy.'}
with open(sys.argv[3], 'w', encoding='utf-8') as f: json.dump(result,f,indent=2)
print(json.dumps(result))
