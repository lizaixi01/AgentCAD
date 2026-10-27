import json
from collections import Counter
import ezdxf

doc = ezdxf.readfile('part.dxf')
print('VERSION', doc.dxfversion, 'UNITS', doc.units)
print('LAYERS', [dict(x.dxf.all_existing_dxf_attribs()) for x in doc.layers])
print('LAYOUTS', [(x.name, len(x)) for x in doc.layouts])
print('BLOCKS', [(x.name, len(x)) for x in doc.blocks])
print('COUNTS', dict(Counter(e.dxftype() for e in doc.modelspace())))
for layout in doc.layouts:
    print('LAYOUT', layout.name)
    for e in layout:
        print(json.dumps({'type': e.dxftype(), **e.dxf.all_existing_dxf_attribs()}, default=str, ensure_ascii=False))
        if e.dxftype() == 'DIMENSION':
            print('DIM OVERRIDES', e.get_acad_dstyle({}))
            if e.dxf.hasattr('geometry'):
                b = doc.blocks.get(e.dxf.geometry)
                if b:
                    for child in b:
                        print('DIM CHILD', child.dxftype(), dict(child.dxf.all_existing_dxf_attribs()))
