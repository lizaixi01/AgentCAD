"""Unified business API. CLI, MCP server and HTTP server are thin adapters over
``Runtime`` methods; every method returns a JSON-serialisable envelope::

    {"ok": true|false, "tool": "<name>", ...payload..., "error": {...}?, "metrics": {...}}
"""
from __future__ import annotations

import json
import os
import time
import traceback
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import ezdxf
from ezdxf import bbox

from . import engine, spec as specmod
from .constraints import ENFORCE_TYPES, CHECK_TYPES, check_constraints, enforce_one
from .errors import AgentCADError, input_error, policy_error
from .metadata import all_meta, get_meta, set_meta
from .model import entity_to_dict, get_tag, select
from .ops import catalog
from .ops.annotate import DIMSTYLE
from .policy import Policy
from .store import DrawingStore, finalize, read_dxf, now
from .units import UNITS, normalize_unit, unit_from_insunits
from .validate import validate_file

DXF_VERSIONS = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024",
                "R2013": "AC1027", "R2018": "AC1032"}

TOOLS: dict[str, Callable] = {}


def tool(fn):
    """Wrap a Runtime method into the standard envelope with metrics and error capture."""
    name = fn.__name__

    @wraps(fn)
    def wrapper(self: "Runtime", *args, **kwargs):
        t0 = time.perf_counter()
        in_bytes = len(json.dumps([args, kwargs], default=str))
        try:
            payload = fn(self, *args, **kwargs)
            env = {"ok": True, "tool": name, **payload}
        except AgentCADError as exc:
            env = {"ok": False, "tool": name, "error": exc.to_dict()}
        except Exception as exc:  # never leak a raw traceback as the only signal
            env = {"ok": False, "tool": name,
                   "error": AgentCADError("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", category="internal",
                                          details={"traceback": traceback.format_exc(limit=8)}).to_dict()}
        env["metrics"] = {"duration_ms": round((time.perf_counter() - t0) * 1000, 2), "input_bytes": in_bytes,
                          "output_bytes": len(json.dumps(env, default=str))}
        self.metrics.append({"tool": name, "ok": env["ok"], **env["metrics"]})
        return env

    TOOLS[name] = fn
    wrapper.__agentcad_tool__ = True  # type: ignore[attr-defined]
    return wrapper


def _units_of(doc) -> str | None:
    return unit_from_insunits(doc.header.get("$INSUNITS", 0))


def setup_document(units: str, template: str, version: str):
    if version not in DXF_VERSIONS:
        raise input_error("UNSUPPORTED_DXF_VERSION", f"Unknown DXF version {version!r}", hint=f"Use one of {list(DXF_VERSIONS)}")
    if version == "R12":
        raise input_error("UNSUPPORTED_DXF_VERSION", "Create drawings as R2000+; R12 is available as an export target")
    doc = ezdxf.new(version, setup=True)
    code, mm_per = UNITS[units]
    doc.header["$INSUNITS"] = code
    doc.header["$MEASUREMENT"] = 0 if units in ("in", "ft") else 1
    doc.header["$LUNITS"] = 2
    doc.header["$MIRRTEXT"] = 0
    k = 1.0 / mm_per  # 1 mm expressed in drawing units, for annotation sizes
    ds = doc.dimstyles.new(DIMSTYLE)
    for key, val in {"dimtxt": 3.5 * k, "dimasz": 2.5 * k, "dimexe": 1.25 * k, "dimexo": 0.625 * k,
                     "dimgap": 0.625 * k, "dimdec": 3 if units in ("in", "ft") else 2, "dimzin": 8,
                     "dimlfac": 1.0, "dimtad": 1, "dimtih": 0, "dimtoh": 0, "dimcen": 2.5 * k, "dimtxsty": "Standard",
                     "dimlunit": 2, "dimdsep": ord(".")}.items():
        ds.dxf.set(key, val)
    if template == "mechanical":
        for o in specmod.LAYERS:
            lt = o.get("linetype", "Continuous")
            doc.layers.add(o["name"], color=o["color"], linetype=lt, lineweight=o["lineweight"])
    elif template != "blank":
        raise input_error("UNKNOWN_TEMPLATE", f"Unknown template {template!r}", hint="Use 'blank' or 'mechanical'")
    set_meta(doc, "created", {"by": "agentcad", "units": units, "template": template, "ts": now()})
    return doc


