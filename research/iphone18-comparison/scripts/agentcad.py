# AgentCAD FreeCAD script; dimensions in mm. Only overall body dimensions are official.
def rounded_box(x,y,z,w,h,t,r):
    s=Part.makeBox(w,h,t,Vector(x,y,z))
    edges=[e for e in s.Edges if len(e.Vertexes)==2 and abs(e.Vertexes[0].Point.z-e.Vertexes[1].Point.z)>t-1e-5]
    return s.makeFillet(r,edges)

phone=rounded_box(0,0,0,78,163.4,8.75,11.5)
# Back camera plateau and three stepped lens rings. All camera dimensions estimated.
bar=rounded_box(1.0,123.4,-1.8,76,38.0,2.0,8.0)
phone=phone.fuse(bar)
for x,y in [(60.3,151.3),(60.3,133.7),(43.2,142.5)]:
    ring=Part.makeCylinder(7.35,1.3,Vector(x,y,-3.0),Vector(0,0,1))
    phone=phone.fuse(ring)
    glass=Part.makeCylinder(5.55,0.32,Vector(x,y,-3.03),Vector(0,0,1))
    phone=phone.cut(glass)
# Flash and sensor, also recesses rather than decorative textures.
for x,y,r in [(12,151.5,3.0),(12,134.0,2.5)]:
    phone=phone.cut(Part.makeCylinder(r,0.36,Vector(x,y,-1.81),Vector(0,0,1)))
# Front display shallow recess, with raised pill inside the pocket.
screen=rounded_box(2.2,2.2,8.59,73.6,159.0,0.3,9.2)
phone=phone.cut(screen)
island=rounded_box(32.5,150.0,8.57,13.0,3.3,0.14,1.5)
phone=phone.fuse(island)
# Representative side controls; protrusions are not calibrated.
for y,h in [(118,8),(96,13),(78,13)]:
    phone=phone.fuse(Part.makeBox(0.3,h,2.4,Vector(-0.25,y,3.1)))
for y,h in [(105,19),(30,14)]:
    phone=phone.fuse(Part.makeBox(0.3,h,2.4,Vector(77.95,y,3.1)))
# USB-C cutout on lower edge.
phone=phone.cut(Part.makeBox(8.6,1.2,2.8,Vector(34.7,-0.1,2.9)))
result=phone.removeSplitter()
