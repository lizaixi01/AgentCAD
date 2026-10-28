import ezdxf
a = ezdxf.readfile('part.dxf')
b = ezdxf.readfile('part_new.dxf')
changed = {'91', '93', '95', '96', 'D2'}
ma = {e.dxf.handle: e for e in a.modelspace()}
mb = {e.dxf.handle: e for e in b.modelspace()}
print('same handle set:', set(ma) == set(mb))
for h in ma:
    if h in changed:
        continue
    ea, eb = ma[h], mb[h]
    same = ea.dxfattribs() == eb.dxfattribs()
    if ea.dxftype() == 'HATCH':
        same &= [list(p.vertices) for p in ea.paths] == [list(p.vertices) for p in eb.paths]
    if ea.dxftype() == 'INSERT':
        same &= [x.dxfattribs() | {'owner': 0} for x in ea.attribs] == [x.dxfattribs() | {'owner': 0} for x in eb.attribs]
    print(h, ea.dxftype(), 'unchanged' if same else 'CHANGED!')
for h in ('96', 'D2'):
    d = mb[h]
    print(h, 'measurement', d.get_measurement(), 'xdata', d.get_xdata('ACAD') if d.has_xdata('ACAD') else None)
    print('  orig xdata', ma[h].get_xdata('ACAD') if ma[h].has_xdata('ACAD') else None)
    blk = b.blocks[d.dxf.geometry]
    for e in blk:
        if e.dxftype() in ('MTEXT', 'TEXT'):
            print('  text:', e.text if e.dxftype() == 'MTEXT' else e.dxf.text, 'at', e.dxf.insert)
        elif e.dxftype() == 'LINE':
            print('  line', e.dxf.start, e.dxf.end)
        else:
            print(' ', e.dxftype(), e.dxf.insert if e.dxftype() == 'INSERT' else e.dxf.location)
    oblk = a.blocks[ma[h].dxf.geometry]
    print('  orig block:', [(e.dxftype(), e.text if e.dxftype() == 'MTEXT' else '') for e in oblk])
# geometry checks
o = mb['91']
xs = [p[0] for p in o.get_points('xy')]
print('plate width', max(xs) - min(xs))
for h in ('93', '95'):
    print('hole', h, 'dist to right edge', max(xs) - mb[h].dxf.center.x)
print('blocks', [x.name for x in b.blocks])
print('audit errors', len(b.audit().errors))
