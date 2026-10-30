"""Explicit signed dimension deviations; no unverified ISO fit-table lookup."""
from __future__ import annotations

import math

from .errors import input_error
from .units import parse_length


def apply_tolerance(override, value, unit: str) -> None:
    """Store native DIMTOL/DIMLIM and render through the caller's normal path."""
    if value is None:
        override.update({"dimtol": 0, "dimlim": 0, "dimtp": 0.0, "dimtm": 0.0})
        return
    lower, upper, precision, mode = _validated_values(override, value, unit)
    method = override.set_limits if mode == "limits" else override.set_tolerance
    # DXF DIMTM is subtracted; the public interface uses signed lower deviations.
    method(upper=upper, lower=-lower, dec=precision, hfactor=0.7, leading_zeros=True, trailing_zeros=True)
    # Keep stacked deviations centred against the nominal and above the dimension
    # line. A full-height, bottom-aligned stack can cross radial extension lines.
    override["dimtolj"] = 1
    override["dimgap"] = max(float(override.get("dimgap", 0)), float(override.get("dimtxt", 2.5)) / 2)


def _validated_values(override, value, unit: str) -> tuple[float, float, int, str]:
    if (not isinstance(value, dict) or not {"lower", "upper"} <= value.keys()
            or value.keys() - {"lower", "upper", "precision", "mode"}):
        raise input_error("INVALID_TOLERANCE", "tolerance needs signed lower/upper deviations, optional precision and mode")
    if (override.dimension.dxf.dimtype & 15) not in {0, 1, 3, 4}:
        raise input_error("UNSUPPORTED_TOLERANCE", "Tolerance rendering supports linear, aligned, radius and diameter dimensions")
    if isinstance(value["lower"], bool) or isinstance(value["upper"], bool):
        raise input_error("INVALID_TOLERANCE", "Deviation values must be lengths, not booleans")
    lower = parse_length(value["lower"], unit, "tolerance.lower")
    upper = parse_length(value["upper"], unit, "tolerance.upper")
    precision = value.get("precision", 3)
    mode = value.get("mode", "deviations")
    if (not math.isfinite(lower) or not math.isfinite(upper) or lower > upper
            or type(precision) is not int or not 0 <= precision <= 8 or mode not in {"deviations", "limits"}):
        raise input_error("INVALID_TOLERANCE", "Require finite lower <= upper, precision 0..8 and mode deviations|limits")
    if any(abs(v - round(v, precision)) > 1e-10 for v in (lower, upper)):
        raise input_error("TOLERANCE_PRECISION_LOSS", "Increase precision so the displayed deviations retain the supplied values")
    from .model import measure_dimension
    nominal = measure_dimension(override.dimension)
    if nominal is None:
        raise input_error("INVALID_TOLERANCE", "Dimension has no measurable nominal value")
    nominal *= float(override.get("dimlfac", 1))
    if not math.isfinite(nominal):
        raise input_error("INVALID_TOLERANCE", "Dimension nominal and length factor must be finite")
    if mode == "limits":
        if any(abs(v - round(v, precision)) > 1e-10 for v in (nominal + lower, nominal + upper)):
            raise input_error("TOLERANCE_PRECISION_LOSS", "Increase precision so displayed limits retain nominal plus deviations")
    text = override.dimension.dxf.get("text", "")
    if text and "<>" not in text:
        raise input_error("TOLERANCE_TEXT_OVERRIDE", "Toleranced dimensions must display the measured value (<>)")
    return lower, upper, precision, mode


def check_dimension_tolerance(dimension, unit: str) -> None:
    """Read-only validation shared by redraw and saved-file delivery checks."""
    try:
        values = tolerance_info(dimension)
        if values is not None:
            values.pop("units")
            _validated_values(dimension.override(), values, unit)
    except (TypeError, ValueError, OverflowError) as exc:
        raise input_error("INVALID_TOLERANCE", "Malformed stored tolerance values") from exc


def tolerance_info(dimension) -> dict | None:
    override = dimension.override()
    if not (override.get("dimtol", 0) or override.get("dimlim", 0)):
        return None
    return {"lower": -float(override.get("dimtm", 0)), "upper": float(override.get("dimtp", 0)),
            "precision": int(override.get("dimtdec", 3)),
            "mode": "limits" if override.get("dimlim", 0) else "deviations",
            "units": "displayed drawing units"}
