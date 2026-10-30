"""Verified ISO limit deviations for a bounded set of common fit classes.

Numeric facts checked against SKF PUB BU/P1 06116/1 EN, May 2013, printed
page 74, tables 3 and 4. Only H7, h6 and g6, 10 < nominal <= 500 mm.
Other classes/ranges are refused; no extrapolation or approximate ISO formula.
"""
from __future__ import annotations

import math

from .errors import input_error

SOURCE = "https://www.skf.com/binaries/pub12/Images/0901d19680154a05-06116_1-EN_tcm_12-122020.pdf"
CLASSES = ("H7", "h6", "g6", "H7/h6", "H7/g6")
# Upper size bound inclusive, H7 width, h6/g6 width, g6 upper deviation; deviations in micrometres.
ROWS = ((18, 18, 11, -6), (30, 21, 13, -7), (50, 25, 16, -9),
        (80, 30, 19, -10), (120, 35, 22, -12), (180, 40, 25, -14),
        (250, 46, 29, -15), (315, 52, 32, -17), (400, 57, 36, -18), (500, 63, 40, -20))


def catalog() -> dict:
    return {"item": "iso_fit", "classes": list(CLASSES), "nominal_mm": {"over": 10, "through": 500},
            "source": SOURCE, "source_page": 74, "source_revision": "SKF 06116/1 EN, May 2013",
            "usage": 'standard_library(item="iso_fit", size="25 H7/g6")',
            "scope": "Tabulated dimensional limits; fit selection under load/temperature needs engineering judgment"}


def lookup(nominal: float, designation: str) -> dict:
    if isinstance(nominal, bool) or not isinstance(nominal, (int, float)) or not math.isfinite(nominal):
        raise input_error("INVALID_SIZE", "Nominal diameter must be finite millimetres")
    if not 10 < nominal <= 500:
        raise input_error("UNVERIFIED_FIT_RANGE", "Verified fit rows cover 10 < nominal <= 500 mm")
    if designation not in CLASSES:
        raise input_error("UNVERIFIED_FIT_CLASS", "Verified classes: " + ", ".join(CLASSES))
    upper_bound, hole_width, shaft_width, shaft_top = next(row for row in ROWS if nominal <= row[0])
    lower_bound = 10 if upper_bound == 18 else ROWS[[r[0] for r in ROWS].index(upper_bound) - 1][0]
    def limits(name):
        low, high = {"H7": (0, hole_width), "h6": (-shaft_width, 0),
                     "g6": (shaft_top - shaft_width, shaft_top)}[name]
        return {"class": name, "lower": low / 1000, "upper": high / 1000,
                "minimum": round(nominal + low / 1000, 9), "maximum": round(nominal + high / 1000, 9)}
    result = {"item": "iso_fit", "designation": designation, "nominal": nominal, "units": "mm",
              "size_step": {"over": lower_bound, "through": upper_bound},
              "source": SOURCE, "source_page": 74, "source_revision": "SKF 06116/1 EN, May 2013"}
    if "/" not in designation:
        return {**result, **limits(designation)}
    hole_name, shaft_name = designation.split("/")
    hole, shaft = limits(hole_name), limits(shaft_name)
    return {**result, "hole": hole, "shaft": shaft,
            "clearance": {"minimum": round(hole["minimum"] - shaft["maximum"], 9),
                          "maximum": round(hole["maximum"] - shaft["minimum"], 9)},
            "fit_type": "clearance"}


def table(size: str | None) -> dict:
    if size is None:
        return catalog()
    try:
        nominal, designation = size.split()
        nominal = float(nominal)
    except (ValueError, AttributeError):
        raise input_error("INVALID_SIZE", 'Use a nominal diameter in mm and class, e.g. "25 H7/g6"')
    return lookup(nominal, designation)
