import ezdxf
D=ezdxf.readfile('part.dxf')
for e in D.modelspace().query('LWPOLYLINE'):
 print('OUTLINE',e.dxf.handle,list(e.get_points()),'closed',e.closed)
for b in D.blocks:
 for e in b:
  if e.dxftype() in ('TEXT','MTEXT'):
   print('TEXT',b.name,e.dxf.handle,repr(e.dxf.text if e.dxftype()=='TEXT' else e.text))
for e in D.modelspace().query('DIMENSION'):
 print('DIM',e.dxf.handle,e.get_measurement(),e.get_acad_dstyle({}))
print('DIMSTYLE',D.dimstyles.get('EZDXF').dxfattribs())
a=D.audit();print('AUDIT',len(a.errors),len(a.fixes))
