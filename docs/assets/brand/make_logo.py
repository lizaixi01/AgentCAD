"""Generate the AgentCAD logo SVGs: black marks on the inverse of a CAD red (#E6193C -> #19E6C3).

    python docs/assets/brand/make_logo.py docs/assets/brand      (needs matplotlib for the DejaVu fonts, and fonttools)
"""
import sys
from pathlib import Path

import matplotlib
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONTS = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
TEAL = "#19E6C3"   # 255 - (230, 25, 60): the inverse of a CAD red
INK = "#0A0A0A"


def text_path(text, font_file, size, x, y, tracking=0.0):
    """SVG path data for `text` with its baseline at (x, y); returns (d, advance width)."""
    font = TTFont(FONTS / font_file)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    d, cx = [], x
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, cx, y)))
        d.append(pen.getCommands())
        cx += gs[g].width * scale + tracking
    return " ".join(d), cx - x - tracking


def mark(x, y, s):
    """The 'A' mark in a tile of side s at (x, y): an A drawn as a sketch, with square grips at its points."""
    k = s / 512
    def p(px, py):
        return f"{x + px * k:.1f},{y + py * k:.1f}"
    w = 46 * k
    grip = 54 * k
    pts = [(256, 112), (140, 400), (372, 400)]
    body = (f'<path d="M{p(140, 400)} L{p(256, 112)} L{p(372, 400)} M{p(191, 274)} L{p(321, 274)}" '
            f'fill="none" stroke="{INK}" stroke-width="{w:.1f}" stroke-linecap="butt" stroke-linejoin="bevel"/>')
    grips = "".join(
        f'<rect x="{x + px * k - grip / 2:.1f}" y="{y + py * k - grip / 2:.1f}" width="{grip:.1f}" height="{grip:.1f}" '
        f'fill="{TEAL}" stroke="{INK}" stroke-width="{12 * k:.1f}"/>' for px, py in pts)
    return (f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{96 * k:.1f}" fill="{TEAL}"/>' + body + grips)


def svg(w, h, inner, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{title}"><title>{title}</title>{inner}</svg>\n')


# Mark alone (favicon, avatar, social preview)
(OUT / "logo-mark.svg").write_text(svg(512, 512, mark(0, 0, 512), "AgentCAD"), encoding="utf-8")

# Banner: teal plate, black mark (inverted tile) and black wordmark
H, size = 160, 84
agent, wa = text_path("Agent", "DejaVuSans.ttf", size, 0, 0, tracking=-1.5)
cad, wc = text_path("CAD", "DejaVuSans-Bold.ttf", size, 0, 0, tracking=-1.5)
pad, tile = 22, H - 44
tx = pad + tile + 30
W = int(tx + wa + 4 + wc + 40)
base = H / 2 + size * 0.36
agent, _ = text_path("Agent", "DejaVuSans.ttf", size, tx, base, tracking=-1.5)
cad, _ = text_path("CAD", "DejaVuSans-Bold.ttf", size, tx + wa + 4, base, tracking=-1.5)
inner = (f'<rect width="{W}" height="{H}" rx="28" fill="{TEAL}"/>'
         f'<rect x="{pad}" y="{(H - tile) / 2}" width="{tile}" height="{tile}" rx="{tile * 96 / 512:.1f}" fill="{INK}"/>'
         + mark(pad, (H - tile) / 2, tile).replace(f'fill="{TEAL}"/>', 'fill="none"/>', 1)
         .replace(f'stroke="{INK}"', 'stroke="#19E6C3"').replace(f'fill="{TEAL}" stroke', f'fill="{INK}" stroke')
         + f'<path d="{agent}" fill="{INK}"/><path d="{cad}" fill="{INK}"/>')
(OUT / "logo.svg").write_text(svg(W, H, inner, "AgentCAD"), encoding="utf-8")
print("banner", W, H)
