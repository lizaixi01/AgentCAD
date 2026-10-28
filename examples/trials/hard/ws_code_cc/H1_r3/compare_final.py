import ezdxf
a = ezdxf.readfile('part.dxf')
b = ezdxf.readfile('part_new.dxf')
ma = {e.dxf.handle: e.dxfattribs() for e in a.modelspace()}
mb = {e.dxf.handle: e.dxfattribs() for e in b.modelspace()}
print('modelspace identical to verified file:', ma == mb)
print('blocks', [x.name for x in a.blocks] == [x.name for x in b.blocks])
o = a.entitydb['91']
xs = [p[0] for p in o.get_points('xy')]
print('width', max(xs) - min(xs), 'holes', [tuple(a.entitydb[h].dxf.center)[:2] for h in ('92', '93', '94', '95')])
print('width dim', a.entitydb['96'].get_measurement(), 'audit errors', len(a.audit().errors))
