import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
msp = doc.modelspace()
d5 = doc.entitydb['D2']
for k in ('defpoint', 'defpoint4', 'text_midpoint', 'leader_length'):
    print(k, d5.dxf.get(k))
print(d5.dxfattribs())
h = doc.entitydb['E2']
for p in h.paths:
    print(p)
tb = doc.blocks['TB']
for e in tb:
    if e.dxftype() in ('TEXT', 'MTEXT', 'ATTDEF'):
        print(e.dxftype(), e.dxf.insert, e.dxf.text if e.dxftype() != 'MTEXT' else e.text)
    elif e.dxftype() == 'LINE':
        print('LINE', e.dxf.start, e.dxf.end)
    else:
        print(e.dxftype())
ins = doc.entitydb['ED']
for a in ins.attribs:
    print('ATTRIB', a.dxf.tag, a.dxf.text)
print(doc.header.get('$EXTMIN'), doc.header.get('$EXTMAX'))
