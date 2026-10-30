"""Read delivery artifacts independently; reject corruption and lost drawing data.

DXF keeps all layouts, block definitions, attributes, styles and native metadata.
JSON/CSV/XLSX compare their documented projection of the frozen source. PDF/SVG
checks are structural print checks, not a claim of pixel or full CAD equivalence.
"""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ezdxf.lldxf.tagwriter import TagCollector

from .errors import AgentCADError
from .guards import fingerprint
from .metadata import all_meta
from .model import entity_to_dict
from .policy import Policy
from .store import read_dxf
from .tabular import csv_cell, drawing_rows
from .units import unit_from_insunits


def _tags(entity) -> list:
    return [(t.code, str(t.value)) for t in TagCollector.dxftags(entity)]


def dxf_snapshot(doc) -> dict[str, Any]:
    """Handle identity and DXF tags include geometry, XDATA, appearance and links."""
    return {
        "units": doc.header.get("$INSUNITS", 0),
        "header": {k: doc.header[k] for k in doc.header.varnames() if k.startswith("$DIM") or k in {
            "$LUNITS", "$LUPREC", "$AUNITS", "$AUPREC", "$MEASUREMENT", "$INSBASE",
            "$MIRRTEXT", "$LTSCALE", "$CELTSCALE", "$PSLTSCALE"}},
        "metadata": all_meta(doc),
        "layouts": {s.name: {e.dxf.handle: fingerprint(e) for e in s} for s in doc.layouts},
        "blocks": {b.name: {"entities": {e.dxf.handle: fingerprint(e) for e in b},
                             "definition": _tags(b.block), "record": _tags(b.block_record)} for b in doc.blocks},
        "styles": {name: {e.dxf.name: _tags(e) for e in getattr(doc, name)}
                   for name in ("layers", "linetypes", "styles", "dimstyles")},
        # finalize() refreshes derived extents; page setup, origins, scales and links must survive.
        "pages": {s.name: {k: v for k, v in s.dxf_layout.dxf.all_existing_dxf_attribs().items()
                           if k not in {"extmin", "extmax"}} for s in doc.layouts},
    }


def _xlsx_rows(path: Path) -> list[list[Any]]:
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    def unescape(value):
        # One pass: an escaped literal _x0041_ must not become A.
        return re.sub(r"_x([0-9a-fA-F]{4})_", lambda m: chr(int(m[1], 16)), value)
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("XLSX checksum failure")
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for required in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"):
            ET.fromstring(archive.read(required))
        rows = []
        for index, row in enumerate(sheet.findall("s:sheetData/s:row", ns), 1):
            if row.get("r") != str(index):
                raise ValueError("XLSX row position differs from source")
            values = []
            for col, cell in enumerate(row.findall("s:c", ns)):
                if cell.get("r") != f"{chr(65 + col)}{index}":
                    raise ValueError("XLSX cell position differs from source")
                if cell.find("s:f", ns) is not None:
                    raise ValueError("Exported cells must not contain formulas")
                if cell.get("t") == "inlineStr":
                    values.append(unescape(cell.findtext("s:is/s:t", "", ns)))
                elif cell.get("t") == "n":
                    values.append(float(cell.findtext("s:v", "", ns)))
                else:
                    raise ValueError("Unexpected XLSX cell representation")
            rows.append(values)
        return rows


def verify_artifact(doc, target: Path, fmt: str, exported: dict) -> dict[str, Any]:
    try:
        if fmt == "dxf":
            actual = read_dxf(target, Policy(root=target.parent))
            expected, observed = dxf_snapshot(doc), dxf_snapshot(actual)
            changed = [key for key in expected if expected[key] != observed[key]]
            if changed:
                raise ValueError("DXF parity mismatch: " + ", ".join(changed))
            if actual.audit().errors:
                raise ValueError("DXF structural audit failed")
            return {"check": "dxf_layout_block_style_metadata_parity", "passed": True,
                    "layouts": len(expected["layouts"]), "blocks": len(expected["blocks"])}
        if fmt == "json":
            expected = {"units": unit_from_insunits(doc.header.get("$INSUNITS", 0)),
                        "metadata": all_meta(doc), "entities": [entity_to_dict(e) for e in doc.modelspace()]}
            if json.loads(target.read_text("utf-8")) != json.loads(json.dumps(expected)):
                raise ValueError("JSON drawing projection differs from source")
        elif fmt in {"csv", "xlsx"}:
            expected = drawing_rows(doc)
            if fmt == "csv":
                with target.open(encoding="utf-8-sig", newline="") as stream:
                    actual = list(csv.reader(stream))
                expected = [[str(csv_cell(v)) for v in row] for row in expected]
            else:
                actual = _xlsx_rows(target)
            if actual != expected:
                raise ValueError(f"{fmt.upper()} cells differ from source")
        elif fmt == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(target, strict=True)
            pages = exported["pages"]
            if len(reader.pages) != len(pages) or not pages:
                raise ValueError("PDF page count mismatch")
            for page, info in zip(reader.pages, pages):
                dims = [float(page.mediabox.width), float(page.mediabox.height)]
                if any(not math.isfinite(v) or abs(v - mm * 72 / 25.4) > 0.3
                       for v, mm in zip(dims, info["paper_mm"])):
                    raise ValueError("PDF MediaBox mismatch")
                content = page.get_contents()
                operations = [] if content is None else content.operations
                if not info["empty"] and not any(op in (b"S", b"s", b"f", b"f*", b"B", b"B*", b"Do")
                                                 for _, op in operations):
                    raise ValueError("PDF lost rendered drawing content")
                if info.get("clipped"):
                    raise ValueError("PDF drawing extends outside its page")
            return {"check": "pdf_pages_mediabox_content", "passed": True, "pages": len(pages),
                    "scope": "structural print validation; not full geometry parity"}
        elif fmt == "svg":
            root = ET.parse(target).getroot()
            box = [float(v) for v in root.get("viewBox", "").split()]
            if (root.tag != "{http://www.w3.org/2000/svg}svg" or len(box) != 4
                    or not all(math.isfinite(v) for v in box) or min(box[2:]) <= 0):
                raise ValueError("Invalid SVG root or viewBox")
            geometry = sum(e.tag.rsplit("}", 1)[-1] in {"path", "line", "polyline", "polygon", "circle", "text"}
                           for e in root.iter())
            if len(doc.modelspace()) and not geometry:
                raise ValueError("SVG has no drawing content")
            return {"check": "svg_xml_viewbox_content", "passed": True,
                    "scope": "structural preview validation; model space only"}
        else:
            raise ValueError("Unknown delivery format")
        return {"check": f"{fmt}_source_projection_parity", "passed": True}
    except Exception as exc:
        raise AgentCADError("DELIVERY_PARITY_FAILED", f"{target.name}: {exc}", category="validation",
                            details={"format": fmt, "artifact": target.name}) from exc
