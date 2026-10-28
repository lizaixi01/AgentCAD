"""part.dxf -> part_rev.dxf (REV B)."""
import math
import sys
from pathlib import Path

import ezdxf
from ezdxf import bbox

HERE = Path(__file__).resolve().parent
SRC = HERE / "part.dxf"
DST = HERE / "part_rev.dxf"

PS_SCALE = 0.325  # paper space "Base Plate" is a 0.325x copy of model space (verified)
CHANGES = {10.2: 10.5, 25.0: 26.0}  # true diameters, mm
NOTE = "REV B: Ø10.2→Ø10.5, Ø25→Ø26"
DIMSTYLE = "2dTranslator Dimension Style"
TOL = 1e-6

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()
ps = doc.layouts.get("Base Plate")


def resize_holes(layout, scale):
    changed = {d: 0 for d in CHANGES}
    for c in layout.query("CIRCLE"):
        true_d = c.dxf.radius * 2 / scale
        for old, new in CHANGES.items():
            if abs(true_d - old) < 1e-4:
                c.dxf.radius = new * scale / 2
                changed[old] += 1
    return changed


def big_holes(layout, scale):
    return sorted(
        (c for c in layout.query("CIRCLE") if abs(c.dxf.radius * 2 / scale - 40) < 1e-4),
        key=lambda c: c.dxf.center.x,
    )


print("model space resized:", resize_holes(msp, 1.0))
print("paper space resized:", resize_holes(ps, PS_SCALE))

def primitives(entities):
    """Explode INSERTs/polylines recursively, yield drawable primitives
    (a polyline border would otherwise "cover" the whole sheet)."""
    for e in entities:
        if e.dxftype() in ("INSERT", "POLYLINE", "LWPOLYLINE"):
            yield from primitives(e.virtual_entities())
        elif e.dxftype() not in ("VIEWPORT", "POINT", "ATTDEF"):
            yield e


def box2d(entities, pad=0.0):
    b = bbox.extents(entities, fast=False)
    if not b.has_data:
        return None
    return ezdxf.math.BoundingBox2d([b.extmin.vec2 - (pad, pad), b.extmax.vec2 + (pad, pad)])


def obstacles(layout):
    out = []
    for p in primitives(layout):
        b = box2d([p])
        if b is not None:
            out.append((p, b))
    return out


def collides(box, obs, ignore=()):
    return [p for p, b in obs if p not in ignore and box.has_overlap(b)]


# --- diameter dimensions on the two Ø40 holes -------------------------------
# Try angles around 45 deg and keep the first whose text and outside leader
# are clear of every existing primitive (holes, dims, notes, title block).
ANGLES = [45, 60, 30, 75, 15, 135, 120, 150, 105, 165, 90, 0, 180,
          225, 315, 240, 300, 210, 330, 255, 285]
# (layout, scale, text height, arrow size, text distance outside the circle)
for layout, scale, txt, asz, gap in ((msp, 1.0, 5.0, 4.0, 15.0), (ps, PS_SCALE, 2.5, 2.5, 5.0)):
    holes = big_holes(layout, scale)
    assert len(holes) == 2, holes
    obs = obstacles(layout)
    override = {"dimtxt": txt, "dimasz": asz, "dimtad": 1, "dimtih": 0, "dimtoh": 0}
    if scale != 1.0:
        override["dimlfac"] = 1 / scale  # paper-space copy: show true size
    for c in holes:
        r = c.dxf.radius
        for ang in ANGLES:
            loc = c.dxf.center + ezdxf.math.Vec3.from_deg_angle(ang, r + gap)
            dim = layout.add_diameter_dim(
                center=c.dxf.center, radius=r, location=loc, dimstyle=DIMSTYLE,
                override=override, dxfattribs={"layer": "Dimensions"},
            )
            dim.render()
            parts = list(dim.dimension.virtual_entities())
            text_box = box2d([p for p in parts if p.dxftype() == "MTEXT"], pad=0.5)
            # outside part of the leader: from the circle edge to the text
            edge = c.dxf.center + ezdxf.math.Vec3.from_deg_angle(ang, r + 0.5 * asz)
            lead_box = ezdxf.math.BoundingBox2d([edge.vec2, loc.vec2])
            hits = collides(text_box, obs, ignore=(c,)) + collides(lead_box, obs, ignore=(c,))
            if not hits:
                break
            # not clear: drop this try (entity + its anonymous block)
            blk_name = dim.dimension.dxf.geometry
            layout.delete_entity(dim.dimension)
            doc.blocks.delete_block(blk_name, safe=False)
        else:
            raise RuntimeError(f"no free angle for Ø40 dim at {c.dxf.center}")
        print(f"{layout.name}: Ø40 dim at {c.dxf.center.round(3)} angle {ang}")

# --- REV note ------------------------------------------------------------------
cache = bbox.Cache()


def outline_box(layout):
    lines = [e for e in layout.query("LINE ARC") if e.dxf.layer == "Visible Edges"]
    return bbox.extents(lines)


# model space: 20 mm below the bottom edge, left-aligned with the outline
ob = outline_box(msp)
t = msp.add_text(NOTE, height=5, dxfattribs={"layer": "Text", "style": "Standard"})
t.set_placement((ob.extmin.x, ob.extmin.y - 20))

# paper space: free strip between the inner border (y=10) and the
# "Material ..." note, left of "CONTROLLED COPY"; left-aligned with that note
t2 = ps.add_text(NOTE, height=5, dxfattribs={"layer": "Text", "style": "Standard"})
t2.set_placement((14.857, 12.5))

for layout, t_ in ((msp, t), (ps, t2)):
    hits = collides(box2d([t_], pad=0.5), obstacles(layout), ignore=(t_,))
    hits = [h for h in hits if h.dxftype() != "DIMENSION"]
    assert not hits, (layout.name, [(h.dxftype(), h.dxf.layer) for h in hits])

doc.saveas(DST)
print("saved", DST)
