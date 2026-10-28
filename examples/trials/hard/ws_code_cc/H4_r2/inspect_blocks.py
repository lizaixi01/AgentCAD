import ezdxf, sys
doc = ezdxf.readfile(sys.argv[1])
for b in doc.blocks:
    if b.name.startswith('*D') or not b.name.startswith('*'):
        print("BLOCK", b.name, "layer", b.block.dxf.layer)
        for e in b:
            d = e.dxf
            print("   ", e.dxftype(), d.layer, d.get('color'), d.get('linetype'), d.get('lineweight'))
for e in doc.modelspace().query('DIMENSION'):
    print(e.dxf.handle, e.dxf.dimstyle, e.get_dim_style().dxf.get('dimclrd'), e.get_dim_style().dxf.get('dimclre'), e.get_dim_style().dxf.get('dimclrt'))
    print("  xdata:", e.get_xdata('ACAD') if e.has_xdata('ACAD') else None)
for e in doc.objects:
    print("OBJ", e.dxftype(), e.dxf.handle)
for v in doc.viewports:
    print("VPORT", v.dxf.name)
print("styles", [(s.dxf.name, s.dxf.font) for s in doc.styles])
print("groups", list(doc.groups))
