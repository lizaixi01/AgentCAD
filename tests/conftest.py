from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime

FIXTURES = Path(__file__).parent / "fixtures"

PLATE_SPEC = {
    "kind": "plate", "units": "mm", "name": "Mounting plate", "width": 100, "height": 60,
    "holes": [{"pattern": "corners", "diameter": 8, "edge_offset": 10}], "material": "Q235", "thickness": 3,
}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def rt(ws: Path) -> Runtime:
    return Runtime(Policy(root=ws))


@pytest.fixture
def plate(rt: Runtime) -> str:
    r = rt.draw_from_spec(PLATE_SPEC, "plate.dxf")
    assert r["ok"], r
    return "plate.dxf"


@pytest.fixture
def blank(rt: Runtime) -> str:
    r = rt.create_drawing("blank.dxf", units="mm")
    assert r["ok"], r
    return "blank.dxf"


def ok(r: dict) -> dict:
    assert r["ok"], json.dumps(r.get("error"), indent=1, default=str)
    return r


def reread(ws: Path, name: str):
    """Fresh, independent read of the file on disk."""
    return ezdxf.readfile(str(ws / name))


def by_tag(doc, tag):
    from agentcad.model import get_tag
    hits = [e for e in doc.modelspace() if get_tag(e) == tag]
    assert len(hits) == 1, f"tag {tag}: {len(hits)} hits"
    return hits[0]


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    """Minimal valid PDF (Helvetica, one text line per entry) without external dependencies."""
    objs: list[bytes] = []
    page_ids = []
    font_id = 3
    objs.append(b"")  # 1 catalog placeholder
    objs.append(b"")  # 2 pages placeholder
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for lines in pages:
        esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
        stream = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({t}) Tj T*" for t in esc) + " ET"
        data = stream.encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        content_id = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                    b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content_id, font_id))
        page_ids.append(len(objs))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % i for i in page_ids) + b"] /Count %d >>" % len(page_ids)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
