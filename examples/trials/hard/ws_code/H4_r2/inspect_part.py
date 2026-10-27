import ezdxf
from collections import Counter
p='part.dxf'
doc=ezdxf.readfile(p)
print('VERSION',doc.dxfversion,'UNITS',doc.units)
print('LAYERS')
for layer in doc.layers:
 print(layer.dxfattribs())
print('LINETYPES', [x.dxf.name for x in doc.linetypes])
print('MODELSPACE')
for e in doc.modelspace():
 print(e.dxftype(),e.dxfattribs())
print('BLOCKS')
for b in doc.blocks:
 print('BLOCK',b.name,Counter(e.dxftype() for e in b))
 for e in b:
  print(' ',e.dxftype(),e.dxfattribs())
