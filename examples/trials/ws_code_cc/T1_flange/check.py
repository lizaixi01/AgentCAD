import ezdxf

doc = ezdxf.readfile("flange.dxf")
msp = doc.modelspace()
print("audit errors:", len(doc.audit().errors))
for e in msp:
    t = e.dxftype()
    if t == "CIRCLE":
        c = e.dxf.center
        lt = doc.layers.get(e.dxf.layer).dxf.linetype
        print(f"CIRCLE layer={e.dxf.layer} lt={lt} c=({c.x:.3f},{c.y:.3f}) D={2 * e.dxf.radius:.3f}")
    elif t == "LINE":
        s, n = e.dxf.start, e.dxf.end
        print(f"LINE layer={e.dxf.layer} ({s.x:.2f},{s.y:.2f}) -> ({n.x:.2f},{n.y:.2f})")
    elif t == "DIMENSION":
        p10, p15 = e.dxf.defpoint, e.dxf.defpoint4
        print(f"DIM type={e.dimtype} meas={e.get_measurement():.3f} text={e.dxf.text!r} "
              f"p10=({p10.x:.2f},{p10.y:.2f}) p15=({p15.x:.2f},{p15.y:.2f})")
        for b in doc.blocks[e.dxf.geometry]:
            if b.dxftype() == "MTEXT":
                print("   rendered text:", repr(b.text),f"at ({b.dxf.insert.x:.1f},{b.dxf.insert.y:.1f})")