class Runtime:
    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy or Policy()
        self.metrics: list[dict[str, Any]] = []

    # --- helpers ---------------------------------------------------------------------------
    def _drawing(self, path: str, must_exist: bool = True) -> tuple[Path, DrawingStore]:
        p = self.policy.resolve(path, must_exist=must_exist, suffixes=(".dxf",))
        return p, DrawingStore(self.policy, p)

    @contextmanager
    def _lock(self, store: DrawingStore):
        store.dir.mkdir(parents=True, exist_ok=True)
        lock = store.dir / "lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - lock.stat().st_mtime
            if age < 120:
                raise AgentCADError("DRAWING_LOCKED", "Another operation is modifying this drawing", category="policy",
                                    retryable=True, hint="Retry shortly")
            os.remove(lock)  # stale lock from a crashed process
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            try:
                os.remove(lock)
            except OSError:
                pass

    def _save_failure(self, store: DrawingStore, doc, label: str) -> str | None:
        try:
            d = store.dir / "failed"
            d.mkdir(parents=True, exist_ok=True)
            fp = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.dxf"
            doc.saveas(fp)
            return str(fp.relative_to(self.policy.root).as_posix())
        except Exception:
            return None

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.policy.root).as_posix()

    # --- tools ------------------------------------------------------------------------------------
    @tool
    def list_operations(self, category: str | None = None) -> dict[str, Any]:
        ops = [o for o in catalog() if category is None or o["category"] == category]
        return {"operations": ops, "count": len(ops), "constraint_types": {"check": sorted(CHECK_TYPES),
                                                                          "enforce": sorted(ENFORCE_TYPES)}}

    @tool
    def create_drawing(self, path: str, units: str = "mm", template: str = "mechanical", dxf_version: str = "R2010",
                       overwrite: bool = False) -> dict[str, Any]:
        self.policy.check_write()
        u = normalize_unit(units)
        p, store = self._drawing(path, must_exist=False)
        if p.exists() and not overwrite:
            raise input_error("FILE_EXISTS", f"{path} already exists", hint="Pass overwrite=true to replace it (a checkpoint is kept)")
        doc = setup_document(u, template, dxf_version)
        with self._lock(store):
            info = store.commit(doc, label="create_drawing")
            seq = store.journal({"tool": "create_drawing", "args": {"units": u, "template": template,
                                                                    "dxf_version": dxf_version}, "ok": True, **info})
        return {"drawing": self._rel(p), "units": u, "dxf_version": dxf_version, "journal_seq": seq, **info}

    @tool
    def read_drawing(self, path: str) -> dict[str, Any]:
        p, store = self._drawing(path)
        doc = store.load()
        msp = doc.modelspace()
        counts: dict[str, int] = {}
        per_layer: dict[str, int] = {}
        tags = []
        for e in msp:
            counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1
            per_layer[e.dxf.layer] = per_layer.get(e.dxf.layer, 0) + 1
            t = get_tag(e)
            if t:
                tags.append({"tag": t, "id": e.dxf.handle, "type": e.dxftype()})
        ext = bbox.extents(msp, fast=True)
        layers = [{"name": l.dxf.name, "color": l.color, "linetype": l.dxf.linetype, "lineweight": l.dxf.lineweight,
                   "on": l.is_on(), "frozen": l.is_frozen(), "locked": l.is_locked(),
                   "entity_count": per_layer.get(l.dxf.name, 0)} for l in doc.layers]
        meta = all_meta(doc)
        return {"drawing": self._rel(p), "dxf_version": doc.acad_release, "units": _units_of(doc),
                "insunits": doc.header.get("$INSUNITS", 0),
                "extents": None if not ext.has_data else [[round(ext.extmin.x, 6), round(ext.extmin.y, 6)],
                                                          [round(ext.extmax.x, 6), round(ext.extmax.y, 6)]],
                "entity_count": len(msp), "entity_types": counts, "layers": layers,
                "blocks": [b.name for b in doc.blocks if not b.name.startswith("*")
                           and not b.name.lower().startswith(("*model_space", "*paper_space"))],
                "tags": tags, "metadata": meta, "status": store.status(),
                "checkpoints": [c["id"] for c in store.list_checkpoints()]}

    @tool
    def inspect_entities(self, path: str, filter: dict | None = None, ids: list[str] | None = None,  # noqa: A002
                         limit: int = 200, offset: int = 0, detail: bool = True,
                         window: list | None = None) -> dict[str, Any]:
        p, store = self._drawing(path)
        doc = store.load()
        if ids:
            ents = select(doc, ids)
        elif filter:
            ents = select(doc, filter, allow_empty=True)
        else:
            ents = list(doc.modelspace())
        if window:
            (x0, y0), (x1, y1) = window
            lo, hi = (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))
            keep = []
            for e in ents:
                ext = bbox.extents([e], fast=True)
                if ext.has_data and ext.extmax.x >= lo[0] and ext.extmin.x <= hi[0] and ext.extmax.y >= lo[1] and ext.extmin.y <= hi[1]:
                    keep.append(e)
            ents = keep
        limit = max(1, min(int(limit), 5000))
        page = ents[offset:offset + limit]
        return {"drawing": self._rel(p), "units": _units_of(doc), "total": len(ents), "offset": offset,
                "returned": len(page), "entities": [entity_to_dict(e, detail=detail) for e in page],
                "next_offset": offset + limit if offset + limit < len(ents) else None}

    @tool
    def apply_operations(self, path: str, operations: list[dict], dry_run: bool = False,
                         requirements: list[dict] | None = None, strict: bool = False,
                         label: str | None = None) -> dict[str, Any]:
        """Run a batch atomically. ``strict``: abort (no save) if post-validation finds errors."""
        if not dry_run:
            self.policy.check_write()
        p, store = self._drawing(path)
        with self._lock(store):
            doc = store.load()
            unit = _units_of(doc)
            try:
                res = engine.execute(doc, operations, unit, self.policy)
            except AgentCADError as exc:
                store.journal({"tool": "apply_operations", "ok": False, "label": label, "operations": operations,
                               "error": exc.to_dict(), "file_unchanged": True})
                raise
            if dry_run:
                return {"drawing": self._rel(p), "dry_run": True, "would_change": _changes(res),
                        "results": res["results"]}
            tmp_report = self._validate_doc(doc, requirements)
            if strict and not tmp_report["passed"]:
                fail = self._save_failure(store, doc, "strict-validation")
                store.journal({"tool": "apply_operations", "ok": False, "label": label, "operations": operations,
                               "error": {"code": "VALIDATION_FAILED"}, "failure_snapshot": fail})
                raise AgentCADError("VALIDATION_FAILED", "Post-operation validation failed; nothing was saved",
                                    category="validation", details={"validation": tmp_report, "failure_snapshot": fail},
                                    hint="Inspect validation.issues; fix the operations and retry")
            info = store.commit(doc, label=label or "apply_operations")
            seq = store.journal({"tool": "apply_operations", "ok": True, "label": label, "operations": operations,
                                 "changes": _changes(res), **info})
        report = validate_file(p, requirements=requirements)
        return {"drawing": self._rel(p), "changes": _changes(res), "results": res["results"],
                "validation": _brief(report), "journal_seq": seq, **info}

    def _validate_doc(self, doc, requirements):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "candidate.dxf"
            doc.saveas(fp)
            return validate_file(fp, requirements=requirements)

    @tool
    def validate_drawing(self, path: str, requirements: list[dict] | None = None, use_stored_spec: bool = True,
                         bounds: list | None = None, tolerance: float = 1e-6,
                         contour_layers: list[str] | None = None) -> dict[str, Any]:
        """Independent validation: re-reads the file from disk. If the drawing carries a part spec and no
        explicit requirements are given, requirements are re-derived from that spec (not from the plan)."""
        p, store = self._drawing(path)
        reqs = requirements
        source = "explicit" if requirements else None
        if reqs is None and use_stored_spec:
            try:
                doc = read_dxf(p, self.policy)
                stored = get_meta(doc, "part_spec")
                if stored:
                    reqs = specmod.compile_spec(stored)["requirements"]
                    source = "stored_part_spec"
                    contour_layers = contour_layers or ["OUTLINE"]
            except AgentCADError:
                pass  # unreadable: validate_file reports it
        report = validate_file(p, requirements=reqs, bounds=bounds, tolerance=tolerance, contour_layers=contour_layers)
        report["file"] = self._rel(p)
        report["requirements_source"] = source
        return {"drawing": self._rel(p), "validation": report}

    @tool
    def apply_constraints(self, path: str, constraints: list[dict], mode: str = "check",
                          tolerance: float = 1e-6) -> dict[str, Any]:
        """mode=check: evaluate only. mode=enforce: sequential direct enforcement (not a simultaneous solver),
        then re-check all constraints; saves only if every constraint is satisfied."""
        if mode not in ("check", "enforce"):
            raise input_error("INVALID_ENUM", "mode must be 'check' or 'enforce'")
        p, store = self._drawing(path)
        doc = store.load()
        if mode == "check":
            res = check_constraints(doc, constraints, tolerance=tolerance)
            return {"drawing": self._rel(p), "mode": "check", "constraints": res,
                    "all_satisfied": all(r.get("satisfied") for r in res)}
        self.policy.check_write()
        with self._lock(store):
            doc = store.load()
            touched: list[str] = []
            for i, c in enumerate(constraints):
                try:
                    for h in enforce_one(doc, c):
                        if h not in touched:
                            touched.append(h)
                except AgentCADError as exc:
                    exc.op_index = i
                    exc.op = f"enforce:{c.get('type')}"
                    raise
            res = check_constraints(doc, constraints, tolerance=tolerance)
            ok = all(r.get("satisfied") for r in res)
            if not ok:
                raise AgentCADError("CONSTRAINT_CONFLICT", "Sequential enforcement could not satisfy all constraints "
                                    "simultaneously; nothing was saved", category="geometry",
                                    entities=touched, details={"constraints": res},
                                    hint="Constraints conflict or need a simultaneous solver; reorder or relax them")
            info = store.commit(doc, label="apply_constraints")
            seq = store.journal({"tool": "apply_constraints", "ok": True, "constraints": constraints,
                                 "changes": {"added": [], "modified": touched, "deleted": []}, **info})
        return {"drawing": self._rel(p), "mode": "enforce", "solver": "sequential-direct", "constraints": res,
                "all_satisfied": True, "changes": {"added": [], "modified": touched, "deleted": []},
                "journal_seq": seq, **info}

    @tool
    def draw_from_spec(self, spec: dict, output: str, overwrite: bool = False,
                       dxf_version: str = "R2010") -> dict[str, Any]:
        self.policy.check_write()
        compiled = specmod.compile_spec(spec)
        p, store = self._drawing(output, must_exist=False)
        if p.exists() and not overwrite:
            raise input_error("FILE_EXISTS", f"{output} already exists",
                              hint="Use revise_drawing to change it, or overwrite=true to regenerate")
        doc = setup_document(compiled["units"], "mechanical", dxf_version)
        with self._lock(store):
            try:
                res = engine.execute(doc, compiled["operations"], compiled["units"], self.policy)
            except AgentCADError as exc:
                store.journal({"tool": "draw_from_spec", "ok": False, "spec": spec, "error": exc.to_dict()})
                raise
            set_meta(doc, "part_spec", spec)
            set_meta(doc, "plan_tags", sorted(engine.plan_tags(compiled["operations"])))
            info = store.commit(doc, label="draw_from_spec")
            seq = store.journal({"tool": "draw_from_spec", "ok": True, "spec": spec, "plan": compiled["operations"],
                                 "changes": _changes(res), **info})
        report = validate_file(p, requirements=compiled["requirements"],
                               contour_layers=["OUTLINE"] if spec.get("kind") == "plate" else None)
        report["file"] = self._rel(p)
        return {"drawing": self._rel(p), "changes": _changes(res), "plan_size": len(compiled["operations"]),
                "requirements": compiled["requirements"], "validation": report, "journal_seq": seq, **info}

    @tool
    def revise_drawing(self, path: str, changes: dict, dry_run: bool = False) -> dict[str, Any]:
        """Spec-level revision: merge ``changes`` into the drawing's stored part spec, recompile and reconcile
        by tag (existing entities are updated in place; untagged / foreign entities are untouched)."""
        if not dry_run:
            self.policy.check_write()
        p, store = self._drawing(path)
        with self._lock(store):
            doc = store.load()
            old = get_meta(doc, "part_spec")
            if not old:
                raise input_error("NO_PART_SPEC", "This drawing has no stored part spec",
                                  hint="Use apply_operations (e.g. stretch / modify) for drawings not made from a spec")
            new_spec = specmod.merge(old, changes)
            compiled = specmod.compile_spec(new_spec)
            if compiled["units"] != _units_of(doc):
                raise input_error("UNITS_MISMATCH", f"Spec units {compiled['units']} != drawing units {_units_of(doc)}")
            prev = set(get_meta(doc, "plan_tags", []))
            res = engine.execute(doc, compiled["operations"], compiled["units"], self.policy, reconcile=True,
                                 previous_tags=prev)
            if dry_run:
                return {"drawing": self._rel(p), "dry_run": True, "would_change": _changes(res), "spec": new_spec}
            set_meta(doc, "part_spec", new_spec)
            set_meta(doc, "plan_tags", sorted(engine.plan_tags(compiled["operations"])))
            info = store.commit(doc, label="revise_drawing")
            seq = store.journal({"tool": "revise_drawing", "ok": True, "changes_requested": changes, "spec": new_spec,
                                 "changes": _changes(res), **info})
        report = validate_file(p, requirements=compiled["requirements"], contour_layers=["OUTLINE"])
        report["file"] = self._rel(p)
        return {"drawing": self._rel(p), "spec": new_spec, "changes": _changes(res), "unchanged": res["unchanged"],
                "validation": report, "journal_seq": seq, **info}

    @tool
    def extract_requirements(self, document: str, facts: list[dict] | None = None,
                             overrides: dict | None = None) -> dict[str, Any]:
        """Parse a PDF/TXT/MD spec into a structured plate spec with sources. ``facts`` (agent-supplied, each with a
        quote + page) are citation-checked and used instead of the built-in rule extractor."""
        from .docspec import build_spec, extract_facts, load_document, verify_citations
        dp = self.policy.resolve(document, must_exist=True, suffixes=(".pdf", ".txt", ".md", ".markdown"))
        pages = load_document(dp, self.policy.max_document_bytes)
        fs = verify_citations(pages, facts) if facts else extract_facts(pages)
        built = build_spec(fs, overrides)
        return {"document": self._rel(dp), "pages": len(pages), "extractor": "agent-citations" if facts else "rules",
                "facts": fs, **built}

    @tool
    def revise_from_document(self, document: str, output: str, facts: list[dict] | None = None,
                             overrides: dict | None = None, overwrite: bool = False) -> dict[str, Any]:
        """Document → spec → drawing (new, or reconciled into an existing spec-made drawing) → check against the
        document's requirements. Refuses to draw while required values are missing or contradictory."""
        ex = TOOLS["extract_requirements"](self, document, facts, overrides)
        if ex["status"] != "ok":
            errs = [i for i in ex["issues"] if i["severity"] == "error"]
            raise AgentCADError("SPEC_CONFLICT" if ex["status"] == "conflict" else "SPEC_INCOMPLETE",
                                f"Document requirements are {ex['status']}: " + "; ".join(i["message"] for i in errs),
                                category="spec", details={"issues": ex["issues"], "facts": ex["facts"],
                                                          "partial_spec": ex["spec"]},
                                hint="Resolve via 'overrides' (recorded as caller decisions) or fix the document")
        spec = ex["spec"]
        spec.setdefault("dimensions", "full")
        spec.setdefault("name", Path(document).stem)
        op, _ = self._drawing(output, must_exist=False)
        if op.exists() and not overwrite:
            existing = read_dxf(op, self.policy)
            if get_meta(existing, "part_spec"):
                changes = {k: v for k, v in spec.items()}
                res = TOOLS["revise_drawing"](self, output, changes)
                mode = "revised"
            else:
                raise input_error("FILE_EXISTS", f"{output} exists and was not made from a spec", hint="overwrite=true")
        else:
            res = TOOLS["draw_from_spec"](self, spec, output, overwrite=overwrite)
            mode = "created"
        # requirement-by-requirement trace back to the document
        trace = []
        for r in res["validation"]["requirements"]:
            src = r.get("source")
            trace.append({"requirement": r["id"], "status": r["status"], "expected": r["expected"],
                          "actual": r["actual"], "deviation": r["deviation"], "tolerance": r["tolerance"],
                          "document_source": src})
        return {"drawing": res["drawing"], "mode": mode, "spec": spec, "issues": ex["issues"],
                "traceability": ex["traceability"], "verification": trace,
                "validation": res["validation"], "journal_seq": res["journal_seq"]}

    @tool
    def get_diff(self, path: str, against: str = "previous") -> dict[str, Any]:
        """Diff the drawing against 'previous' (latest checkpoint), a checkpoint id, or another .dxf path."""
        p, store = self._drawing(path)
        cur = store.load()
        if against == "previous":
            cps = store.list_checkpoints()
            if not cps:
                raise input_error("NO_CHECKPOINT", "Drawing has no checkpoints to diff against")
            other_path = store.checkpoint_path(cps[-1]["id"])
            label = cps[-1]["id"]
        elif against.startswith("cp-"):
            other_path = store.checkpoint_path(against)
            label = against
        else:
            other_path = self.policy.resolve(against, must_exist=True, suffixes=(".dxf",))
            label = self._rel(other_path)
        old = read_dxf(other_path, self.policy)
        return {"drawing": self._rel(p), "against": label, **diff_docs(old, cur)}

    @tool
    def rollback(self, path: str, checkpoint: str | None = None) -> dict[str, Any]:
        """Restore a checkpoint (default: the latest). The pre-rollback state is checkpointed too."""
        self.policy.check_write()
        p, store = self._drawing(path, must_exist=False)
        cps = store.list_checkpoints()
        if not cps:
            raise input_error("NO_CHECKPOINT", "Drawing has no checkpoints")
        cid = checkpoint or cps[-1]["id"]
        with self._lock(store):
            info = store.restore(cid, label=f"rollback to {cid}")
            seq = store.journal({"tool": "rollback", "ok": True, "checkpoint": cid, **info})
        return {"drawing": self._rel(p), "journal_seq": seq, **info}

    @tool
    def list_checkpoints(self, path: str) -> dict[str, Any]:
        p, store = self._drawing(path, must_exist=False)
        return {"drawing": self._rel(p), "checkpoints": store.list_checkpoints()}

    @tool
    def history(self, path: str, limit: int = 50) -> dict[str, Any]:
        p, store = self._drawing(path, must_exist=False)
        recs = store.read_journal(limit)
        return {"drawing": self._rel(p), "records": recs}

    @tool
    def recover(self, path: str) -> dict[str, Any]:
        """Crash recovery: if the file is unreadable, or an interrupted transaction left it inconsistent, restore
        the most recent checkpoint whose content is a valid DXF."""
        p, store = self._drawing(path, must_exist=False)
        st = store.status()
        needed = (not st["exists"]) or (not st["readable"]) or bool(st["pending_transaction"])
        if not needed:
            return {"drawing": self._rel(p), "recovered": False, "status": st}
        self.policy.check_write()
        from .store import sha256_file
        candidates = []
        if store.committed_path.is_file() and sha256_file(store.committed_path) == st["committed_sha256"]:
            candidates.append({"id": "committed"})  # exact last committed state
        candidates += list(reversed(store.list_checkpoints()))
        for cp in candidates:
            try:
                read_dxf(store.committed_path if cp["id"] == "committed" else store.checkpoint_path(cp["id"]), self.policy)
            except AgentCADError:
                continue
            with self._lock(store):
                if st["exists"]:
                    bad = store.dir / "failed" / f"{time.strftime('%Y%m%d-%H%M%S')}-corrupt.dxf"
                    bad.parent.mkdir(parents=True, exist_ok=True)
                    bad.write_bytes(p.read_bytes())
                info = store.restore(cp["id"], label="recover")
                seq = store.journal({"tool": "recover", "ok": True, "from_status": st, **info})
            return {"drawing": self._rel(p), "recovered": True, "restored_checkpoint": cp["id"], "previous_status": st,
                    "journal_seq": seq}
        raise AgentCADError("NO_VALID_CHECKPOINT", "No readable checkpoint to recover from", category="file",
                            details={"status": st})

    @tool
    def export_drawing(self, path: str, output: str, format: str = "dxf",  # noqa: A002
                       dxf_version: str | None = None, overwrite: bool = False) -> dict[str, Any]:
        """Export to dxf (optionally another DXF version, incl. R12 via ezdxf.addons.r12export), svg, json, or
        dwg (optional AutoCAD backend; ``dxf_version`` then selects the DWG release, default 2018)."""
        self.policy.check_write()
        p, store = self._drawing(path)
        fmt = format.lower()
        suffix = {"dxf": ".dxf", "svg": ".svg", "json": ".json", "dwg": ".dwg"}.get(fmt)
        if suffix is None:
            raise input_error("UNSUPPORTED_FORMAT", f"Unsupported export format {format!r}", hint="dxf | svg | json | dwg")
        out = self.policy.resolve(output, suffixes=(suffix,))
        if out.exists() and not overwrite:
            raise input_error("FILE_EXISTS", f"{output} exists", hint="overwrite=true")
        if out == p:
            raise input_error("SAME_FILE", "Export target must differ from the source drawing")
        if fmt == "dwg":
            from .backends import autocad
            ver = (dxf_version or "2018").removeprefix("R")
            if ver not in autocad.DWG_VERSIONS:
                raise input_error("UNSUPPORTED_DWG_VERSION", f"DWG version {dxf_version!r} not supported",
                                  hint=f"Use one of {sorted(autocad.DWG_VERSIONS)}")
            jobs = self.policy.state_dir() / "acad"
            info = autocad.dxf_to_dwg(p, out, jobs, ver)
            # read the DWG back through AutoCAD and validate the resulting DXF independently
            back = jobs / f"readback-{out.stem}.dxf"
            autocad.dwg_to_dxf(out, back, jobs, "2018")
            rb = validate_file(back)
            src_n = len(store.load().modelspace())
            store.journal({"tool": "export_drawing", "ok": True, "output": self._rel(out), "format": "dwg"})
            return {"drawing": self._rel(p), "output": self._rel(out), "format": "dwg", "dwg_version": ver,
                    "bytes": info["bytes"], "backend": "autocad", "seconds": info["seconds"],
                    "readback": {"readable": rb["readable"], "entities": rb.get("recognized", {}).get("entity_count"),
                                 "source_entities": src_n, "issues": rb["issues"][:20]}}
        doc = store.load()
        finalize(doc)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "dxf":
            ver = dxf_version or doc.acad_release
            if ver == "R12":
                from ezdxf.addons import r12export
                r12export.saveas(doc, out)
                clean_r12(out)
            else:
                if ver not in DXF_VERSIONS:
                    raise input_error("UNSUPPORTED_DXF_VERSION", f"Unknown DXF version {ver!r}")
                doc.dxfversion = DXF_VERSIONS[ver]
                doc.saveas(out)
            back = validate_file(out)
            extra = {"dxf_version": ver, "reread_ok": back["readable"]}
            if ver == "R12":
                extra["warnings"] = ["DXF R12 has no $INSUNITS: the unit is not stored in the exported file",
                                     "LWPOLYLINE exported as POLYLINE; tags/metadata are not guaranteed"]
        elif fmt == "svg":
            try:
                from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
            except ImportError as exc:
                raise AgentCADError("DEPENDENCY_MISSING", f"SVG preview needs an optional package: {exc}",
                                    category="dependency", hint="pip install 'agentcad[preview]' (Pillow)")
            from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
            backend = svg.SVGBackend()
            cfg = Configuration(background_policy=BackgroundPolicy.WHITE)
            Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace())
            page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(5))
            out.write_text(backend.get_string(page), "utf-8")
            extra = {}
        else:
            data = {"units": _units_of(doc), "metadata": all_meta(doc),
                    "entities": [entity_to_dict(e) for e in doc.modelspace()]}
            out.write_text(json.dumps(data, indent=1, ensure_ascii=False), "utf-8")
            extra = {"entity_count": len(data["entities"])}
        store.journal({"tool": "export_drawing", "ok": True, "output": self._rel(out), "format": fmt})
        return {"drawing": self._rel(p), "output": self._rel(out), "format": fmt, "bytes": out.stat().st_size, **extra}

    @tool
    def import_drawing(self, source: str, output: str, overwrite: bool = False) -> dict[str, Any]:
        """Import a DWG into the workspace as DXF through the optional AutoCAD backend, then validate it."""
        self.policy.check_write()
        from .backends import autocad
        src = self.policy.resolve(source, must_exist=True, suffixes=(".dwg",))
        out, store = self._drawing(output, must_exist=False)
        if out.exists() and not overwrite:
            raise input_error("FILE_EXISTS", f"{output} exists", hint="overwrite=true")
        jobs = self.policy.state_dir() / "acad"
        tmp = jobs / f"import-{out.stem}.dxf"
        info = autocad.dwg_to_dxf(src, tmp, jobs, "2018")
        doc = read_dxf(tmp, self.policy)
        with self._lock(store):
            commit = store.commit(doc, label="import_drawing")
            seq = store.journal({"tool": "import_drawing", "ok": True, "source": self._rel(src), **commit})
        rep = validate_file(out)
        return {"drawing": self._rel(out), "source": self._rel(src), "backend": "autocad", "seconds": info["seconds"],
                "units": _units_of(doc), "entity_count": len(doc.modelspace()), "validation": _brief(rep),
                "journal_seq": seq, **commit}

    @tool
    def autocad_audit(self, path: str) -> dict[str, Any]:
        """Open the DXF in AutoCAD (headless, optional backend) and run AUDIT without fixing: a second,
        independent opinion on file validity from the reference implementation."""
        from .backends import autocad
        p, _ = self._drawing(path)
        res = autocad.audit_dxf(p, self.policy.state_dir() / "acad")
        res["passed"] = not res["import_rejected"] and res["audit_errors"] == 0
        return {"drawing": self._rel(p), "backend": "autocad", **res}

    @tool
    def get_metrics(self) -> dict[str, Any]:
        calls = len(self.metrics)
        fails = sum(1 for m in self.metrics if not m["ok"])
        return {"tool_calls": calls, "failures": fails,
                "total_duration_ms": round(sum(m["duration_ms"] for m in self.metrics), 2),
                "input_bytes": sum(m["input_bytes"] for m in self.metrics),
                "output_bytes": sum(m["output_bytes"] for m in self.metrics),
                "model_calls": 0, "model_cost_usd": 0.0, "calls": self.metrics[-200:]}


