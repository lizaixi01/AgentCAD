"""Plot to PDF without external software.

ezdxf's drawing add-on renders each layout (text becomes filled glyph outlines, viewports show model space) into a
recorder; the recording is placed on the sheet and replayed into a minimal vector PDF writer below. PyMuPDF would
do the writing too, but it is AGPL.

Placement: a paper-space layout prints 1:1 on its own sheet (paper space is in mm). Model space prints at
``scale`` paper mm per drawing unit (the same convention as add_viewport: 0.5 = 1:2 for a mm drawing), centred on
the sheet, or scaled to fit the sheet inside a margin when no scale is given.
"""
from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any, Iterable

from ezdxf.addons.drawing import RenderContext, recorder
from ezdxf.addons.drawing.backend import BackendInterface
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.math import Matrix44, Vec2
from ezdxf.path import Command

from .errors import input_error
from .drawing_frontend import DrawingFrontend
from .model import is_model
from .ops.sheet import PAPER

PT = 72.0 / 25.4  # PDF points per mm
MARGIN = 10.0  # mm around fitted model space
MIN_LINEWEIGHT = 0.13  # mm; thinner strokes vanish in print


def _n(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


class _PdfPage(BackendInterface):
    """Collects one page's content stream (PDF coordinates: points, origin bottom-left)."""

    def __init__(self) -> None:
        self.ops: list[str] = []
        self._stroke = self._fill = self._width = None

    def _color(self, color: str, op: str) -> bool:
        if len(color) >= 9 and color[7:9].lower() == "00":
            return False  # fully transparent
        rgb = " ".join(_n(int(color[i:i + 2], 16) / 255) for i in (1, 3, 5))
        key = "_stroke" if op == "RG" else "_fill"
        if getattr(self, key) != rgb:
            self.ops.append(f"{rgb} {op}")
            setattr(self, key, rgb)
        return True

    def _stroke_props(self, props) -> bool:
        if not self._color(props.color, "RG"):
            return False
        w = _n(max(props.lineweight, MIN_LINEWEIGHT) * PT)
        if self._width != w:
            self.ops.append(f"{w} w")
            self._width = w
        return True

    @staticmethod
    def _poly(points: Iterable[Vec2], close: bool) -> str:
        pts = list(points)
        if len(pts) < 2:
            return ""
        s = [f"{_n(pts[0].x)} {_n(pts[0].y)} m"] + [f"{_n(p.x)} {_n(p.y)} l" for p in pts[1:]]
        return " ".join(s + (["h"] if close else []))

    @staticmethod
    def _path(path, close: bool) -> str:
        if len(path) == 0:
            return ""
        cur = path.start
        s = [f"{_n(cur.x)} {_n(cur.y)} m"]
        for cmd in path.commands():
            e = cmd.end
            if cmd.type == Command.MOVE_TO:
                if close:
                    s.append("h")
                s.append(f"{_n(e.x)} {_n(e.y)} m")
            elif cmd.type == Command.LINE_TO:
                s.append(f"{_n(e.x)} {_n(e.y)} l")
            elif cmd.type == Command.CURVE3_TO:  # quadratic -> cubic
                c1 = cur + (cmd.ctrl - cur) * (2 / 3)
                c2 = e + (cmd.ctrl - e) * (2 / 3)
                s.append(f"{_n(c1.x)} {_n(c1.y)} {_n(c2.x)} {_n(c2.y)} {_n(e.x)} {_n(e.y)} c")
            else:
                c1, c2 = cmd.ctrl1, cmd.ctrl2
                s.append(f"{_n(c1.x)} {_n(c1.y)} {_n(c2.x)} {_n(c2.y)} {_n(e.x)} {_n(e.y)} c")
            cur = e
        if close:
            s.append("h")
        return " ".join(s)

    def _emit_stroke(self, d: str, props) -> None:
        if d and self._stroke_props(props):
            self.ops.append(d + " S")

    def _emit_fill(self, d: str, props) -> None:
        if d and self._color(props.color, "rg"):
            self.ops.append(d + " f*")

    # BackendInterface ---------------------------------------------------------------------
    def draw_point(self, pos, properties) -> None:
        self._emit_stroke(f"{_n(pos.x)} {_n(pos.y)} m {_n(pos.x)} {_n(pos.y)} l", properties)

    def draw_line(self, start, end, properties) -> None:
        self._emit_stroke(self._poly([start, end], False), properties)

    def draw_solid_lines(self, lines, properties) -> None:
        self._emit_stroke(" ".join(self._poly([a, b], False) for a, b in lines), properties)

    def draw_path(self, path, properties) -> None:
        self._emit_stroke(self._path(path, False), properties)

    def draw_filled_paths(self, paths, properties) -> None:
        self._emit_fill(" ".join(d for d in (self._path(p, True) for p in paths) if d), properties)

    def draw_filled_polygon(self, points, properties) -> None:
        self._emit_fill(self._poly(points.vertices(), True), properties)

    def draw_image(self, image_data, properties) -> None:
        pass  # raster images are not plotted

    def configure(self, config) -> None:
        pass

    def set_background(self, color) -> None:
        pass  # always white paper

    def enter_entity(self, entity, properties) -> None:
        pass

    def exit_entity(self, entity) -> None:
        pass

    def clear(self) -> None:
        self.ops.clear()

    def finalize(self) -> None:
        pass


def write_pdf(pages: list[tuple[float, float, str]], out: Path, title: str) -> int:
    """pages: (width_pt, height_pt, content stream). Returns the file size."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"")  # 1: catalog, filled in below
    add(b"")  # 2: page tree
    kids = []
    for w, h, content in pages:
        data = zlib.compress(content.encode("latin-1"))
        cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_n(w)} {_n(h)}] /Contents {cid} 0 R "
                        f"/Resources << >> >>".encode()))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    safe = "".join(c if 32 <= ord(c) < 127 and c not in "()\\" else "_" for c in title)
    info = add(f"<< /Producer (AgentCAD) /Title ({safe}) >>".encode())
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    buf += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    buf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".agentcad-tmp")
    tmp.write_bytes(bytes(buf))
    tmp.replace(out)
    return len(buf)


def _sheet(paper: str | None, orientation: str, need: tuple[float, float] | None, wide: bool) -> tuple[float, float]:
    """Paper size in mm. paper=None/'auto': the smallest ISO A sheet that holds ``need`` (content size in mm on
    paper) inside the margin, or exactly (a drawing frame of that sheet's size); A3 when fitting."""
    def orient(w: float, h: float) -> tuple[float, float]:
        land = wide if orientation == "auto" else orientation == "landscape"
        return (max(w, h), min(w, h)) if land else (min(w, h), max(w, h))
    if paper and paper != "auto":
        if paper not in PAPER:
            raise input_error("UNKNOWN_PAPER", f"Unknown paper {paper!r}", hint=f"Use one of {list(PAPER)} or 'auto'")
        return orient(*PAPER[paper])
    if need is None:
        return orient(*PAPER["A3"])
    for name in ("A4", "A3", "A2", "A1", "A0"):
        w, h = orient(*PAPER[name])
        if need[0] + 2 * MARGIN <= w + 1e-6 and need[1] + 2 * MARGIN <= h + 1e-6:
            return w, h
        if w * 0.95 <= need[0] <= w + 0.5 and h * 0.95 <= need[1] <= h + 0.5:
            return w, h
    raise input_error("PLOT_TOO_LARGE", f"At this scale the drawing is {need[0]:.0f} x {need[1]:.0f} mm, more "
                      "than A0", hint="Use a smaller scale, or omit scale to fit the sheet")


def _ratio(s: float) -> str:
    return f"1:{1 / s:g}" if s < 1 else f"{s:g}:1"


def _layout_paper(lay) -> tuple[float, float, float, float] | None:
    """(x0, y0, width, height) of a paper-space sheet in paper units, or None when the layout has no page setup."""
    d = lay.dxf
    w, h = d.get("paper_width", 0) or 0, d.get("paper_height", 0) or 0
    if w <= 0 or h <= 0:
        return None
    if d.get("plot_rotation", 0) in (1, 3):
        w, h = h, w
    return -(d.get("left_margin", 0) or 0), -(d.get("bottom_margin", 0) or 0), w, h


CJK_FONTS = ("msyh.ttc", "simsun.ttc", "simhei.ttf", "NotoSansCJK-Regular.ttc", "wqy-microhei.ttc")
# ISO 5455 scales, largest first; 'fit' picks the largest that fits the sheet
STANDARD_SCALES = (50, 20, 10, 5, 2, 1, 1 / 2, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100, 1 / 200, 1 / 500, 1 / 1000,
                   1 / 2000, 1 / 5000, 1 / 10000)


def _cjk_face(doc) -> str | None:
    """The CJK TrueType font SHX styles are plotted with, or None when the drawing's text is all ASCII (or no CJK
    font is installed)."""
    def texts():
        for lay in [doc.modelspace(), *doc.layouts, *doc.blocks]:
            for e in lay.query("TEXT MTEXT ATTRIB ATTDEF"):
                yield e.dxf.get("text", "") if e.dxftype() != "MTEXT" else e.text
    if all(str(t).isascii() for t in texts()):
        return None
    from ezdxf.fonts import fonts
    return next((f for f in CJK_FONTS if fonts.font_manager.has_font(f)), None)


def _plotted_with_cjk(st) -> bool:
    return str(st.dxf.get("font", "")).lower().endswith(".shx") or bool(st.dxf.get("bigfont"))


def _cjk_styles(doc) -> str | None:
    """SHX fonts (gbenor/gbcbig) are rarely resolvable outside AutoCAD and the fallback has no CJK glyphs, so
    Chinese text came out as boxes. When the drawing has non-ASCII text, plot SHX styles with a CJK TrueType font.
    Only the in-memory copy being plotted is changed."""
    face = _cjk_face(doc)
    if face is None:
        return None
    for st in doc.styles:
        if _plotted_with_cjk(st):
            st.dxf.font = face
            st.dxf.discard("bigfont")
    return face


def plot_fonts(doc) -> dict[str, str]:
    """Text style name (lower case) -> the font file the plot draws it with, without changing the drawing."""
    face = _cjk_face(doc)
    return {st.dxf.name.lower(): face if face and _plotted_with_cjk(st) else str(st.dxf.get("font", "") or "txt")
            for st in doc.styles}


def font_cmap(font: str) -> set[int] | None:
    """Code points the plotted font has glyphs for; None for fonts that are not TrueType (SHX, LFF), which are not
    checked. A font that is not installed resolves to ezdxf's fallback, as it does when plotting."""
    from ezdxf.fonts import fonts
    try:
        f = fonts.make_font(font, 1.0)
        return set(f.glyph_cache.cmap) if isinstance(f, fonts.TrueTypeFont) else None
    except Exception:  # an unreadable font file: the plot falls back too, nothing reliable to report
        return None


def _render(doc, name: str, monochrome: bool):
    lay = doc.modelspace() if is_model(name) else doc.layouts.get(name)
    ctb = "" if is_model(name) else lay.dxf_layout.dxf.get("current_style_sheet", "")
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                        color_policy=ColorPolicy.BLACK if monochrome or ctb == "monochrome.ctb" else ColorPolicy.COLOR)
    rec = recorder.Recorder()
    DrawingFrontend(RenderContext(doc), rec, config=cfg).draw_layout(lay, finalize=True)
    return lay, rec.player()


def plot_pdf(doc, out: Path, layouts: list[str], *, paper: str | None = None, orientation: str = "auto",
             scale: float | None = None, monochrome: bool = False, title: str = "") -> dict[str, Any]:
    font = _cjk_styles(doc)
    pages, report = [], []
    for name in layouts:
        lay, player = _render(doc, name, monochrome)
        box = player.bbox()
        info: dict[str, Any] = {"layout": "Model" if is_model(name) else name}
        sheet = None if is_model(name) or paper not in (None, "auto") or scale else _layout_paper(lay)
        if sheet:  # paper space 1:1 on its own sheet
            x0, y0, w, h = sheet
            s = 1.0
            m = Matrix44.translate(-x0, -y0, 0)
            info["placement"] = "layout page setup"
        else:
            if not box.has_data:
                w, h = _sheet(paper, orientation, None, True)
                s, m = 1.0, Matrix44()
            else:
                size, center = box.size, box.center
                wide = size.x >= size.y
                if scale:
                    s = float(scale)
                    w, h = _sheet(paper, orientation, (size.x * s, size.y * s), wide)
                else:
                    w, h = _sheet(paper, orientation, None, wide)
                    fit = min((w - 2 * MARGIN) / max(size.x, 1e-9), (h - 2 * MARGIN) / max(size.y, 1e-9))
                    s = next((k for k in STANDARD_SCALES if k <= fit + 1e-9), fit)
                m = Matrix44.chain(Matrix44.translate(-center.x, -center.y, 0), Matrix44.scale(s, s, 1),
                                   Matrix44.translate(w / 2, h / 2, 0))
            info["placement"] = "scale" if scale else "fit"
        player.transform(Matrix44.chain(m, Matrix44.scale(PT, PT, 1)))
        placed = player.bbox()
        clipped = placed.has_data and (placed.extmin.x < -0.01 or placed.extmin.y < -0.01
                                       or placed.extmax.x > w * PT + 0.01 or placed.extmax.y > h * PT + 0.01)
        if clipped:
            player.crop_rect(Vec2(0, 0), Vec2(w * PT, h * PT), 0.1 * PT)
        page = _PdfPage()
        player.replay(page)
        pages.append((w * PT, h * PT, "1 J 1 j\n" + "\n".join(page.ops)))
        info.update({"paper_mm": [round(w, 1), round(h, 1)], "scale": round(s, 6), "scale_text": _ratio(s),
                     "empty": not box.has_data})
        if clipped:
            info["clipped"] = True
        report.append(info)
    size = write_pdf(pages, out, title)
    res: dict[str, Any] = {"pages": report, "bytes": size}
    if font:
        res["font_substitution"] = f"SHX text styles plotted with {font}"
    return res


SUPERSAMPLE = 2  # PNG previews are drawn at twice the size and scaled down, so thin lines and text stay legible


class _PngCanvas(BackendInterface):
    """Draws the recorded plot into a Pillow image (pixel coordinates, origin top-left)."""

    def __init__(self, image) -> None:
        from PIL import ImageDraw
        self.image = image
        self.draw = ImageDraw.Draw(image)

    @staticmethod
    def _rgb(color: str) -> tuple[int, int, int] | None:
        if len(color) >= 9 and color[7:9].lower() == "00":
            return None  # fully transparent
        return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

    @staticmethod
    def _width(props) -> int:
        return SUPERSAMPLE * (2 if props.lineweight >= 0.4 else 1)

    @staticmethod
    def _subpaths(path) -> list[list[tuple[float, float]]]:
        return [[(v.x, v.y) for v in sp.flattening(0.25 * SUPERSAMPLE)] for sp in path.sub_paths() if len(sp)]

    def _lines(self, pts, props) -> None:
        if (rgb := self._rgb(props.color)) and len(pts) >= 2:
            self.draw.line(pts, fill=rgb, width=self._width(props), joint="curve")

    def _fill(self, polys, props) -> None:
        """Even-odd fill like the PDF's f*, so the counters of glyphs ('o', '口') stay open."""
        from PIL import Image, ImageChops, ImageDraw
        rgb = self._rgb(props.color)
        polys = [p for p in polys if len(p) >= 3]
        if not rgb or not polys:
            return
        xs = [x for p in polys for x, _ in p]
        ys = [y for p in polys for _, y in p]
        x0, y0 = max(int(min(xs)) - 1, 0), max(int(min(ys)) - 1, 0)
        x1, y1 = min(int(max(xs)) + 2, self.image.width), min(int(max(ys)) + 2, self.image.height)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("1", (x1 - x0, y1 - y0), 0)
        for p in polys:
            one = Image.new("1", mask.size, 0)
            ImageDraw.Draw(one).polygon([(x - x0, y - y0) for x, y in p], fill=1)
            mask = ImageChops.logical_xor(mask, one)
        self.image.paste(rgb, (x0, y0, x1, y1), mask)

    def draw_point(self, pos, properties) -> None:
        if rgb := self._rgb(properties.color):
            self.draw.point((pos.x, pos.y), fill=rgb)

    def draw_line(self, start, end, properties) -> None:
        self._lines([(start.x, start.y), (end.x, end.y)], properties)

    def draw_solid_lines(self, lines, properties) -> None:
        for a, b in lines:
            self.draw_line(a, b, properties)

    def draw_path(self, path, properties) -> None:
        for sp in self._subpaths(path):
            self._lines(sp, properties)

    def draw_filled_paths(self, paths, properties) -> None:
        self._fill([sp for p in paths for sp in self._subpaths(p)], properties)

    def draw_filled_polygon(self, points, properties) -> None:
        self._fill([[(v.x, v.y) for v in points.vertices()]], properties)

    def draw_image(self, image_data, properties) -> None:
        pass  # raster images are not plotted

    def configure(self, config) -> None:
        pass

    def set_background(self, color) -> None:
        pass  # always white paper

    def enter_entity(self, entity, properties) -> None:
        pass

    def exit_entity(self, entity) -> None:
        pass

    def clear(self) -> None:
        pass

    def finalize(self) -> None:
        pass


def plot_png(doc, out: Path, layout: str, *, size: int = 1600, monochrome: bool = False) -> dict[str, Any]:
    """Raster preview of one layout, drawn like the PDF plot (same fonts, colours and line types), its longer
    side ``size`` pixels. For an agent to look at what it drew: no fixed scale, do not measure pixels."""
    from PIL import Image
    font = _cjk_styles(doc)
    _, player = _render(doc, layout, monochrome)
    box = player.bbox()
    big = size * SUPERSAMPLE
    if box.has_data:
        sx, sy = max(box.size.x, 1e-9), max(box.size.y, 1e-9)
        margin = 0.02 * big
        s = (big - 2 * margin) / max(sx, sy)
        w, h = max(round(sx * s + 2 * margin), 1), max(round(sy * s + 2 * margin), 1)
        # y up in the drawing, down in the image
        player.transform(Matrix44.chain(Matrix44.translate(-box.extmin.x, -box.extmax.y, 0),
                                        Matrix44.scale(s, -s, 1), Matrix44.translate(margin, margin, 0)))
    else:
        w = h = big
        s = 0.0
    image = Image.new("RGB", (w, h), (255, 255, 255))
    if box.has_data:
        player.replay(_PngCanvas(image))
    image = image.resize((max(w // SUPERSAMPLE, 1), max(h // SUPERSAMPLE, 1)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".agentcad-tmp")
    image.save(tmp, format="PNG")
    tmp.replace(out)
    res: dict[str, Any] = {"layout": "Model" if is_model(layout) else layout, "pixels": list(image.size),
                           "empty": not box.has_data, "bytes": out.stat().st_size}
    if font:
        res["font_substitution"] = f"SHX text styles plotted with {font}"
    return res
