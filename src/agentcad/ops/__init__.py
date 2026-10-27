"""Operation catalog. Importing this package registers all operations."""
from . import annotate, draw, edit, sheet, structure  # noqa: F401
from .registry import REGISTRY, Ctx, catalog, coerce

__all__ = ["REGISTRY", "Ctx", "catalog", "coerce"]
