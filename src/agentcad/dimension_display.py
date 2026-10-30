"""Read the visible primary value from a saved DIMENSION graphics block.

Geometry and DIMLFAC are not evidence of what the drawing actually prints.
Ambiguous or missing graphics have no verified displayed value.
"""
from __future__ import annotations

import math
import re

from ezdxf.tools.text import plain_mtext

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", plain_mtext(text).replace("%%c", "Ø").replace("%%C", "Ø")
                  .replace("∅", "Ø").replace("%%d", "°")).strip()


def _visible(doc, entity):
    if entity.dxf.get("invisible", 0) or not doc.layers.has_entry(entity.dxf.layer):
        return False
    layer = doc.layers.get(entity.dxf.layer)
    return not layer.is_off() and not layer.is_frozen() and bool(layer.dxf.get("plot", 1))


def _number(text: str) -> float | None:
    """Primary decimal/scientific, architectural or fractional measurement."""
    text = re.sub(r"^(?:\d+\s*[xX×]\s*)?(?:Ø|⌀|R)?\s*", "", text)
    text = re.sub(r"\s*(?:mm|cm|m|in|ft|deg|°)\s*$", "", text).strip()
    # Architectural feet/inches are expressed in drawing inches after DIMLFAC.
    match = re.fullmatch(r"(?:(\d+)\s*'\s*-?\s*)?(\d+(?:\.\d*)?)(?:[ -]+(\d+)/(\d+))?\s*\"", text)
    if match:
        feet, inches, numerator, denominator = match.groups()
        if denominator and not int(denominator):
            return None
        return 12 * int(feet or 0) + float(inches) + (int(numerator) / int(denominator) if numerator else 0)
    match = re.fullmatch(r"(?:(\d+)\s+)?(\d+)/(\d+)", text)
    if match:
        whole, numerator, denominator = match.groups()
        return int(whole or 0) + int(numerator) / int(denominator) if int(denominator) else None
    match = re.fullmatch(NUMBER, text)
    return float(match.group()) if match else None


def read_display(dim) -> dict:
    doc = dim.doc
    result = {"value": None, "texts": [], "resolution": None, "status": "unverifiable",
              "scope": "visible primary measurement; not a certification of all note/tolerance text"}
    if doc is None or not _visible(doc, dim):
        return {**result, "status": "hidden"}
    block = doc.blocks.get(dim.dxf.get("geometry", ""))
    if block is None:
        return {**result, "status": "missing"}
    texts = [e for e in block if e.dxftype() in {"TEXT", "MTEXT"}]
    result["texts"] = [_plain(e.dxf.text if e.dxftype() == "TEXT" else e.text) for e in texts]
    if not texts:
        return {**result, "status": "missing"}
    heights = [e.dxf.get("height" if e.dxftype() == "TEXT" else "char_height", 0) for e in texts]
    if any(not _visible(doc, e) for e in texts) or any(not math.isfinite(h) or h <= 0 for h in heights):
        return {**result, "status": "hidden"}
    # Multiple independent text entities do not establish which is the primary
    # measurement; never pick the one closest to the expected geometry.
    if len(texts) != 1:
        return result
    override = dim.override()
    digits = override.get("dimdec", 2)
    angular = (dim.dxf.dimtype & 15) in {2, 5}
    if angular and override.get("dimadec", -1) >= 0:
        digits = override.get("dimadec")
    if not isinstance(digits, int) or not 0 <= digits <= 8:
        return result
    units = override.get("dimlunit", 2)
    result["resolution"] = 2.0 ** -digits if units in {4, 5} else 10.0 ** -digits
    rounding = override.get("dimrnd", 0)
    if not isinstance(rounding, (int, float)) or not math.isfinite(rounding) or rounding < 0:
        return result
    if not angular:
        result["resolution"] = max(result["resolution"], rounding)
    text = result["texts"][0]
    if override.get("dimtol", 0):
        raw = texts[0].dxf.text if texts[0].dxftype() == "TEXT" else texts[0].text
        if "\\S" in raw:
            text = _plain(raw.split("\\S", 1)[0])
        else:
            text = text.split("±", 1)[0].rstrip()
    # Remove known literal annotation prefixes/suffixes, including their digits
    # (e.g. M14 <> or <> H7). They are not the primary measured value.
    for template in (dim.dxf.get("text", "") or "<>", override.get("dimpost", "") or "<>"):
        if "<>" not in template:
            continue
        prefix, suffix = _plain(template).split("<>", 1)
        prefix, suffix = prefix.strip(), suffix.strip()
        if prefix:
            if not text.startswith(prefix):
                return result
            text = text[len(prefix):].lstrip()
        if suffix:
            if suffix not in text:
                return result
            text = text.split(suffix, 1)[0].rstrip()
    separator = override.get("dimdsep", ord("."))
    if isinstance(separator, int) and 0 < separator <= 0x10ffff:
        text = text.replace(chr(separator), ".")
    text = re.sub(r"\[[^\]]*\]", "", text)  # optional alternate units
    if override.get("dimlim", 0) and not override.get("dimtol", 0):
        tolerance_digits = override.get("dimtdec", digits)
        if not isinstance(tolerance_digits, int) or not 0 <= tolerance_digits <= 8:
            return result
        values = [float(n) for n in re.findall(NUMBER, text)]
        if len(values) != 2:
            return result
        upper = values[0] - override.get("dimtp", 0)
        lower = values[1] + override.get("dimtm", 0)
        if abs(upper - lower) > 10.0 ** -tolerance_digits:
            return result
        value = (upper + lower) / 2
        result["inferred_from_limits"] = values
    else:
        value = _number(text)
    if value is not None and math.isfinite(value):
        if units == 1 and value and not angular:
            result["resolution"] = max(result["resolution"], 10.0 ** (math.floor(math.log10(abs(value))) - digits))
        result.update(value=value, status="read")
    return result
