"""Drawing persistence: safe load/save, checkpoints, append-only journal and
crash recovery.

State for ``<root>/path/to/part.dxf`` lives in
``<root>/.agentcad/drawings/path__to__part.dxf/``::

    head.json         committed sha256 + pending-transaction marker
    journal.jsonl     one JSON record per committed (or failed) operation
    checkpoints/      cp-0001.dxf ... byte-exact copies taken before each change

The same store serves 3D parts (``.FCStd``): checkpoints keep the file's own
suffix and ``reader`` is the format's strict reader (``read_dxf`` by default).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Callable

import ezdxf
from ezdxf.document import Drawing

from . import __version__
from .errors import AgentCADError, file_error, input_error
from .policy import Policy

VERSIONS = {"agentcad": __version__, "ezdxf": ezdxf.__version__, "python": platform.python_version()}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def read_dxf(path: Path, policy: Policy) -> Drawing:
    """Strict DXF read with structured errors (never returns a half-parsed doc)."""
    if not path.is_file():
        raise file_error("FILE_NOT_FOUND", f"{path} does not exist")
    size = path.stat().st_size
    if size > policy.max_file_bytes:
        raise file_error("FILE_TOO_LARGE", f"{path} is {size} bytes (limit {policy.max_file_bytes})")
    if size == 0:
        raise file_error("DXF_PARSE_ERROR", f"{path} is empty", hint="Restore from a checkpoint with rollback/recover")
    try:
        with open(path, "rb") as fh:  # distinguish real I/O errors from ezdxf's OSError on garbage
            fh.read(1)
    except OSError as exc:
        raise file_error("FILE_READ_ERROR", f"Cannot read {path}: {exc}", retryable=True)
    try:
        return ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError as exc:
        raise file_error("DXF_PARSE_ERROR", f"{path.name} is not a valid DXF: {exc}",
                         hint="The file is corrupt or not DXF; use recover or rollback to a checkpoint")
    except (UnicodeDecodeError, ValueError, IndexError, KeyError, TypeError) as exc:
        raise file_error("DXF_PARSE_ERROR", f"{path.name} could not be parsed: {type(exc).__name__}: {exc}",
                         hint="The file is corrupt or not DXF; use recover or rollback to a checkpoint")
    except OSError as exc:  # ezdxf raises plain OSError for non-DXF content
        raise file_error("DXF_PARSE_ERROR", f"{path.name} is not a DXF file: {exc}",
                         hint="The file is corrupt or not DXF; use recover or rollback to a checkpoint")


def dxf_bytes(doc: Drawing) -> bytes:
    finalize(doc)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode(doc.output_encoding, errors="dxfreplace")


def finalize(doc: Drawing) -> None:
    """Write real $EXTMIN/$EXTMAX. ezdxf leaves the 1e20 sentinels, which makes
    importers that fit the view to the header extents (e.g. LibreOffice) shrink
    the drawing to a dot."""
    from ezdxf import bbox
    msp = doc.modelspace()
    try:
        ext = bbox.extents(msp, fast=True)
    except Exception:  # never block a save on extents
        return
    if ext.has_data:
        lo, hi = ext.extmin, ext.extmax
        doc.header["$EXTMIN"] = (lo.x, lo.y, 0)
        doc.header["$EXTMAX"] = (hi.x, hi.y, 0)
        msp.dxf.extmin = (lo.x, lo.y, 0)
        msp.dxf.extmax = (hi.x, hi.y, 0)


class DrawingStore:
    def __init__(self, policy: Policy, path: Path, reader: Callable[[Path, Policy], Any] = read_dxf) -> None:
        self.policy = policy
        self.path = path
        self.reader = reader
        self.ext = path.suffix.lower() or ".dxf"
        rel = path.relative_to(policy.root).as_posix().replace("/", "__")
        self.dir = policy.state_dir() / "drawings" / rel
        self.cp_dir = self.dir / "checkpoints"
        self.journal_path = self.dir / "journal.jsonl"
        self.head_path = self.dir / "head.json"
        self.committed_path = self.dir / f"committed{self.ext}"

    # --- head / journal ---------------------------------------------------------
    def head(self) -> dict[str, Any]:
        if self.head_path.is_file():
            return json.loads(self.head_path.read_text("utf-8"))
        return {"seq": 0, "sha256": None, "pending": None, "checkpoints": []}

    def _write_head(self, head: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.head_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(head, indent=1), "utf-8")
        os.replace(tmp, self.head_path)

    def journal(self, record: dict[str, Any]) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        head = self.head()
        seq = head["seq"] + 1
        head["seq"] = seq
        record = {"seq": seq, "ts": now(), "drawing": self.path.relative_to(self.policy.root).as_posix(),
                  "versions": VERSIONS, **record}
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._write_head(head)
        return seq

    def read_journal(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.journal_path.is_file():
            return []
        lines = self.journal_path.read_text("utf-8").splitlines()
        recs = [json.loads(x) for x in lines if x.strip()]
        return recs[-limit:] if limit else recs

    # --- checkpoints ---------------------------------------------------------------
    def checkpoint(self, label: str) -> str | None:
        """Copy the current file bytes into a new checkpoint. Returns its id."""
        if not self.path.is_file():
            return None
        self.cp_dir.mkdir(parents=True, exist_ok=True)
        head = self.head()
        n = len(head["checkpoints"]) + 1
        cid = f"cp-{n:04d}"
        shutil.copy2(self.path, self.cp_dir / f"{cid}{self.ext}")
        head["checkpoints"].append({"id": cid, "ts": now(), "label": label, "sha256": sha256_file(self.path)})
        self._write_head(head)
        return cid

    def list_checkpoints(self) -> list[dict[str, Any]]:
        return self.head()["checkpoints"]

    def checkpoint_path(self, cid: str) -> Path:
        p = self.cp_dir / f"{cid}{self.ext}"
        if not p.is_file():
            raise input_error("CHECKPOINT_NOT_FOUND", f"No checkpoint {cid!r}",
                              hint=f"Available: {[c['id'] for c in self.list_checkpoints()]}")
        return p

    # --- load / commit --------------------------------------------------------------
    def load(self) -> Drawing:
        return self.reader(self.path, self.policy)

    def commit(self, doc: Drawing, *, label: str, overwrite_ok: bool = True) -> dict[str, Any]:
        """Checkpoint the current file, then atomically replace it with ``doc``.

        A ``pending`` marker is written to head.json before the replace and
        cleared afterwards; a crash in between is detected by ``recover``.
        """
        return self.commit_bytes(dxf_bytes(doc), label=label, overwrite_ok=overwrite_ok)

    def commit_bytes(self, data: bytes, *, label: str, overwrite_ok: bool = True) -> dict[str, Any]:
        """``commit`` for a file already serialised (a 3D part saved by FreeCAD)."""
        self.policy.check_write()
        if len(data) > self.policy.max_file_bytes:
            raise file_error("FILE_TOO_LARGE", f"Result would be {len(data)} bytes")
        existed = self.path.is_file()
        if existed and not overwrite_ok:
            raise input_error("FILE_EXISTS", f"{self.path.name} already exists", hint="Pass overwrite=true")
        cid = self.checkpoint(f"before {label}") if existed else None
        head = self.head()
        head["pending"] = {"label": label, "checkpoint": cid, "ts": now()}
        self._write_head(head)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".agentcad-tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        digest = hashlib.sha256(data).hexdigest()
        # exact copy of the committed state, so crash recovery loses nothing
        ctmp = self.committed_path.with_suffix(".tmp")
        ctmp.write_bytes(data)
        os.replace(ctmp, self.committed_path)
        head = self.head()
        head["pending"] = None
        head["sha256"] = digest
        self._write_head(head)
        return {"checkpoint_before": cid, "sha256": digest, "bytes": len(data)}

    def restore(self, cid: str, *, label: str) -> dict[str, Any]:
        """Restore checkpoint ``cid`` ("committed" = the exact last committed state)."""
        self.policy.check_write()
        src = self.committed_path if cid == "committed" else self.checkpoint_path(cid)
        before = None
        if self.path.is_file():
            try:
                self.reader(self.path, self.policy)
                before = self.checkpoint(f"before {label}")
            except AgentCADError:
                before = None  # never checkpoint a corrupt file
        tmp = self.path.with_name(self.path.name + ".agentcad-tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, self.path)
        shutil.copy2(self.path, self.committed_path)
        head = self.head()
        head["pending"] = None
        head["sha256"] = sha256_file(self.path)
        self._write_head(head)
        return {"restored": cid, "checkpoint_before": before, "sha256": head["sha256"]}

    def status(self) -> dict[str, Any]:
        """Integrity of the file versus the last commit."""
        head = self.head()
        exists = self.path.is_file()
        actual = sha256_file(self.path) if exists else None
        readable = True
        err = None
        if exists:
            try:
                self.reader(self.path, self.policy)
            except AgentCADError as exc:
                readable = False
                err = exc.to_dict()
        return {"exists": exists, "readable": readable, "parse_error": err, "pending_transaction": head.get("pending"),
                "committed_sha256": head.get("sha256"), "actual_sha256": actual,
                "modified_outside_runtime": bool(head.get("sha256") and actual and actual != head["sha256"]),
                "checkpoints": len(head["checkpoints"])}
