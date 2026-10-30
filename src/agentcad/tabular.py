"""Drawing text/attributes exported as data, never executable spreadsheet formulas."""

from __future__ import annotations

import csv
import re
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

from .errors import input_error

NUMBER = re.compile(r"^[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def value(text):
    if isinstance(text, str) and NUMBER.fullmatch(text) and sum(c.isdigit() for c in text) <= 15:
        number = float(text)
        if abs(number) < 1e100:
            return number
    return text


def drawing_rows(doc, table="entities"):
    if table == "pid_lines":
        from .engineering.pid import read

        columns = ["handle", "from_tag", "to_tag", "line_class", "line_number", "confidence"]
        return [columns] + [
            [row.get(key) if row.get(key) is not None else "" for key in columns]
            for row in read(doc)["line_list"]
        ]
    if table == "bom":
        from .engineering.records import get

        columns = ["item", "qty", "designation", "standard", "material", "mass"]
        groups = {}
        for e in doc.modelspace():
            attrs = {a.dxf.tag.upper(): a.dxf.text for a in getattr(e, "attribs", ())}
            record = get(e, "mech") or {}
            if record.get("role") == "part":
                key = (record["name"], "", record.get("material", ""), "")
            elif attrs.get("DESIGNATION") or attrs.get("PART"):
                name = attrs.get("DESIGNATION") or " ".join(filter(None, [attrs["PART"], attrs.get("SIZE")]))
                key = (name, attrs.get("STANDARD", ""), attrs.get("MATERIAL", ""), attrs.get("MASS", ""))
            else:
                continue
            groups[key] = groups.get(key, 0) + 1
        return [columns] + [
            [i, count, *[value(v) if j == 3 else v for j, v in enumerate(key)]]
            for i, (key, count) in enumerate(groups.items(), 1)
        ]
    if table != "entities":
        raise input_error("INVALID_TABLE", "Table must be entities, pid_lines or bom")
    rows = [["handle", "type", "field", "value"]]
    for space in doc.layouts:
        for e in space:
            if e.dxftype() in {"TEXT", "MTEXT"}:
                rows.append(
                    [
                        e.dxf.handle,
                        e.dxftype(),
                        "text",
                        value(e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()),
                    ]
                )
            elif e.dxftype() == "INSERT":
                for a in e.attribs:
                    rows.append([e.dxf.handle, "INSERT", a.dxf.tag, value(a.dxf.text)])
    return rows


def csv_cell(item):
    if isinstance(item, str) and (
        item.lstrip().startswith(("=", "+", "-", "@")) or item.startswith(("\t", "\r", "\n"))
    ):
        return "'" + item
    return item


def write_table(path, fmt, rows):
    if fmt == "csv":
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows([[csv_cell(v) for v in row] for row in rows])
        return
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = [f'<worksheet xmlns="{ns}"><sheetData>']
    for index, row in enumerate(rows, 1):
        sheet.append(f'<row r="{index}">')
        for col, item in enumerate(row):
            # The supported engineering tables have at most six columns.
            cell = f"{chr(65 + col)}{index}"
            if isinstance(item, (int, float)):
                sheet.append(f'<c r="{cell}" t="n"><v>{item}</v></c>')
            else:
                text = re.sub(r"_x[0-9a-fA-F]{4}_", lambda m: "_x005F_" + m.group()[1:], str(item))
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", lambda m: f"_x{ord(m.group()):04X}_", text)
                sheet.append(
                    f'<c r="{cell}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
                )
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        relns = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
        prefix = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        z.writestr(
            "_rels/.rels",
            f'<Relationships {relns}><Relationship Id="rId1" Type="{prefix}officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="{prefix[:-1]}"><sheets><sheet name="Drawing" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships {relns}><Relationship Id="rId1" Type="{prefix}worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr("xl/worksheets/sheet1.xml", "".join(sheet))
