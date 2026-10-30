"""Resolve saved entity visibility, including DIMENSION block inheritance."""
from __future__ import annotations

from ezdxf.colors import TRANSPARENCY_BYBLOCK


def _layer_name(entity, parent):
    name = entity.dxf.layer
    return parent.dxf.layer if name == "0" and parent is not None else name


def _alpha(doc, entity, parent) -> int:
    raw = entity.dxf.get("transparency")
    if raw is None:  # BYLAYER; block layer 0 inherits its reference's layer.
        layer = doc.layers.get(_layer_name(entity, parent))
        return round((1.0 - layer.transparency) * 255)
    if raw == TRANSPARENCY_BYBLOCK:
        return _alpha(doc, parent, None) if parent is not None else 255
    return raw & 255


def is_visible(doc, entity, *, parent=None, container: bool = False) -> bool:
    """Check saved visibility/plot flags and nonzero effective opacity.

    A DIMENSION is a container: its opacity only applies to children that inherit
    BYBLOCK. Explicitly opaque children remain visible, as in the drawing renderer.
    This checks invisibility, not contrast or general visual layout/readability.
    """
    if entity is None or not entity.is_alive or entity.dxf.get("invisible", 0):
        return False
    if parent is not None and not is_visible(doc, parent, container=True):
        return False
    name = _layer_name(entity, parent)
    if not doc.layers.has_entry(name):
        return False
    layer = doc.layers.get(name)
    if layer.is_off() or layer.is_frozen() or not layer.dxf.get("plot", 1):
        return False
    return container or _alpha(doc, entity, parent) > 0
