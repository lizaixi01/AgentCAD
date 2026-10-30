"""Runtime metadata stored *inside* the DXF (rootdict -> AGENTCAD dictionary ->
XRECORDs holding JSON split into 250-char group-1 strings). Other CAD tools
preserve unknown XRECORDs, so the part spec travels with the drawing."""
from __future__ import annotations

import json
from typing import Any

from ezdxf.document import Drawing

DICT = "AGENTCAD"
CHUNK = 250


def set_meta(doc: Drawing, key: str, value: Any) -> None:
    root = doc.rootdict
    d = root.get(DICT)
    if d is None:
        d = root.add_new_dict(DICT)
    if key in d:
        d.remove(key)
    xr = d.add_xrecord(key)
    s = json.dumps(value, ensure_ascii=True, sort_keys=True)
    xr.reset([(1, s[i:i + CHUNK]) for i in range(0, len(s), CHUNK)] or [(1, "")])


def get_meta(doc: Drawing, key: str, default: Any = None, *, strict: bool = False) -> Any:
    d = doc.rootdict.get(DICT)
    if d is None or key not in d:
        return default
    xr = d.get(key)
    try:
        return json.loads("".join(v for code, v in xr.tags if code == 1))
    except (ValueError, TypeError, AttributeError):
        if strict:
            from .errors import input_error
            raise input_error("INVALID_METADATA", f"Stored {key!r} is not valid JSON metadata")
        return default


def all_meta(doc: Drawing) -> dict[str, Any]:
    d = doc.rootdict.get(DICT)
    if d is None:
        return {}
    return {k: get_meta(doc, k) for k in d.keys()}
