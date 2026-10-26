"""Operation catalog. Importing this package registers all operations."""
from . import annotate, draw, edit, structure  # noqa: F401
from .registry import REGISTRY, Ctx, catalog, coerce

__all__ = ["REGISTRY", "Ctx", "catalog", "coerce"]
