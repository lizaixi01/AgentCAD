"""Common presentation pass for both already-built models; no geometry is changed."""
import FreeCAD as App, FreeCADGui as Gui, os, sys, time
source, destination, solid_name = sys.argv[1:]
Gui.showMainWindow()
doc=App.openDocument(source)
for obj in doc.Objects:
    if hasattr(obj,'ViewObject'): obj.ViewObject.Visibility=False
obj=doc.getObject(solid_name)
if obj is None or not obj.Shape.isValid(): raise RuntimeError('Expected a valid solid')
obj.ViewObject.Visibility=True
colors=[]
for face in obj.Shape.Faces:
    center=face.CenterOfMass
    if center.z >= 8.57 and center.z < 8.72:
        col=(0.035,0.045,0.055) # screen
    elif center.z < -2.60:
        col=(0.035,0.045,0.065) # recessed lenses and ring
    elif center.z < -1.70:
        col=(0.31,0.12,0.15) # rear camera plateau
    else:
        col=(0.48,0.24,0.27) # approximate burgundy
    colors.append(col)
obj.ViewObject.ShapeColor=(0.48,0.24,0.27)
obj.ViewObject.DiffuseColor=colors
obj.ViewObject.LineColor=(0.10,0.07,0.08)
obj.ViewObject.DisplayMode='Flat Lines'
view=Gui.activeDocument().activeView()
doc.recompute()
display_name='agentcad-display.FCStd' if solid_name=='ScriptSolid' else 'native-display.FCStd'
doc.saveAs(os.path.join(destination,display_name))
for name,func in [('front',view.viewTop),('back',view.viewBottom),('angle',view.viewAxonometric)]:
    func(); view.fitAll()
    for _ in range(12):
        Gui.updateGui(); time.sleep(0.1)
    output=os.path.join(destination,name+'.png')
    view.saveImage(output,1000,1000,'White')
    if name=='back':
        from PIL import Image
        with Image.open(output) as img:
            img.rotate(180).save(output)
print('PRESENTATION_OK',source,len(obj.Shape.Solids),obj.Shape.isValid(),obj.Shape.Volume)
App.closeDocument(doc.Name)
Gui.getMainWindow().close()