def clean_r12(path: Path) -> None:
    """Post-process ezdxf's R12 export so AutoCAD's AUDIT accepts it.

    Observed in AutoCAD 2027 (research/autocad/exp_r12_bisect.py): BYBLOCK/BYLAYER
    LTYPE entries (built-ins, not table records in R12) and unused text styles
    trigger 233 audit errors on DXFIN; removing both gives 0.
    """
    doc = ezdxf.readfile(path)
    for name in ("BYBLOCK", "BYLAYER"):
        if name in doc.linetypes:
            doc.linetypes.remove(name)
    used = {"STANDARD"}
    for layout in [doc.modelspace(), *doc.blocks]:
        for e in layout:
            if e.dxf.hasattr("style"):
                used.add(e.dxf.style.upper())
    for ds in doc.dimstyles:
        if ds.dxf.hasattr("dimtxsty"):
            used.add(str(ds.dxf.dimtxsty).upper())
    for s in [s.dxf.name for s in doc.styles]:
        if s.upper() not in used:
            doc.styles.remove(s)
    doc.saveas(path)


def _changes(res: dict[str, Any]) -> dict[str, Any]:
    return {"added": res["added"], "modified": res["modified"], "deleted": res["deleted"]}


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    return {"passed": report["passed"], "summary": report["summary"], "issues": report["issues"][:50],
            "requirements": report["requirements"]}


def diff_docs(old, new) -> dict[str, Any]:
    a = {e.dxf.handle: entity_to_dict(e) for e in old.modelspace()}
    b = {e.dxf.handle: entity_to_dict(e) for e in new.modelspace()}
    added = [b[h] for h in b if h not in a]
    deleted = [a[h] for h in a if h not in b]
    modified = []
    for h in a.keys() & b.keys():
        if a[h] != b[h]:
            fields = {k: {"old": a[h].get(k), "new": b[h].get(k)} for k in set(a[h]) | set(b[h]) if a[h].get(k) != b[h].get(k)}
            modified.append({"id": h, "type": b[h]["type"], "tag": b[h].get("tag"), "changes": fields})
    modified.sort(key=lambda m: m["id"])
    unchanged = len([h for h in a.keys() & b.keys() if a[h] == b[h]])
    layers_old = {l.dxf.name for l in old.layers}
    layers_new = {l.dxf.name for l in new.layers}
    return {"summary": {"added": len(added), "deleted": len(deleted), "modified": len(modified), "unchanged": unchanged},
            "added": added, "deleted": deleted, "modified": modified,
            "layers": {"added": sorted(layers_new - layers_old), "deleted": sorted(layers_old - layers_new)}}
