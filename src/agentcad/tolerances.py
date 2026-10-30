"""Explicit signed dimension deviations; no unverified ISO fit-table lookup."""
from __future__ import annotations

import json
import math

from ezdxf.lldxf.const import DXFTableEntryError

from .errors import input_error
from .units import parse_length

TOLERANCED = {0, 1, 3, 4}  # dimension types AgentCAD tolerances: linear, aligned, diameter, radius
# XDATA app on a dimension whose tolerance AgentCAD wrote, holding the dimension's own look before it.
# Its own app, so that setting a tag (which replaces the AGENTCAD xdata) keeps it.
MARK = "AGENTCAD_TOLERANCE"
LOOK = ("dimgap", "dimtolj", "dimtfac")


def apply_tolerance(override, value, unit: str) -> None:
    """Store native DIMTOL/DIMLIM and render through the caller's normal path."""
    dimension = override.dimension
    if value is None:
        override.update({"dimtol": 0, "dimlim": 0, "dimtp": 0.0, "dimtm": 0.0})
        before = _mark(dimension)
        if before is not None:  # back to the dimension's own look before AgentCAD's tolerance
            for key, old in before.items():
                if old is None:
                    del override[key]
                else:
                    override[key] = old
            dimension.discard_xdata(MARK)
        return
    lower, upper, precision, mode = _validated_values(override, value, unit)
    if _mark(dimension) is None:
        _set_mark(dimension, {key: override.dimstyle_attribs.get(key) for key in LOOK})
    method = override.set_limits if mode == "limits" else override.set_tolerance
    # DXF DIMTM is subtracted; the public interface uses signed lower deviations.
    method(upper=upper, lower=-lower, dec=precision, hfactor=0.7, leading_zeros=True, trailing_zeros=True)
    # Keep stacked deviations centred against the nominal and above the dimension
    # line. A full-height, bottom-aligned stack can cross radial extension lines.
    override["dimtolj"] = 1
    override["dimgap"] = max(float(override.get("dimgap", 0)), _tolerance_gap(override))


def _tolerance_gap(override) -> float:
    return float(override.get("dimtxt", 2.5)) / 2


def _validated_values(override, value, unit: str) -> tuple[float, float, int, str]:
    if (not isinstance(value, dict) or not {"lower", "upper"} <= value.keys()
            or value.keys() - {"lower", "upper", "precision", "mode"}):
        raise input_error("INVALID_TOLERANCE", "tolerance needs signed lower/upper deviations, optional precision and mode")
    if (override.dimension.dxf.dimtype & 15) not in TOLERANCED:
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
    """Read-only validation shared by redraw and saved-file delivery checks.

    A tolerance AgentCAD wrote is held to the rules it was created under, also after a foreign
    edit. Any other tolerance (from the dimension style, or set by another program, for one
    dimension or on a type such as angular) is the drawing author's: only corrupt values are refused."""
    try:
        override = _override(dimension)
        values = None if override is None else _stored(override)
        if values is None:
            return
        if _mark(dimension) is not None and _own(override) and (dimension.dxf.dimtype & 15) in TOLERANCED:
            _validated_values(override, values, unit)
        elif not (math.isfinite(values["lower"]) and math.isfinite(values["upper"])):
            raise ValueError("non-finite deviation")
    except (TypeError, ValueError, OverflowError) as exc:
        raise input_error("INVALID_TOLERANCE", "Malformed stored tolerance values") from exc


def tolerance_info(dimension) -> dict | None:
    override = _override(dimension)
    values = None if override is None else _stored(override)
    if values is None:
        return None
    values["units"] = "displayed drawing units"
    if not _own(override):
        values["from_style"] = True
    return values


def _override(dimension):
    try:
        return dimension.override()
    except DXFTableEntryError:  # names a dimension style the drawing does not have
        return None


def _stored(override) -> dict | None:
    if not (override.get("dimtol", 0) or override.get("dimlim", 0)):
        return None
    return {"lower": -float(override.get("dimtm", 0)), "upper": float(override.get("dimtp", 0)),
            "precision": int(override.get("dimtdec", 3)),
            "mode": "limits" if override.get("dimlim", 0) else "deviations"}


def _own(override) -> bool:
    """The flag that turns the tolerance on is set on the dimension, not inherited from its style."""
    return any(override.dimstyle_attribs.get(k) for k in ("dimtol", "dimlim"))


def _mark(dimension) -> dict | None:
    """The dimension's own look before AgentCAD's tolerance; None if AgentCAD did not write its tolerance.
    A missing or implausible value reads as None, so clearing falls back to the style's value."""
    if not dimension.has_xdata(MARK):
        return None
    try:
        saved = json.loads(next(value for code, value in dimension.get_xdata(MARK) if code == 1000))
        return {key: _plausible(key, saved.get(key)) for key in LOOK}
    except (StopIteration, ValueError, TypeError, AttributeError):  # damaged: still AgentCAD's, look unknown
        return {}


def _plausible(key: str, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if key == "dimtolj":
        return value if value in (0, 1, 2) else None
    if key == "dimtfac":
        return value if 0 < value < 1e6 else None
    return value if abs(value) < 1e6 else None  # a negative gap is AutoCAD's boxed text


def _set_mark(dimension, before: dict) -> None:
    doc = dimension.doc
    if doc is not None and MARK not in doc.appids:
        doc.appids.add(MARK)
    dimension.set_xdata(MARK, [(1000, json.dumps(before))])
