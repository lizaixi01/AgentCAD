import FreeCAD as App, sys, os
for group,name,obj in [('agentcad','agentcad-display.FCStd','ScriptSolid'),('native','native-display.FCStd','Phone')]:
 d=App.openDocument(os.path.join(sys.argv[1],group,name)); s=d.getObject(obj).Shape
 assert s.isValid() and len(s.Solids)==1
 print(group,round(s.Volume,6),len(s.Faces))
 App.closeDocument(d.Name)
