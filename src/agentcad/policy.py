"""Execution policy: sandboxed workspace, read-only mode, op allow-list, budgets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import policy_error, input_error

STATE_DIR = ".agentcad"


@dataclass
class Policy:
    root: Path = field(default_factory=lambda: Path(os.environ.get("AGENTCAD_ROOT", os.getcwd())))
    read_only: bool = field(default_factory=lambda: os.environ.get("AGENTCAD_READ_ONLY", "") in {"1", "true", "yes"})
    allowed_ops: frozenset[str] | None = field(default_factory=lambda: _env_set("AGENTCAD_ALLOWED_OPS"))
    max_entities: int = field(default_factory=lambda: int(os.environ.get("AGENTCAD_MAX_ENTITIES", "200000")))
    max_ops_per_batch: int = field(default_factory=lambda: int(os.environ.get("AGENTCAD_MAX_OPS", "5000")))
    max_new_entities_per_batch: int = 50000
    # deleting more entities than this in one batch requires "confirm_large": true
    delete_confirm_threshold: int = 50
    max_file_bytes: int = 256 * 1024 * 1024
    max_document_bytes: int = 32 * 1024 * 1024
    # run_script (agent-written ezdxf scripts, see scripting.py) is off unless explicitly enabled
    allow_scripts: bool = field(default_factory=lambda: os.environ.get("AGENTCAD_ALLOW_SCRIPTS", "") in {"1", "true", "yes"})
    script_timeout: float = field(default_factory=lambda: float(os.environ.get("AGENTCAD_SCRIPT_TIMEOUT", "60")))

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    # --- paths -------------------------------------------------------------
    def resolve(self, path: str | os.PathLike, *, must_exist: bool = False,
                suffixes: tuple[str, ...] | None = None, hint_suffix: str = "") -> Path:
        if path is None or str(path).strip() == "":
            raise input_error("MISSING_PATH", "A file path is required")
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        if not p.is_relative_to(self.root):
            raise policy_error("PATH_OUTSIDE_WORKSPACE",
                               f"{path} resolves outside the workspace root {self.root}",
                               hint="Use a path inside the workspace (set AGENTCAD_ROOT to change it)")
        if STATE_DIR in p.relative_to(self.root).parts:
            raise policy_error("PATH_RESERVED", f"{path} is inside the runtime state directory {STATE_DIR}/")
        if suffixes and p.suffix.lower() not in suffixes:
            raise input_error("BAD_EXTENSION", f"{path}: expected one of {list(suffixes)}{hint_suffix}")
        if must_exist and not p.is_file():
            from .errors import file_error
            raise file_error("FILE_NOT_FOUND", f"{path} does not exist", hint="Create it first with create_drawing")
        return p

    def check_write(self) -> None:
        if self.read_only:
            raise policy_error("READ_ONLY", "Runtime is in read-only mode; modifications are disabled")

    def check_scripts_allowed(self) -> None:
        if not self.allow_scripts:
            raise policy_error("SCRIPTS_DISABLED", "run_script is disabled for this workspace",
                               hint="Use apply_operations, or start the runtime with AGENTCAD_ALLOW_SCRIPTS=1 "
                                    "(only for agents you would let run Python as your user)")

    def check_op_allowed(self, op: str, index: int) -> None:
        if self.allowed_ops is not None and op not in self.allowed_ops:
            raise policy_error("OP_NOT_ALLOWED", f"Operation {op!r} is not in the allowed operation set",
                               op=op, op_index=index)

    def state_dir(self) -> Path:
        return self.root / STATE_DIR


def _env_set(name: str) -> frozenset[str] | None:
    v = os.environ.get(name)
    if not v:
        return None
    return frozenset(s.strip() for s in v.split(",") if s.strip())
