"""Structured, machine-readable errors.

Every failure surfaced by the runtime is an ``AgentCADError``. Its ``to_dict``
form is the stable contract consumed by CLI / MCP / HTTP callers.
"""
from __future__ import annotations

from typing import Any

# category -> meaning
#   input      : the request/operation parameters are wrong (fix the call)
#   spec       : the design specification is incomplete or contradictory
#   geometry   : the operation is well formed but geometrically impossible
#   file       : file missing / unreadable / not a valid DXF
#   policy     : refused by sandbox / read-only / budget rules
#   validation : the drawing does not satisfy a requirement
#   dependency : an optional component is not installed
#   internal   : bug or unexpected library failure
CATEGORIES = {"input", "spec", "geometry", "file", "policy", "validation", "dependency", "internal"}


class AgentCADError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "input",
        entities: list[str] | None = None,
        op_index: int | None = None,
        op: str | None = None,
        retryable: bool = False,
        hint: str | None = None,
        partial_changes: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        assert category in CATEGORIES, category
        self.code = code
        self.message = message
        self.category = category
        self.entities = entities or []
        self.op_index = op_index
        self.op = op
        self.retryable = retryable
        self.hint = hint
        self.partial_changes = partial_changes
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "entities": self.entities,
            "retryable": self.retryable,
            "partial_changes": self.partial_changes,
        }
        if self.op_index is not None:
            d["op_index"] = self.op_index
        if self.op is not None:
            d["op"] = self.op
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d["details"] = self.details
        return d


def input_error(code: str, message: str, **kw: Any) -> AgentCADError:
    return AgentCADError(code, message, category="input", **kw)


def geometry_error(code: str, message: str, **kw: Any) -> AgentCADError:
    return AgentCADError(code, message, category="geometry", **kw)


def file_error(code: str, message: str, **kw: Any) -> AgentCADError:
    return AgentCADError(code, message, category="file", **kw)


def policy_error(code: str, message: str, **kw: Any) -> AgentCADError:
    return AgentCADError(code, message, category="policy", **kw)


def spec_error(code: str, message: str, **kw: Any) -> AgentCADError:
    return AgentCADError(code, message, category="spec", **kw)
