"""Explicit length units.

Drawings carry their unit in the DXF header ``$INSUNITS``. Operations either
use bare numbers (interpreted in the drawing unit) or strings such as
``"8mm"`` / ``"0.5 in"`` which are converted explicitly. A plan that declares a
unit different from the drawing's is rejected unless conversion is requested.
"""
from __future__ import annotations

import re
from typing import Any

from .errors import input_error

# name -> (DXF $INSUNITS code, millimetres per unit)
UNITS: dict[str, tuple[int, float]] = {
    "mm": (4, 1.0),
    "cm": (5, 10.0),
    "m": (6, 1000.0),
    "in": (1, 25.4),
    "ft": (2, 304.8),
}
ALIASES = {
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "毫米": "mm",
    "centimeter": "cm", "centimeters": "cm", "厘米": "cm",
    "meter": "m", "meters": "m", "metre": "m", "米": "m",
    "inch": "in", "inches": "in", '"': "in", "英寸": "in",
    "foot": "ft", "feet": "ft", "'": "ft", "英尺": "ft",
}
CODE_TO_UNIT = {code: name for name, (code, _) in UNITS.items()}

_LEN_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([a-zA-Z\"'一-鿿]*)\s*$")


def normalize_unit(name: str | None) -> str | None:
    if name is None:
        return None
    n = name.strip().lower()
    n = ALIASES.get(n, n)
    if n not in UNITS:
        raise input_error("UNKNOWN_UNIT", f"Unknown length unit {name!r}",
                          hint=f"Use one of {sorted(UNITS)}")
    return n


def convert(value: float, src: str, dst: str) -> float:
    if src == dst:
        return value
    return value * UNITS[src][1] / UNITS[dst][1]


def unit_from_insunits(code: int) -> str | None:
    return CODE_TO_UNIT.get(int(code))


def parse_length(value: Any, drawing_unit: str | None, field: str = "value") -> float:
    """Parse a number or a ``"<num><unit>"`` string into drawing units."""
    if isinstance(value, bool):
        raise input_error("INVALID_NUMBER", f"{field}: boolean is not a length")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _LEN_RE.match(value)
        if not m:
            raise input_error("INVALID_LENGTH", f"{field}: cannot parse length {value!r}",
                              hint="Use a number or a string like '8mm' / '0.5in'")
        num = float(m.group(1))
        unit = m.group(2)
        if not unit:
            return num
        u = normalize_unit(unit)
        if drawing_unit is None:
            raise input_error("UNITS_UNDEFINED",
                              f"{field}: drawing has no unit, cannot convert {value!r}",
                              hint="Create the drawing with an explicit unit")
        return convert(num, u, drawing_unit)
    raise input_error("INVALID_LENGTH", f"{field}: expected number or length string, got {type(value).__name__}")
