import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
for e in msp:
    if e.dxftype() == 'MTEXT':
        print('MTEXT', repr(e.text).encode('unicode_escape'))
    if e.dxftype() == 'DIMENSION':
        print(e.dxf.handle, 'overrides', e.get_xdata('ACAD') if e.has_xdata('ACAD') else None)
ds = doc.dimstyles.get('EZDXF')
for k in ('dimclrd', 'dimclre', 'dimclrt', 'dimlwd', 'dimlwe', 'dimltype'):
    print(k, ds.dxf.get(k))
print('LTSCALE', doc.header.get('$LTSCALE'), 'ver', doc.dxfversion)
for b in doc.blocks:
    for x in b:
        if x.dxf.layer not in ('0', 'Defpoints'):
            print('block', b.name, x.dxftype(), x.dxf.layer)
