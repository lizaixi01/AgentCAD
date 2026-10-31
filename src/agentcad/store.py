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
import time
from pathlib import Path
from typing import Any, Callable

import ezdxf
from ezdxf.document import Drawing

from . import sessions
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


REPLACE_TIMEOUT = 2.0  # seconds replace_file waits out a reader; tests lower it


def busy_error(path: Path, *, applied: bool, **kw: Any) -> AgentCADError:
    """A file the store must replace stayed open in another process. ``applied``: the drawing itself was already
    replaced (the change is in the file), so the call must not be repeated."""
    if applied:
        return file_error("FILE_BUSY", f"{path.name} stayed open in another process; the change was saved to the "
                          "drawing but not recorded", retryable=False, partial_changes=True,
                          hint="Do not repeat the operations: call recover to record the change", **kw)
    return file_error("FILE_BUSY", f"{path.name} stayed open in another process; nothing was changed",
                      retryable=True, hint="Retry when the other program has closed the file", **kw)


def replace_file(src: Path, dst: Path, timeout: float | None = None) -> None:
    """``os.replace`` that waits out readers. On Windows a file another process has open (the live viewer, an
    antivirus scan, the search indexer, Explorer's preview) cannot be replaced, even with delete sharing; those
    reads are short, so retry for up to ``timeout`` seconds before giving up."""
    deadline = time.monotonic() + (REPLACE_TIMEOUT if timeout is None else timeout)
    delay = 0.005
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


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
        replace_file(tmp, self.head_path)

    def _last_journal_seq(self) -> int:
        """seq of the journal's last record, read from the file's tail (the record is appended before head.json
        is updated, so head's seq can lag behind it)."""
        try:
            with open(self.journal_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().splitlines()
        except OSError:
            return 0
        for raw in reversed(lines):
            try:
                return int(json.loads(raw)["seq"])
            except (ValueError, KeyError, TypeError):
                continue
        return 0

    def journal(self, record: dict[str, Any]) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        head = self.head()
        seq = max(head["seq"], self._last_journal_seq()) + 1
        head["seq"] = seq
        record = {"seq": seq, "ts": now(), "drawing": self.path.relative_to(self.policy.root).as_posix(),
                  "versions": VERSIONS, **{k: v for k, v in sessions.tag().items() if k != "session"}, **record}
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        try:
            self._write_head(head)
        except PermissionError:  # the record is written; the next journal call takes its seq from the file
            pass
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
        cp = self.cp_dir / f"{cid}{self.ext}"
        shutil.copy2(self.path, cp)
        head["checkpoints"].append({"id": cid, "ts": now(), "label": label, "sha256": sha256_file(self.path)})
        try:
            self._write_head(head)
        except PermissionError:
            cp.unlink(missing_ok=True)  # not recorded: leave no file the next checkpoint would silently replace
            raise
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

    def commit(self, doc: Drawing, *, label: str, overwrite_ok: bool = True,
               attempt: dict[str, Any] | None = None) -> dict[str, Any]:
        """Checkpoint the current file, then atomically replace it with ``doc``.

        A ``pending`` marker is written to head.json before the replace and
        cleared afterwards; a crash in between is detected by ``recover``.
        ``attempt``: the journal record the caller writes on success. If the change reaches the file but cannot be
        recorded (FILE_BUSY, applied_not_recorded), it is journaled as a failed attempt, and settling the commit
        later copies its payload (operations, changes) into the recover record.
        """
        return self.commit_bytes(dxf_bytes(doc), label=label, overwrite_ok=overwrite_ok, attempt=attempt)

    def commit_bytes(self, data: bytes, *, label: str, overwrite_ok: bool = True,
                     attempt: dict[str, Any] | None = None) -> dict[str, Any]:
        """``commit`` for a file already serialised (a 3D part saved by FreeCAD)."""
        self.policy.check_write()
        if len(data) > self.policy.max_file_bytes:
            raise file_error("FILE_TOO_LARGE", f"Result would be {len(data)} bytes")
        existed = self.path.is_file()
        if existed and not overwrite_ok:
            raise input_error("FILE_EXISTS", f"{self.path.name} already exists", hint="Pass overwrite=true")
        return self._replace_tracked(data, label=label, attempt=attempt,
                                     checkpoint=lambda: self.checkpoint(f"before {label}") if existed else None)

    def _replace_tracked(self, data: bytes, *, label: str, checkpoint: Callable[[], str | None],
                         attempt: dict[str, Any] | None = None) -> dict[str, Any]:
        """Replace the drawing with ``data`` as one transaction (commits and restores): settle an earlier
        interrupted transaction, ``checkpoint`` the current file, write the pending marker with the target sha,
        replace, refresh the committed copy, update head. A file another process holds past the retry timeout
        raises FILE_BUSY: retryable while the drawing is untouched, partial_changes once it holds ``data``."""
        digest = hashlib.sha256(data).hexdigest()
        try:  # an earlier interrupted transaction is settled first; if head.json is busy it stays as it is
            self.settle_pending()
        except PermissionError:
            raise busy_error(self.head_path, applied=False)
        cid = None
        # the target sha lets recover tell whether the drawing was replaced before the commit was interrupted
        revision = self.head().get("revision", 0) + 1
        marker = {"label": label, "checkpoint": None, "ts": now(), "sha256": digest, "revision": revision}
        try:  # until the drawing is replaced, a busy file means nothing changed
            cid = checkpoint()
            marker["checkpoint"] = cid
            head = self.head()
            head["pending"] = marker
            self._write_head(head)
        except PermissionError:
            self._abandon(cid, marker)
            raise busy_error(self.head_path, applied=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".agentcad-tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            replace_file(tmp, self.path)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            self._abandon(cid, marker)
            raise busy_error(self.path, applied=False)
        # From here the drawing holds the change: the commit has happened and must not be reported as failed.
        warnings = []
        # exact copy of the committed state, so crash recovery loses nothing
        ctmp = self.committed_path.with_suffix(".tmp")
        ctmp.write_bytes(data)
        try:
            replace_file(ctmp, self.committed_path)
        except PermissionError:
            ctmp.unlink(missing_ok=True)
            warnings.append(f"{self.committed_path.name} was busy and still holds the previous version; recover "
                            "falls back to checkpoints until the next commit refreshes it")
        head = self.head()
        head["pending"] = None
        head["sha256"] = digest
        head["revision"] = revision
        try:
            self._write_head(head)
        except PermissionError:
            exc = busy_error(self.head_path, applied=True, details={"state": "applied_not_recorded",
                                                                   "sha256": digest, "checkpoint_before": cid})
            if attempt is not None:  # the journal needs no head write to take the record
                self.journal({**attempt, "ok": False, "error": exc.to_dict()})
            raise exc
        return {"checkpoint_before": cid, "sha256": digest, "bytes": len(data), "revision": revision,
                **({"warnings": warnings} if warnings else {})}

    def _abandon(self, cid: str | None, marker: dict[str, Any]) -> None:
        """Undo a transaction that stopped before the drawing was replaced: drop the checkpoint it took and its
        pending marker, so a retry starts from the same state (a retried rollback would otherwise restore that
        checkpoint, i.e. do nothing). Only this transaction's own marker is cleared, never an earlier one that
        still has to be settled. head.json is rewritten first and the checkpoint file deleted only after that
        succeeded: if head.json is the busy file, head keeps listing the checkpoint and its file stays (a harmless
        copy of the unchanged drawing), and the marker stays for recover, which sees the drawing unchanged."""
        try:
            head = self.head()
        except (OSError, ValueError):
            return
        drop = bool(cid and head["checkpoints"] and head["checkpoints"][-1]["id"] == cid)
        mine = head.get("pending") == marker
        if not (drop or mine):
            return
        if drop:
            head["checkpoints"].pop()
        if mine:
            head["pending"] = None
        try:
            self._write_head(head)
        except PermissionError:
            return
        if drop:
            (self.cp_dir / f"{cid}{self.ext}").unlink(missing_ok=True)

    def settle_pending(self, **record: Any) -> tuple[dict[str, Any], int] | None:
        """``finish_pending`` and journal the outcome: an interrupted commit that reached the file gets its record
        (a ``recover`` record with ``completed_commit``), so a later commit never absorbs it unrecorded."""
        done = self.finish_pending()
        if done is None:
            return None
        rec = {"tool": "recover", "ok": True, **record, **done}
        if done["outcome"] == "completed":
            rec["completed_commit"] = done["pending"]["label"]
            rec["checkpoint_before"] = done["pending"].get("checkpoint")
            for r in reversed(self.read_journal()):  # the attempt journaled when the commit could not be recorded
                if ((r.get("error") or {}).get("details") or {}).get("sha256") == done["sha256"]:
                    rec["completed_seq"] = r["seq"]
                    rec.update({k: r[k] for k in ("operations", "changes", "code") if k in r})
                    break
        return done, self.journal(rec)

    def finish_pending(self) -> dict[str, Any] | None:
        """Settle a commit that was interrupted after its pending marker was written. If the drawing holds the
        marker's target content, the commit happened: record it. If it still holds the last committed content, the
        drawing was never replaced: clear the marker. None when neither holds, or the marker has no target sha
        (written before markers carried one): then restore a checkpoint as before."""
        head = self.head()
        pend = head.get("pending")
        if not pend or not pend.get("sha256") or not self.path.is_file():
            return None
        actual = sha256_file(self.path)
        if actual == pend["sha256"]:
            shutil.copy2(self.path, self.committed_path)
            head["sha256"] = actual
            head["revision"] = pend.get("revision", head.get("revision", 0) + 1)
            outcome = "completed"
        elif actual == head.get("sha256"):
            outcome = "discarded"
        else:
            return None
        head["pending"] = None
        self._write_head(head)
        return {"pending": pend, "outcome": outcome, "sha256": actual}

    def restore(self, cid: str, *, label: str) -> dict[str, Any]:
        """Restore checkpoint ``cid`` ("committed" = the exact last committed state), as one transaction like a
        commit (see ``_replace_tracked``)."""
        self.policy.check_write()
        src = self.committed_path if cid == "committed" else self.checkpoint_path(cid)
        data = src.read_bytes()

        def checkpoint() -> str | None:
            if not self.path.is_file():
                return None
            try:
                self.reader(self.path, self.policy)
            except AgentCADError:
                return None  # never checkpoint a corrupt file
            return self.checkpoint(f"before {label}")

        info = self._replace_tracked(data, label=label, checkpoint=checkpoint)
        return {"restored": cid, "checkpoint_before": info["checkpoint_before"], "sha256": info["sha256"],
                **({"warnings": info["warnings"]} if "warnings" in info else {})}

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
                "committed_sha256": head.get("sha256"), "actual_sha256": actual, "revision": head.get("revision", 0),
                "modified_outside_runtime": bool(head.get("sha256") and actual and actual != head["sha256"]),
                "checkpoints": len(head["checkpoints"])}
