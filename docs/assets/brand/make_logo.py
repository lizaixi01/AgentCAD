"""Generate the AgentCAD logo SVGs: the layout of a CAD app icon with its colors inverted (white on red ->
black on cyan). Letters are DejaVu Sans Bold outlines, not any vendor's artwork.

    python docs/assets/brand/make_logo.py docs/assets/brand      (needs matplotlib for the DejaVu fonts, and fonttools)
"""
import sys
from pathlib import Path

import matplotlib
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONTS = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
TILE_TOP, TILE_BOTTOM = "#19F0D2", "#0FCDB0"   # inverse of a red tile
TAB = "#63F2DA"                                # inverse of its darker red tab
INK = "#000000"                                # inverse of white letters


def text_path(text, font_file, size, x, y, tracking=0.0):
    """Path data for `text` with its baseline at (x, y); returns (d, width, cap height)."""
    font = TTFont(FONTS / font_file)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    d, cx, top = [], x, 0.0
    for ch in text:
        g = gs[cmap[ord(ch)]]
        pen = SVGPathPen(gs)
        g.draw(TransformPen(pen, (scale, 0, 0, -scale, cx, y)))
        d.append(pen.getCommands())
        b = BoundsPen(gs)
        g.draw(b)
        if b.bounds:
            top = max(top, b.bounds[3] * scale)
        cx += g.width * scale + tracking
    return " ".join(d), cx - x - tracking, top


def mark(x, y, s, uid="m"):
    """App-icon mark of side s at (x, y): a big A on the tile and a CAD tab in the lower left."""
    k = s / 512
    r = 72 * k
    defs = (f'<defs><linearGradient id="{uid}g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{TILE_TOP}"/><stop offset="1" stop-color="{TILE_BOTTOM}"/>'
            f'</linearGradient><clipPath id="{uid}c"><rect x="{x}" y="{y}" width="{s}" height="{s}" '
            f'rx="{r:.1f}"/></clipPath></defs>')
    tile = f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{r:.1f}" fill="url(#{uid}g)"/>'
    size = 400 * k
    _, wa, ta = text_path("A", "DejaVuSans-Bold.ttf", size, 0, 0)
    a, _, _ = text_path("A", "DejaVuSans-Bold.ttf", size, x + 300 * k - wa / 2, y + 60 * k + ta)
    tx, ty, tw, th = x, y + 330 * k, 300 * k, 182 * k
    tab = f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" fill="{TAB}" clip-path="url(#{uid}c)"/>'
    csize = 104 * k
    _, wc, tc = text_path("CAD", "DejaVuSans-Bold.ttf", csize, 0, 0, tracking=-2 * k)
    cad, _, _ = text_path("CAD", "DejaVuSans-Bold.ttf", csize, tx + (tw - wc) / 2, ty + (th + tc) / 2,
                          tracking=-2 * k)
    return defs + tile + f'<path d="{a}" fill="{INK}"/>' + tab + f'<path d="{cad}" fill="{INK}"/>'


def svg(w, h, inner, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" role="img" aria-label="{title}"><title>{title}</title>{inner}</svg>\n')


(OUT / "logo-mark.svg").write_text(svg(512, 512, mark(0, 0, 512), "AgentCAD"), encoding="utf-8")

# Lockups: mark + wordmark, dark ink for light backgrounds and light ink for dark ones
H, size = 160, 92
_, wa, top = text_path("Agent", "DejaVuSans.ttf", size, 0, 0, tracking=-1.5)
_, wc, _ = text_path("CAD", "DejaVuSans-Bold.ttf", size, 0, 0, tracking=-1.5)
tx, base = H + 32, H / 2 + top / 2
W = tx + wa + 6 + wc + 8
for name, ink in (("logo.svg", "#1F2328"), ("logo-dark.svg", "#F0F6FC")):
    agent, _, _ = text_path("Agent", "DejaVuSans.ttf", size, tx, base, tracking=-1.5)
    cad, _, _ = text_path("CAD", "DejaVuSans-Bold.ttf", size, tx + wa + 6, base, tracking=-1.5)
    inner = mark(0, 0, H, uid="l") + f'<path d="{agent}" fill="{ink}"/><path d="{cad}" fill="{ink}"/>'
    (OUT / name).write_text(svg(W, H, inner, "AgentCAD"), encoding="utf-8")
print("lockup", round(W), H)
