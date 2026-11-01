# Independently re-open FCStd and STEP exports, check geometry and dimensions.
import FreeCAD as App, Part, json, os, sys
root=sys.argv[1]
result={}
for group,fcname,objname,stepname in [('agentcad','iphone18.FCStd','ScriptSolid','iphone18.step'),('native','iphone18-native.FCStd','Phone','iphone18-native.step')]:
    d=App.openDocument(os.path.join(root,group,fcname))
    original=d.getObject(objname).Shape
    exported=Part.read(os.path.join(root,group,stepname))
    if not original.isValid() or len(original.Solids)!=1 or not exported.isValid() or len(exported.Solids)!=1:
        raise ValueError(group+' invalid or not a single solid')
    err=abs(original.Volume-exported.Volume)
    bounds=original.BoundBox
    if err>1e-4 or abs(bounds.XLength-78.5)>1e-5 or abs(bounds.YLength-163.4)>1e-5 or abs(bounds.ZLength-11.75)>1e-5:
        raise ValueError(group+' dimensions or STEP volume mismatch')
    result[group]={'fcstd_valid':True,'step_valid':True,'solids':1,'bbox_mm':[bounds.XLength,bounds.YLength,bounds.ZLength], 'step_volume_difference_mm3':err}
    App.closeDocument(d.Name)
print(json.dumps(result,indent=2))
