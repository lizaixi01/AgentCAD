"""Base drawings for the second hard-task set (H4-H6), shared by run_hard.py and grade_hard.py.

H4  clean up a messy drawing: everything on layer 0 with explicit colours, duplicates, zero-length lines,
    empty junk layers; the agent moves it onto a layer standard.
H5  dimension an undimensioned part (holes, a slot, a chamfer) so it can be made.
H6  make a print sheet: an A3 layout with frame, title block and a 1:2 viewport onto the model-space part.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

# --- H4 ---------------------------------------------------------------------------------------------
H4_HOLES = [((20, 20), 6), ((180, 20), 6), ((20, 80), 6), ((180, 80), 6), ((100, 50), 20)]
H4_LAYERS = {"OUTLINE": (7, "CONTINUOUS", 50), "CENTER": (1, "CENTER", 25), "DIM": (3, "CONTINUOUS", 25),
             "TEXT": (4, "CONTINUOUS", 25)}
H4_JUNK_LAYERS = ("temp", "OLD_DIM", "Layer1")
H4_DIMS = [200, 100, 160, 40]
H4_TEXTS = ["技术要求", "MP-200"]


def _iso_dimstyle(doc) -> None:
    st = doc.styles.get("Standard")
    st.dxf.font, st.dxf.bigfont = "gbenor.shx", "gbcbig.shx"
    ds = doc.dimstyles.get("EZDXF")
    for k, v in {"dimtxt": 3.5, "dimasz": 2.5, "dimexo": 0.625, "dimexe": 1.25, "dimgap": 0.625, "dimtad": 1,
                 "dimdec": 0, "dimtxsty": "Standard", "dimlfac": 1.0, "dimtsz": 0.0, "dimblk": ""}.items():
        ds.dxf.set(k, v)


def make_h4_base(path: Path) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    _iso_dimstyle(doc)
    for name in H4_JUNK_LAYERS:
        doc.layers.add(name, color=2)
    msp = doc.modelspace()
    a = {"layer": "0", "color": 7}
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True, dxfattribs=a)
    for c, r in H4_HOLES:
        msp.add_circle(c, r, dxfattribs=a)
    msp.add_circle((180, 80), 6, dxfattribs=a)                                   # duplicate hole
    red = {"layer": "0", "color": 1}
    for (x, y), r in H4_HOLES:
        e = r + 4
        msp.add_line((x - e, y), (x + e, y), dxfattribs=red)
        msp.add_line((x, y - e), (x, y + e), dxfattribs=red)
    msp.add_line((0, 0), (200, 0), dxfattribs=a)                                  # duplicates of outline edges
    msp.add_line((200, 0), (200, 100), dxfattribs=a)
    msp.add_line((60, 10), (60, 10), dxfattribs=a)                                # zero-length
    msp.add_line((140, 90), (140, 90), dxfattribs=red)
    g = {"layer": "0", "color": 3}
    msp.add_linear_dim(base=(0, -15), p1=(0, 0), p2=(200, 0), dimstyle="EZDXF", dxfattribs=g).render()
    msp.add_linear_dim(base=(-15, 0), p1=(0, 0), p2=(0, 100), angle=90, dimstyle="EZDXF", dxfattribs=g).render()
    msp.add_linear_dim(base=(0, 112), p1=(20, 80), p2=(180, 80), dimstyle="EZDXF", dxfattribs=g).render()
    msp.add_diameter_dim(center=(100, 50), radius=20, angle=45, dimstyle="EZDXF", dxfattribs=g).render()
    c = {"layer": "0", "color": 4}
    msp.add_mtext("技术要求\\P未注倒角 C1", dxfattribs={**c, "char_height": 3.5, "insert": (0, -25)})
    msp.add_text("MP-200", height=5, dxfattribs={**c, "insert": (150, -30)})
    doc.saveas(path)


# --- H5 ---------------------------------------------------------------------------------------------
H5_OUTLINE = [(0, 0), (160, 0), (160, 80), (150, 90), (0, 90)]
H5_HOLES = [(25, 25), (135, 25)]
H5_HOLE_R = 7
H5_SLOT = ((66, 62), (94, 62), 6)   # arc centres and radius: overall 40 x 12, centred at (80, 62)


def make_h5_base(path: Path) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    _iso_dimstyle(doc)
    for name, color, lt in (("OUTLINE", 7, "Continuous"), ("CENTER", 1, "CENTER"), ("DIM", 3, "Continuous"),
                            ("TEXT", 7, "Continuous")):
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    o, cl = {"layer": "OUTLINE"}, {"layer": "CENTER"}
    msp.add_lwpolyline(H5_OUTLINE, close=True, dxfattribs=o)
    for x, y in H5_HOLES:
        msp.add_circle((x, y), H5_HOLE_R, dxfattribs=o)
        msp.add_line((x - 11, y), (x + 11, y), dxfattribs=cl)
        msp.add_line((x, y - 11), (x, y + 11), dxfattribs=cl)
    (x1, y), (x2, _), r = H5_SLOT
    msp.add_arc((x1, y), r, 90, 270, dxfattribs=o)
    msp.add_arc((x2, y), r, 270, 90, dxfattribs=o)
    msp.add_line((x1, y - r), (x2, y - r), dxfattribs=o)
    msp.add_line((x1, y + r), (x2, y + r), dxfattribs=o)
    msp.add_line((x1 - r - 4, y), (x2 + r + 4, y), dxfattribs=cl)
    for x in (x1, x2):
        msp.add_line((x, y - r - 4), (x, y + r + 4), dxfattribs=cl)
    msp.add_text("支架板 SB-160  材料 Q235  厚 8", height=5, dxfattribs={"layer": "TEXT", "insert": (0, -40)})
    doc.saveas(path)


# --- H6 ---------------------------------------------------------------------------------------------
H6_PART = (300, 160)      # plate size in model space, origin at (0, 0)


def make_h6_base(path: Path) -> None:
    """A fully dimensioned 300 x 160 plate in model space, no layouts besides the default empty Layout1."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    _iso_dimstyle(doc)
    for name, color, lt in (("OUTLINE", 7, "Continuous"), ("CENTER", 1, "CENTER"), ("DIM", 3, "Continuous")):
        doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    W, H = H6_PART
    o, d = {"layer": "OUTLINE"}, {"layer": "DIM"}
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs=o)
    holes = [(30, 30), (W - 30, 30), (30, H - 30), (W - 30, H - 30)]
    for c in holes:
        msp.add_circle(c, 9, dxfattribs=o)
    msp.add_circle((W / 2, H / 2), 40, dxfattribs=o)
    for x, y, e in [(*c, 13) for c in holes] + [(W / 2, H / 2, 46)]:
        msp.add_line((x - e, y), (x + e, y), dxfattribs={"layer": "CENTER"})
        msp.add_line((x, y - e), (x, y + e), dxfattribs={"layer": "CENTER"})
    msp.add_linear_dim(base=(0, -20), p1=(0, 0), p2=(W, 0), dimstyle="EZDXF", dxfattribs=d).render()
    msp.add_linear_dim(base=(-20, 0), p1=(0, 0), p2=(0, H), angle=90, dimstyle="EZDXF", dxfattribs=d).render()
    msp.add_linear_dim(base=(0, H + 15), p1=(30, H - 30), p2=(W - 30, H - 30), dimstyle="EZDXF",
                       dxfattribs=d).render()
    msp.add_diameter_dim(center=(W / 2, H / 2), radius=40, angle=45, dimstyle="EZDXF", dxfattribs=d).render()
    dd = msp.add_diameter_dim(center=holes[3], radius=9, angle=45, dimstyle="EZDXF", dxfattribs=d)
    dd.dimension.dxf.text = "4X <>"
    dd.render()
    doc.saveas(path)
