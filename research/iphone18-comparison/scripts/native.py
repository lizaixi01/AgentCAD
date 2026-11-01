"""Standalone FreeCAD: build the same shared visual brief without AgentCAD."""
import FreeCAD as App, Part, json, os
from FreeCAD import Vector

def blank(x,y,z,w,h,thickness,radius):
    box=Part.makeBox(w,h,thickness,Vector(x,y,z))
    vertical=[edge for edge in box.Edges if len(edge.Vertexes)==2 and abs(edge.Vertexes[0].Point.z-edge.Vertexes[1].Point.z)>thickness-0.00001]
    return box.makeFillet(radius,vertical)

shell=blank(0,0,0,78,163.4,8.75,11.5)
plate=blank(1,123.4,-1.8,76,38,2.0,8)
features=[plate]
for center in [(60.3,151.3),(60.3,133.7),(43.2,142.5)]:
    features.append(Part.makeCylinder(7.35,1.3,Vector(center[0],center[1],-3),Vector(0,0,1)))
for y,h in [(118,8),(96,13),(78,13)]:
    features.append(Part.makeBox(.3,h,2.4,Vector(-.25,y,3.1)))
for y,h in [(105,19),(30,14)]:
    features.append(Part.makeBox(.3,h,2.4,Vector(77.95,y,3.1)))
body=shell.multiFuse(features)
cutters=[blank(2.2,2.2,8.59,73.6,159.0,.3,9.2),Part.makeBox(8.6,1.2,2.8,Vector(34.7,-.1,2.9))]
for x,y in [(60.3,151.3),(60.3,133.7),(43.2,142.5)]:
    cutters.append(Part.makeCylinder(5.55,.32,Vector(x,y,-3.03)))
for x,y,r in [(12,151.5,3.0),(12,134,2.5)]:
    cutters.append(Part.makeCylinder(r,.36,Vector(x,y,-1.81)))
body=body.cut(Part.makeCompound(cutters))
body=body.fuse(blank(32.5,150,8.57,13,3.3,.14,1.5)).removeSplitter()
if not body.isValid() or len(body.Solids)!=1: raise ValueError('Native shape invalid or not one solid')
out=os.environ['IPHONE_NATIVE_OUT']
os.makedirs(out,exist_ok=True)
doc=App.newDocument('iPhone18Native')
obj=doc.addObject('PartDesign::Feature','Phone')
obj.Shape=body
doc.recompute()
doc.saveAs(os.path.join(out,'iphone18-native.FCStd'))
Part.export([obj],os.path.join(out,'iphone18-native.step'))
import Mesh
Mesh.export([obj],os.path.join(out,'iphone18-native.stl'))
b=body.BoundBox
with open(os.path.join(out,'validation.json'),'w',encoding='utf-8') as f:
    json.dump({'valid':body.isValid(),'solids':len(body.Solids),'volume_mm3':body.Volume,'bounds_mm':[b.XLength,b.YLength,b.ZLength],'freecad':App.Version()},f,indent=2)
print('NATIVE_OK',body.isValid(),len(body.Solids),b.XLength,b.YLength,b.ZLength)
