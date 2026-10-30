"""Unified business API. CLI, MCP server and HTTP server are thin adapters over
``Runtime`` methods; every method returns a JSON-serialisable envelope::

    {"ok": true|false, "tool": "<name>", ...payload..., "error": {...}?, "metrics": {...}}
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import time
import traceback
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import ezdxf
from ezdxf import bbox

from . import engine, guards, progress, spec as specmod
from .constraints import ENFORCE_TYPES, CHECK_TYPES, check_constraints, enforce_one
from .errors import AgentCADError, input_error, policy_error
from .metadata import all_meta, get_meta, set_meta
from .model import entity_to_dict, get_tag, is_model, layout_spaces, select
from .ops import catalog
from .ops.annotate import DIMSTYLE, apply_annotation_scale, setup_text_style
from .part import service as part
from .policy import Policy
from .store import DrawingStore, busy_error, finalize, read_dxf, now, sha256_file
from .units import UNITS, normalize_unit, unit_from_insunits
from .validate import validate_file
from .validate.checks import MIN_PRINTED_TEXT

DXF_VERSIONS = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024",
                "R2013": "AC1027", "R2018": "AC1032"}

TOOLS: dict[str, Callable] = {}
# tools that change a drawing: with AGENTCAD_LIVE_SYNC the drawing is re-opened in a running AutoCAD afterwards
LIVE_SYNC_TOOLS = {"create_drawing", "apply_operations", "run_script", "apply_constraints", "draw_from_spec",
                   "revise_drawing", "revise_from_document", "rollback", "recover", "import_drawing"}
LIVE_ACTIONS = ("status", "open", "reload", "pull", "zoom", "command")
# tools whose results carry viewer_url (the live viewer's page for the drawing they changed)
VIEWER_TOOLS = LIVE_SYNC_TOOLS | {"apply_batch"}
# tools that report progress to the live viewer (progress.py): name -> the argument naming the drawing
PROGRESS_TOOLS = {"create_drawing": "path", "apply_operations": "path", "run_script": "path",
                  "apply_constraints": "path", "draw_from_spec": "output", "revise_drawing": "path",
                  "revise_from_document": "output", "rollback": "path", "recover": "path",
                  "import_drawing": "output", "validate_drawing": "path"}


def _live_base(store, path: Path | None = None) -> str | None:
    """sha256 of the file version AutoCAD opened (set when ``path`` is given, else read)."""
    f = store.dir / "live.json"
    if path is None:
        try:
            return json.loads(f.read_text("utf-8")).get("base_sha256")
        except (OSError, ValueError):
            return None
    store.dir.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"base_sha256": sha256_file(path)}), "utf-8")
    return None


def tool(fn):
    """Wrap a Runtime method into the standard envelope with metrics and error capture."""
    name = fn.__name__

    sig = inspect.signature(fn)

    @wraps(fn)
    def wrapper(self: "Runtime", *args, **kwargs):
        t0 = time.perf_counter()
        in_bytes = len(json.dumps([args, kwargs], default=str))
        act, ops = self._activity(name, sig, args, kwargs)
        token = progress.begin(act) if act else None
        try:
            payload = fn(self, *args, **kwargs)
            env = {"ok": True, "tool": name, **payload}
        except AgentCADError as exc:
            env = {"ok": False, "tool": name, "error": exc.to_dict()}
        except Exception as exc:  # never leak a raw traceback as the only signal
            env = {"ok": False, "tool": name,
                   "error": AgentCADError("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", category="internal",
                                          details={"traceback": traceback.format_exc(limit=8)}).to_dict()}
        finally:
            if token is not None:
                progress.end(token)
        if act:
            act.finish(env, ops)
        if (env["ok"] and name in LIVE_SYNC_TOOLS and self.policy.live_sync and env.get("drawing")
                and not env.get("dry_run")):
            env["live"] = self._live_sync(env["drawing"])
        if env["ok"] and name in VIEWER_TOOLS and not env.get("dry_run"):
            url = self._viewer_link(env)
            if url:
                env["viewer_url"] = url
        env["metrics"] = {"duration_ms": round((time.perf_counter() - t0) * 1000, 2), "input_bytes": in_bytes,
                          "output_bytes": len(json.dumps(env, default=str))}
        self.metrics.append({"tool": name, "ok": env["ok"], **env["metrics"]})
        return env

    TOOLS[name] = fn
    wrapper.__agentcad_tool__ = True  # type: ignore[attr-defined]
    return wrapper


def _op_names(ops: Any) -> list[str] | None:
    """Op names as a list. Agents also send them as one string: a JSON list ('["pad","pocket"]') or 'pad, pocket'."""
    if ops is None or isinstance(ops, list):
        return ops or None
    if isinstance(ops, str):
        s = ops.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, list) and all(isinstance(o, str) for o in parsed):
                return parsed or None
        return [o.strip().strip("'\"") for o in s.strip("[]").split(",") if o.strip()] or None
    raise input_error("BAD_PARAMETER", "ops: a list of operation names")


def _paper_layouts(doc) -> list[dict[str, Any]]:
    """Paper-space layouts with their content. A layout holding geometry (not just viewports) is often the
    printed sheet: a scaled copy of the part, title block and notes that must be edited along with the model."""
    out = []
    for name in doc.layouts.names_in_taborder():
        if is_model(name):
            continue
        lay = doc.layouts.get(name)
        types: dict[str, int] = {}
        for e in lay:
            types[e.dxftype()] = types.get(e.dxftype(), 0) + 1
        content = sum(n for t, n in types.items() if t != "VIEWPORT")
        ext = bbox.extents((e for e in lay if e.dxftype() != "VIEWPORT"), fast=True)
        from .ops.sheet import page_setup_info
        out.append({"name": name, "entity_count": content, "entity_types": types, "page_setup": page_setup_info(lay),
                    "viewports": max(0, types.get("VIEWPORT", 0) - 1),
                    "extents": None if not ext.has_data else [[round(ext.extmin.x, 6), round(ext.extmin.y, 6)],
                                                              [round(ext.extmax.x, 6), round(ext.extmax.y, 6)]]})
    return out


def _units_of(doc) -> str | None:
    return unit_from_insunits(doc.header.get("$INSUNITS", 0))


def setup_document(units: str, template: str, version: str, annotation_scale: float = 1.0):
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
    setup_text_style(doc)
    if annotation_scale <= 0:
        raise input_error("INVALID_VALUE", "annotation_scale must be > 0", hint="e.g. 1 for parts, 50 for building plans in mm")
    apply_annotation_scale(doc, float(annotation_scale))
    if template == "mechanical":
        for o in specmod.LAYERS:
            lt = o.get("linetype", "Continuous")
            doc.layers.add(o["name"], color=o["color"], linetype=lt, lineweight=o["lineweight"])
    elif template != "blank":
        raise input_error("UNKNOWN_TEMPLATE", f"Unknown template {template!r}", hint="Use 'blank' or 'mechanical'")
    set_meta(doc, "created", {"by": "agentcad", "units": units, "template": template, "ts": now()})
    return doc


class Runtime:
    def __init__(self, policy: Policy | None = None, auto_viewer: bool = False) -> None:
        """``auto_viewer``: start the live viewer in the background on the first change (the MCP server sets it;
        AGENTCAD_VIEWER=0 in the environment turns it off)."""
        self.policy = policy or Policy()
        self.metrics: list[dict[str, Any]] = []
        self.auto_viewer = auto_viewer and os.environ.get("AGENTCAD_VIEWER", "1").strip().lower() not in \
            {"0", "false", "no", "off"}
        self._viewer = None
        self._viewer_retry = 0.0

    # --- helpers ---------------------------------------------------------------------------
    def _drawing(self, path: str, must_exist: bool = True, part_ok: bool = False) -> tuple[Path, DrawingStore]:
        """``part_ok``: the tool works on 3D parts (.FCStd) too, through the store alone."""
        if part_ok and part.is_part(path):
            return part.store_for(self, path, must_exist)
        p = self.policy.resolve(path, must_exist=must_exist, suffixes=(".dxf",),
                                hint_suffix=" (3D parts: .FCStd)")
        return p, DrawingStore(self.policy, p)

    @contextmanager
    def _lock(self, store: DrawingStore):
        from .locking import drawing_lock
        with drawing_lock(store.dir):
            yield

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

    def _activity(self, name: str, sig: inspect.Signature, args: tuple, kwargs: dict):
        """(progress.Activity, operations) for a call the live viewer follows, else (None, None). A call nested in
        another one on the same drawing (apply_operations(create=...) creating it) is not reported separately."""
        arg = PROGRESS_TOOLS.get(name)
        if arg is None or self.policy.read_only:
            return None, None
        try:
            bound = sig.bind_partial(self, *args, **kwargs).arguments
            if bound.get("dry_run") or not isinstance(bound.get(arg), str):
                return None, None
            drawing = self._rel(self.policy.resolve(bound[arg]))
            outer = progress.current()
            if outer is not None and outer.drawing == drawing:
                return None, None
            ops = bound.get("operations") if isinstance(bound.get("operations"), list) else None
            act = progress.Activity(self.policy, name, drawing)
            checks = name == "validate_drawing" or (name == "apply_constraints"
                                                    and bound.get("mode", "check") == "check")
            act.emit("checking" if checks else "working", step=0, total=len(ops) if ops is not None else None)
            return act, ops
        except Exception:  # noqa: BLE001 - a bad path fails the call itself, with its own error
            return None, None

    def _viewer_link(self, env: dict[str, Any]) -> str | None:
        """The live viewer's page for the drawing a call changed. With ``auto_viewer`` (the MCP server) a viewer is
        started in the background on the first change if none serves this root (AGENTCAD_VIEWER=0 turns that off)."""
        drawing = env.get("drawing")
        if not drawing and env.get("jobs"):
            drawing = next((j["path"] for j in env["jobs"] if j.get("ok")), "")
        drawing = drawing or ""
        try:
            from .viewer import serves_root, viewer_url
            if self._viewer is not None:  # ours, but check it is still the one answering on its port
                if serves_root(self._viewer.url, self.policy):
                    return f"{self._viewer.url}#{drawing}"
                self._viewer.stop()
                self._viewer = None
            url = viewer_url(self.policy, drawing)
            if url or not self.auto_viewer or time.monotonic() < self._viewer_retry:
                return url
            from .viewer import start_background
            self._viewer = start_background(self.policy)
            if self._viewer is None:
                self._viewer_retry = time.monotonic() + 60
                return None
            return f"{self._viewer.url}#{drawing}"
        except Exception:  # noqa: BLE001 - the viewer is a convenience; the change is already committed
            return None

    def live_connect(self, start: bool = False):
        """The running AutoCAD (COM), or None; replaced in tests."""
        from .backends import acad_live
        return acad_live.connect(start)

    def _live_sync(self, drawing: str) -> dict[str, Any]:
        from .backends import acad_live
        try:
            with acad_live.com_thread():
                app = self.live_connect()
                if app is None:
                    return {"autocad_running": False}
                p, store = self._drawing(drawing)
                with self._lock(store):
                    res = acad_live.Session(app).reload(p)
                    if res.get("reloaded"):
                        _live_base(store, p)
                return res
        except AgentCADError as exc:  # never fail a committed change because AutoCAD could not follow
            e = exc.to_dict()
            return {"reloaded": False, "error": {k: e[k] for k in ("code", "message", "hint") if k in e}}
        except Exception as exc:  # noqa: BLE001 - same: the change is already committed
            return {"reloaded": False, "error": {"code": "AUTOCAD_COM_ERROR", "message": f"{type(exc).__name__}: {exc}"}}

    # --- tools ------------------------------------------------------------------------------------
    @tool
    def list_operations(self, category: str | None = None, ops: list[str] | str | None = None,
                        detail: bool = False) -> dict[str, Any]:
        """Default: a compact index (name, category, one-line summary, parameter names; * = required), ~9K chars.
        Full JSON schemas for the ops named in 'ops', for one 'category', or for everything with detail=true.
        The full catalog is ~90K chars, more than Claude Code accepts in one tool result: 34 of 36 sessions in the
        Claude Code trials failed on their first list_operations call (docs/comparison-claude-code.md)."""
        from .ops import REGISTRY
        from .ops.registry import COMMON_ALL, COMMON_DRAW
        from .part.ops import PART_CONVENTIONS, PART_REGISTRY, part_schema
        ops = _op_names(ops)
        if category is not None and (category == "part" or category.startswith("part_")):
            names = ops or sorted(PART_REGISTRY)
            unknown = [o for o in names if o not in PART_REGISTRY]
            if unknown:
                raise input_error("UNKNOWN_OPERATION", f"Unknown part operation(s) {unknown}",
                                  hint=f"Part operations: {sorted(PART_REGISTRY)}")
            full = [part_schema(PART_REGISTRY[o]) for o in names
                    if category == "part" or PART_REGISTRY[o].category == category]
            return {"operations": full, "count": len(full), "detail": True, "kind": "part",
                    "conventions": PART_CONVENTIONS}
        constraints = {"check": sorted(CHECK_TYPES), "enforce": sorted(ENFORCE_TYPES)}
        cats = sorted({d.category for d in REGISTRY.values()})
        if category is not None and category not in cats:
            raise input_error("UNKNOWN_CATEGORY", f"No operation category {category!r}", hint=f"Categories: {cats}")
        if ops:
            # Names are looked up among drawing and part operations alike; fillet, chamfer and mirror exist for
            # both, and then both schemas come back, the part one marked kind='part'.
            unknown = [o for o in ops if o not in REGISTRY and o not in PART_REGISTRY]
            if unknown:
                raise input_error("UNKNOWN_OPERATION", f"Unknown operation(s) {unknown}",
                                  hint=f"Drawing operations: {sorted(REGISTRY)}; part operations: "
                                       f"{sorted(PART_REGISTRY)}")
            full: list[dict[str, Any]] = []
            for o in ops:
                if o in REGISTRY and (category is None or REGISTRY[o].category == category):
                    full.append(REGISTRY[o].schema())
                if o in PART_REGISTRY and category is None:
                    full.append({**part_schema(PART_REGISTRY[o]), "kind": "part"})
            if not full:
                where = {o: ("part" if o not in REGISTRY else REGISTRY[o].category) for o in ops}
                raise input_error("UNKNOWN_OPERATION", f"None of {ops} is a {category!r} operation",
                                  hint=f"Their categories: {where}. Leave out the category to get them; part "
                                       f"operations also come with category='part'")
            out = {"operations": full, "count": len(full), "detail": True, "constraint_types": constraints}
            if any(s.get("kind") == "part" for s in full):
                out["conventions"] = PART_CONVENTIONS
            return out
        if detail or category is not None:
            full = [o for o in catalog() if category is None or o["category"] == category]
            return {"operations": full, "count": len(full), "detail": True, "constraint_types": constraints}
        index = [{"op": d.name, "category": d.category, "summary": d.description.split(". ")[0].rstrip(".")[:100],
                  "params": [k + ("*" if p.required else "") for k, p in d.params.items()],
                  **({"draw_params": True} if d.common_draw else {})}
                 for d in (REGISTRY[k] for k in sorted(REGISTRY))]
        common = {"layout": "'Model' (default) or a paper-space layout name", "layer": "layer name, created if missing",
                  "color": "ACI color, 256 = BYLAYER", "linetype": "e.g. CONTINUOUS, CENTER, DASHED",
                  "lineweight": "1/100 mm, -1 = BYLAYER", "tag": "name for later reference as 'tag:<name>'",
                  "if_tag_exists": "error | skip | replace"}
        part_index: dict[str, list[str]] = {}  # names only: a 3D task fetches category='part' anyway
        for d in PART_REGISTRY.values():
            part_index.setdefault(d.category, []).append(d.name)
        return {"operations": index, "count": len(index), "detail": False, "categories": cats,
                "part_operations": part_index,
                "part_hint": "3D parts (.FCStd, FreeCAD) take part_operations in apply_operations; their "
                             "summaries and schemas: list_operations(category='part')",
                "common_params": {"all_ops": sorted(COMMON_ALL), "draw_params": sorted(COMMON_DRAW),
                                  "meaning": common},
                "constraint_types": constraints,
                "hint": "Parameters marked * are required. Ops with draw_params also take layer, color, linetype, "
                        "lineweight, tag, if_tag_exists; every op takes layout. For types, units, defaults and "
                        "limits call list_operations(ops=[...]) or list_operations(category=...)."}

    @tool
    def create_drawing(self, path: str, units: str = "mm", template: str = "mechanical", dxf_version: str = "R2010",
                       overwrite: bool = False, annotation_scale: float = 1.0) -> dict[str, Any]:
        if part.is_part(path):
            return part.create(self, path, units, overwrite)
        self.policy.check_write()
        u = normalize_unit(units)
        p, store = self._drawing(path, must_exist=False)
        if p.exists() and not overwrite:
            raise input_error("FILE_EXISTS", f"{path} already exists", hint="Pass overwrite=true to replace it (a checkpoint is kept)")
        doc = setup_document(u, template, dxf_version, annotation_scale)
        with self._lock(store):
            info = store.commit(doc, label="create_drawing")
            seq = store.journal({"tool": "create_drawing", "args": {"units": u, "template": template,
                                                                    "dxf_version": dxf_version,
                                                                    "annotation_scale": annotation_scale}, "ok": True, **info})
        return {"drawing": self._rel(p), "units": u, "dxf_version": dxf_version, "journal_seq": seq, **info}

    @tool
    def inspect_image(self, path: str, region: list[int] | None = None, max_size: int = 1536,
                      rotate: int = 0) -> dict[str, Any]:
        """Read a workspace image or magnify a region; return a PNG without writing files.

        region is [left, top, right, bottom] in displayed source pixels (top-left origin).
        The longest preview side is max_size. Pixel magnification adds no missing detail.
        """
        from .images import inspect_image
        return inspect_image(self.policy, path, region, max_size, rotate)

    @tool
    def read_drawing(self, path: str) -> dict[str, Any]:
        if part.is_part(path):
            return part.read(self, path)
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
                "layouts": _paper_layouts(doc),
                "tags": tags, "metadata": meta, "status": store.status(),
                "checkpoints": [c["id"] for c in store.list_checkpoints()]}

    @tool
    def inspect_entities(self, path: str, filter: dict | None = None, ids: list[str] | None = None,  # noqa: A002
                         limit: int = 200, offset: int = 0, detail: bool = True,
                         window: list | None = None, layout: str | None = None,
                         selection_mode: str = "crossing", polygon: list | None = None) -> dict[str, Any]:
        if part.is_part(path):
            return part.inspect(self, path, filter, limit, offset)
        p, store = self._drawing(path)
        doc = store.load()
        if ids:
            ents = select(doc, ids)
        elif filter:
            ents = select(doc, {"layout": layout, **filter} if layout else filter, allow_empty=True)
        else:
            ents = [e for sp in layout_spaces(doc, layout) for e in sp]
        if window is not None or polygon is not None:
            from .measure import spatial_filter
            ents = spatial_filter(ents, window, polygon, selection_mode)
        limit = max(1, min(int(limit), 5000))
        page = ents[offset:offset + limit]
        return {"drawing": self._rel(p), "units": _units_of(doc), "total": len(ents), "offset": offset,
                "returned": len(page), "entities": [{**entity_to_dict(e, detail=detail),
                    **({"fingerprint": guards.fingerprint(e)} if detail else {})} for e in page],
                "filtered_by": list((filter or {}).keys()),
                "next_offset": offset + limit if offset + limit < len(ents) else None}

    @tool
    def apply_operations(self, path: str, operations: list[dict], dry_run: bool = False,
                         requirements: list[dict] | None = None, strict: bool = False,
                         label: str | None = None, create: dict | None = None, bounds: list | None = None,
                         layout: str | None = None, expected_revision: int | None = None,
                         preconditions: dict | None = None) -> dict[str, Any]:
        """Run a batch atomically. ``strict``: abort (no save) if post-validation finds errors.
        ``create``: create the drawing first if it does not exist ({units, template, dxf_version, annotation_scale}),
        so a new drawing needs one call. The returned validation is the same independent re-read of the saved file
        as validate_drawing (``requirements``, ``bounds``, ``layout``), so a separate validate_drawing call is only
        needed for its detail=true report."""
        if part.is_part(path):
            if expected_revision is not None or preconditions is not None:
                raise input_error("UNSUPPORTED_GUARD", "Revision guards currently support DXF drawings")
            return part.apply(self, path, operations, dry_run, requirements, strict, label, create)
        if not dry_run:
            self.policy.check_write()
        created = None
        if create is not None:
            created = self._create_if_missing(path, create, dry_run)
        p, store = self._drawing(path)
        with self._lock(store):
            loaded_sha = sha256_file(p)
            doc = store.load()
            before = guards.check(store, doc, expected_revision, preconditions)
            if before["sha256"] != loaded_sha:
                raise input_error("STALE_REVISION", "Drawing changed while it was being read; retry the preview")
            unit = _units_of(doc)
            try:
                res = engine.execute(doc, operations, unit, self.policy)
            except AgentCADError as exc:
                store.journal({"tool": "apply_operations", "ok": False, "label": label, "operations": operations,
                               "error": exc.to_dict(), "file_unchanged": True})
                raise
            if dry_run:
                return {"drawing": self._rel(p), "dry_run": True, "would_change": _changes(res),
                        "results": res["results"], "preview": {"revision": before["revision"],
                            "preconditions": {"sha256": before["sha256"], "entities": before["entities"]}}}
            # without strict the pre-commit report is unused; the file is validated once, after the commit
            tmp_report = self._validate_doc(doc, requirements, bounds, layout) if strict else None
            if tmp_report is not None and not tmp_report["passed"]:
                fail = self._save_failure(store, doc, "strict-validation")
                store.journal({"tool": "apply_operations", "ok": False, "label": label, "operations": operations,
                               "error": {"code": "VALIDATION_FAILED"}, "failure_snapshot": fail})
                raise AgentCADError("VALIDATION_FAILED", "Post-operation validation failed; nothing was saved",
                                    category="validation",
                                    details={"validation": compact_report(tmp_report), "failure_snapshot": fail},
                                    hint="Inspect validation.issues; fix the operations and retry")
            attempt = {"tool": "apply_operations", "label": label, "operations": operations, "changes": _changes(res)}
            # Also refuse an external edit made during geometry computation or strict validation.
            guards.check(store, store.load(), before["revision"], {"sha256": before["sha256"]})
            info = store.commit(doc, label=label or "apply_operations", attempt=attempt)
            seq = store.journal({**attempt, "ok": True, **info})
        progress.checking()
        report = validate_file(p, requirements=requirements, bounds=bounds, layout=layout)
        out = {"drawing": self._rel(p), "changes": _changes(res), "results": res["results"],
               "validation": _brief(report), "journal_seq": seq, **info}
        if created:
            out["created_drawing"] = created
        return out

    @staticmethod
    def _check_create(create: Any, where: str = "create") -> None:
        if not isinstance(create, dict):
            raise input_error("INVALID_OBJECT", f"{where}: expected an object {{units, template, ...}}")
        bad = sorted(set(create) - CREATE_FIELDS)
        if bad:
            raise input_error("UNKNOWN_PARAM", f"{where}: unknown field(s) {bad}", hint=f"Fields: {sorted(CREATE_FIELDS)}")

    def _create_if_missing(self, path: str, create: dict, dry_run: bool) -> dict | None:
        """apply_operations(create=...): make the drawing unless it already exists. Returns what was created.
        The new drawing is committed on its own: if the operations then fail, it stays, empty."""
        self._check_create(create)
        p, _ = self._drawing(path, must_exist=False)
        if p.exists():
            return None
        if dry_run:
            raise input_error("DRY_RUN_NEEDS_DRAWING", f"{path} does not exist; dry_run cannot create it",
                              hint="Run without dry_run, or create the drawing first")
        r = TOOLS["create_drawing"](self, path, **create)
        return {"units": r["units"], "dxf_version": r["dxf_version"], "template": create.get("template", "mechanical")}

    @tool
    def apply_batch(self, jobs: list[dict], stop_on_error: bool = False) -> dict[str, Any]:
        """apply_operations on several drawings in one call (e.g. a family of parts from a table). Each job is
        {path, operations, create?, requirements?, bounds?, layout?, strict?, label?} and is its own transaction:
        a failing job's operations change nothing (a drawing its 'create' made stays, empty) and do not undo the
        other jobs. ``stop_on_error`` skips the jobs after the first failure."""
        allowed = {"path", "operations", "create", "requirements", "bounds", "layout", "strict", "label"}
        self.policy.check_write()
        if not isinstance(jobs, list) or not jobs:
            raise input_error("INVALID_LIST", "jobs: expected a non-empty list")
        if len(jobs) > MAX_BATCH_JOBS:
            raise policy_error("BUDGET_EXCEEDED", f"{len(jobs)} jobs (limit {MAX_BATCH_JOBS})", hint="Split the batch")
        resolved = []
        for i, j in enumerate(jobs):  # check every job's shape and path before touching any drawing
            if not isinstance(j, dict) or "path" not in j or "operations" not in j:
                raise input_error("INVALID_JOB", f"jobs[{i}]: needs 'path' and 'operations'")
            bad = sorted(set(j) - allowed)
            if bad:
                raise input_error("UNKNOWN_PARAM", f"jobs[{i}]: unknown field(s) {bad}", hint=f"Fields: {sorted(allowed)}")
            if j.get("create") is not None:
                self._check_create(j["create"], f"jobs[{i}].create")
            resolved.append(str(self._drawing(str(j["path"]), must_exist=False, part_ok=True)[0]).lower())
        dup = sorted({j["path"] for j, r in zip(jobs, resolved) if resolved.count(r) > 1})
        if dup:
            raise input_error("DUPLICATE_PATH", f"jobs name the same drawing more than once: {dup}",
                              hint="Put all operations for one drawing into one job")
        out = []
        for j in jobs:
            if stop_on_error and any(not x["ok"] for x in out):
                out.append({"path": j["path"], "ok": False, "skipped": True})
                continue
            r = self.apply_operations(j["path"], j["operations"], requirements=j.get("requirements"),
                                      strict=bool(j.get("strict", False)), label=j.get("label"),
                                      create=j.get("create"), bounds=j.get("bounds"), layout=j.get("layout"))
            if not r["ok"]:
                out.append({"path": j["path"], "ok": False, "error": r["error"]})
                continue
            item = {"path": j["path"], "ok": True, "passed": r["validation"]["passed"],
                    "changes": {k: len(v) for k, v in r["changes"].items()}, "validation": r["validation"],
                    "journal_seq": r["journal_seq"]}
            if r.get("created_drawing"):
                item["created"] = True
            if r.get("normalized"):
                item["normalized"] = r["normalized"]
            out.append(item)
        skipped = sum(1 for x in out if x.get("skipped"))
        return {"jobs": out, "succeeded": sum(1 for x in out if x["ok"]),
                "failed": sum(1 for x in out if not x["ok"]) - skipped, "skipped": skipped,
                "all_passed": all(x["ok"] and x["passed"] for x in out)}

    @tool
    def run_script(self, path: str, code: str, label: str | None = None, dry_run: bool = False,
                   requirements: list[dict] | None = None, strict: bool = False, language: str | None = None,
                   keep_features: bool = False) -> dict[str, Any]:
        """Run an ezdxf script on the drawing as one transaction (opt-in; see scripting.py). The script edits the
        document given as ``doc`` in place; it may set ``result`` to return a JSON value. Its output is re-read
        strictly, diffed, validated and committed with a checkpoint; the journal keeps the full script.

        3D part (.FCStd): a CadQuery (``language`` 'cadquery', default) or FreeCAD Part ('freecad') program that
        sets ``result`` to the solid; it becomes the part's base solid, which later part ops build on
        (``keep_features``: rebuild the Body's existing features on the new solid). See part.service.run_script."""
        from . import scripting
        if part.is_part(path):
            return part.run_script(self, path, code, language, keep_features, dry_run, requirements, strict, label)
        if language not in (None, "ezdxf"):
            raise input_error("BAD_LANGUAGE", f"language {language!r}: drawings (.dxf) take ezdxf scripts",
                              hint="CadQuery and FreeCAD scripts build 3D parts (.FCStd)")
        if keep_features:
            raise input_error("UNKNOWN_PARAM", "keep_features applies to 3D parts (.FCStd)")
        self.policy.check_scripts_allowed()
        if not dry_run:
            self.policy.check_write()
        scripting.check_script(code)
        p, store = self._drawing(path)
        with self._lock(store):
            before = store.load()
            job = store.dir / "scripts" / f"job-{int(time.time() * 1000)}"
            try:
                res = scripting.run(p, code, job, self.policy.script_timeout)
                if not res["ok"]:
                    raise AgentCADError("SCRIPT_FAILED", f"The script raised {res['error']}", category="input",
                                        details={k: res.get(k) for k in ("script_lines", "stdout", "traceback")},
                                        hint="Nothing was saved; fix the script and run it again")
                doc = read_dxf(job / "out.dxf", self.policy)
            except AgentCADError as exc:
                store.journal({"tool": "run_script", "ok": False, "label": label, "code": code,
                               "error": exc.to_dict(), "file_unchanged": True})
                raise
            finally:
                shutil.rmtree(job, ignore_errors=True)
            n = sum(len(sp) for sp in layout_spaces(doc, "*"))
            if n > self.policy.max_entities:
                raise policy_error("BUDGET_EXCEEDED", f"Drawing would contain {n} entities "
                                                      f"(limit {self.policy.max_entities})")
            diff = diff_docs(before, doc)
            changes = {"added": [e["id"] for e in diff["added"]], "modified": [m["id"] for m in diff["modified"]],
                       "deleted": [e["id"] for e in diff["deleted"]]}
            out = {"drawing": self._rel(p), "changes": changes, "diff_summary": diff["summary"],
                   "result": res.get("result"), "stdout": res.get("stdout"), "script_seconds": res.get("seconds")}
            if dry_run:
                return {**out, "dry_run": True, "diff": {k: diff[k] for k in ("added", "deleted", "modified")}}
            tmp_report = self._validate_doc(doc, requirements) if strict else None
            if tmp_report is not None and not tmp_report["passed"]:
                fail = self._save_failure(store, doc, "strict-validation")
                store.journal({"tool": "run_script", "ok": False, "label": label, "code": code,
                               "error": {"code": "VALIDATION_FAILED"}, "failure_snapshot": fail})
                raise AgentCADError("VALIDATION_FAILED", "Validation of the script's result failed; nothing was saved",
                                    category="validation",
                                    details={"validation": compact_report(tmp_report), "failure_snapshot": fail},
                                    hint="Inspect validation.issues; fix the script and retry")
            attempt = {"tool": "run_script", "label": label, "code": code,
                       "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "changes": changes}
            info = store.commit(doc, label=label or "run_script", attempt=attempt)
            seq = store.journal({**attempt, "ok": True, "stdout": res.get("stdout"), **info})
        report = validate_file(p, requirements=requirements)
        return {**out, "validation": _brief(report), "journal_seq": seq, **info}

    def _validate_doc(self, doc, requirements, bounds=None, layout=None):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "candidate.dxf"
            doc.saveas(fp)
            return validate_file(fp, requirements=requirements, bounds=bounds, layout=layout)

    @tool
    def validate_drawing(self, path: str, requirements: list[dict] | None = None, use_stored_spec: bool = True,
                         bounds: list | None = None, tolerance: float = 1e-6,
                         contour_layers: list[str] | None = None, layout: str | None = None,
                         detail: bool = False) -> dict[str, Any]:
        """Independent validation: re-reads the file from disk. If the drawing carries a part spec and no
        explicit requirements are given, requirements are re-derived from that spec (not from the plan).
        ``layout``: check a paper-space sheet instead of model space (the stored spec describes model space).
        ``detail``: the full report (see compact_report for the default)."""
        if part.is_part(path):
            return part.validate(self, path, requirements, detail)
        p, store = self._drawing(path)
        report = self._drawing_validation(p, requirements, use_stored_spec, bounds, tolerance,
                                          contour_layers, layout)
        return {"drawing": self._rel(p), "validation": report if detail else compact_report(report)}

    def _drawing_validation(self, p, requirements=None, use_stored_spec=True, bounds=None,
                            tolerance=1e-6, contour_layers=None, layout=None):
        """One stored-intent path for explicit validation and final delivery."""
        reqs = requirements
        source = "explicit" if requirements is not None else None
        if reqs is None and use_stored_spec and is_model(layout):
            try:
                doc = read_dxf(p, self.policy)
            except AgentCADError:
                doc = None  # unreadable: validate_file reports it
            if doc is not None:
                absent = object()
                stored = get_meta(doc, "part_spec", absent, strict=True)
                if stored is not absent:
                    # Invalid stored intent must fail closed, not silently become zero requirements.
                    reqs = specmod.compile_spec(stored)["requirements"]
                    source = "stored_part_spec"
                    contour_layers = contour_layers or ["OUTLINE"]
        report = validate_file(p, requirements=reqs, bounds=bounds, tolerance=tolerance, contour_layers=contour_layers,
                               layout=layout)
        report["file"] = self._rel(p)
        report["requirements_source"] = source
        return report

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
    def get_diff(self, path: str, against: str = "previous", detail: bool = False) -> dict[str, Any]:
        """Diff the drawing against 'previous' (latest checkpoint), a checkpoint id, or another .dxf path.
        Modified entities always list their changed fields (old/new); added and deleted entities are listed by
        id/type/layer/tag unless ``detail`` asks for their full geometry."""
        if part.is_part(path):
            return part.diff(self, path, against)
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
        diff = diff_docs(old, cur)
        if not detail:
            for k in ("added", "deleted"):
                diff[k] = [{f: e[f] for f in ("id", "type", "layer", "tag", "layout") if f in e} for e in diff[k]]
        return {"drawing": self._rel(p), "against": label, **diff}

    @tool
    def rollback(self, path: str, checkpoint: str | None = None) -> dict[str, Any]:
        """Restore a checkpoint (default: the latest one that differs from the file, so the last change is undone
        even when a checkpoint of the unchanged file was left behind, e.g. by a FILE_BUSY attempt). The
        pre-rollback state is checkpointed too."""
        self.policy.check_write()
        p, store = self._drawing(path, must_exist=False, part_ok=True)
        cps = store.list_checkpoints()
        if not cps:
            raise input_error("NO_CHECKPOINT", "Drawing has no checkpoints")
        cid = checkpoint
        if cid is None:
            cur = sha256_file(p) if p.is_file() else None
            cid = next((c["id"] for c in reversed(cps) if c.get("sha256") != cur), cps[-1]["id"])
        with self._lock(store):
            info = store.restore(cid, label=f"rollback to {cid}")
            seq = store.journal({"tool": "rollback", "ok": True, "checkpoint": cid, **info})
        return {"drawing": self._rel(p), "journal_seq": seq, **info}

    @tool
    def list_checkpoints(self, path: str) -> dict[str, Any]:
        p, store = self._drawing(path, must_exist=False, part_ok=True)
        return {"drawing": self._rel(p), "checkpoints": store.list_checkpoints()}

    @tool
    def history(self, path: str, limit: int = 50, detail: bool = False, seq: list[int] | None = None) -> dict[str, Any]:
        """Operation journal, oldest first. By default one line per record (what ran, what changed, checkpoint);
        ``seq`` returns those records in full (operations with their parameters, scripts, errors), ``detail`` all."""
        p, store = self._drawing(path, must_exist=False, part_ok=True)
        if seq:
            want = set(seq)
            recs = [r for r in store.read_journal() if r.get("seq") in want]
            return {"drawing": self._rel(p), "records": recs}
        recs = store.read_journal(limit)
        if detail:
            return {"drawing": self._rel(p), "records": recs}
        return {"drawing": self._rel(p), "records": [_journal_line(r) for r in recs],
                "detail_hint": "seq=[n, ...]: those records in full (operation parameters, script, error)"}

    @tool
    def recover(self, path: str) -> dict[str, Any]:
        """Crash recovery. A commit interrupted after its pending marker (e.g. FILE_BUSY with partial_changes) is
        settled first: recorded if its content is in the file, dropped if not. Otherwise, if the file is unreadable
        or an older marker left it inconsistent, restore the most recent checkpoint whose content is a valid DXF (or
        FreeCAD file, for a part)."""
        p, store = self._drawing(path, must_exist=False, part_ok=True)
        st = store.status()
        needed = (not st["exists"]) or (not st["readable"]) or bool(st["pending_transaction"])
        if not needed:
            return {"drawing": self._rel(p), "recovered": False, "status": st}
        self.policy.check_write()
        if st["exists"] and st["readable"] and st["pending_transaction"]:
            with self._lock(store):  # an interrupted commit in the file is recorded, an unstarted one dropped
                try:
                    settled = store.settle_pending(from_status=st)
                except PermissionError:  # head.json still held by another process: nothing was changed
                    raise busy_error(store.head_path, applied=False)
            if settled:
                done, seq = settled
                return {"drawing": self._rel(p), "recovered": True, "pending_commit": done["outcome"],
                        "label": done["pending"]["label"], "sha256": done["sha256"], "journal_seq": seq}
        from .store import sha256_file
        candidates = []
        if store.committed_path.is_file() and sha256_file(store.committed_path) == st["committed_sha256"]:
            candidates.append({"id": "committed"})  # exact last committed state
        candidates += list(reversed(store.list_checkpoints()))
        for cp in candidates:
            try:
                store.reader(store.committed_path if cp["id"] == "committed" else store.checkpoint_path(cp["id"]),
                             self.policy)
            except AgentCADError:
                continue
            with self._lock(store):
                if st["exists"]:
                    bad = store.dir / "failed" / f"{time.strftime('%Y%m%d-%H%M%S')}-corrupt{store.ext}"
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
                       dxf_version: str | None = None, overwrite: bool = False, layout: str | None = None,
                       paper: str | None = None, scale: float | None = None, orientation: str = "auto",
                       monochrome: bool = False, views: list | None = None, image_size: int | None = None,
                       fit: str | None = None, reference: str | None = None, table: str = "entities") -> dict[str, Any]:
        """Export to dxf (optionally another DXF version, incl. R12 via ezdxf.addons.r12export), svg, json,
        pdf, csv/xlsx, or dwg (optional AutoCAD backend; ``dxf_version`` then selects the DWG release, default 2018).
        CSV/XLSX tables: entities (text/attributes), pid_lines, or bom, reconstructed from the saved drawing.

        pdf (plot.py, no external software): ``layout`` 'Model', a paper layout, or '*' for every paper layout
        (default: every paper layout with content, else model space), one page each. Paper layouts print 1:1 on
        their page setup; model space at ``scale`` (paper mm per drawing unit) or the largest standard scale that
        fits ``paper`` (A0-A4 or 'auto').

        3D parts (.FCStd): step, iges, brep, stl, obj, or png (shaded preview: ``views``, ``image_size``,
        ``fit``; ``reference``: compare with a reference image of the same views; see part.service.export)."""
        if table not in {"entities", "pid_lines", "bom"} or table != "entities" and format.lower() not in {"csv", "xlsx"}:
            raise input_error("INVALID_TABLE", "pid_lines and bom tables require CSV or XLSX export")
        if part.is_part(path):
            return part.export(self, path, output, format, overwrite, views, image_size, fit, reference)
        if views or image_size or fit or reference:
            raise input_error("UNKNOWN_PARAM", "views, image_size, fit and reference apply to png previews of 3D "
                                               "parts")
        self.policy.check_write()
        p, store = self._drawing(path)
        fmt = format.lower()
        suffix = {"dxf": ".dxf", "svg": ".svg", "json": ".json", "dwg": ".dwg", "pdf": ".pdf",
                  "csv": ".csv", "xlsx": ".xlsx"}.get(fmt)
        if suffix is None:
            raise input_error("UNSUPPORTED_FORMAT", f"Unsupported export format {format!r}",
                              hint="dxf | svg | json | pdf | dwg | csv | xlsx")
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
        if fmt == "pdf":
            from . import plot
            if scale is not None and scale <= 0:
                raise input_error("INVALID_VALUE", "scale must be > 0", hint="paper mm per drawing unit, 0.5 = 1:2")
            if orientation not in ("auto", "landscape", "portrait"):
                raise input_error("INVALID_ENUM", "orientation must be auto | landscape | portrait")
            res = plot.plot_pdf(doc, out, _plot_layouts(doc, layout), paper=paper, orientation=orientation,
                                scale=scale, monochrome=monochrome, title=p.stem)
            warn = [i for i in validate_file(p)["issues"] if i["code"] == "PRINTED_TEXT_TOO_SMALL"]
            small = _min_model_text(doc) if any(pg["layout"] == "Model" for pg in res["pages"]) else None
            for pg in res["pages"]:
                if small and pg["layout"] == "Model" and small * pg["scale"] < MIN_PRINTED_TEXT - 1e-9:
                    warn.append({"code": "PRINTED_TEXT_TOO_SMALL", "severity": "warning", "layout": "Model",
                                 "message": f"At {pg['scale_text']} the smallest model text prints "
                                            f"{small * pg['scale']:.2f} mm high (minimum {MIN_PRINTED_TEXT} mm)",
                                 "hint": "Plot at a larger scale or paper, or enlarge the text"})
            store.journal({"tool": "export_drawing", "ok": True, "output": self._rel(out), "format": "pdf"})
            return {"drawing": self._rel(p), "output": self._rel(out), "format": "pdf", **res,
                    **({"warnings": warn[:20]} if warn else {})}
        finalize(doc)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt in {"csv", "xlsx"}:
            from .tabular import drawing_rows, write_table
            rows = drawing_rows(doc, table)
            write_table(out, fmt, rows)
            extra = {"rows": len(rows) - 1, "formula_policy": "CSV apostrophe; XLSX explicit string cells; numbers preserved"}
        elif fmt == "dxf":
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
                                    category="dependency",
                                    hint="pip install -e '.[preview]' (Pillow) in the AgentCAD checkout")
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
        """Open the DXF or DWG in AutoCAD (headless, optional backend) and run AUDIT without fixing: a second,
        independent opinion on file validity from the reference implementation. A DWG is first converted to DXF
        by AutoCAD itself (agents asked to audit the DWG they had just exported)."""
        import tempfile
        from .backends import autocad
        p = self.policy.resolve(path, must_exist=True, suffixes=(".dxf", ".dwg"))
        jobs = self.policy.state_dir() / "acad"
        if p.suffix.lower() == ".dwg":
            with tempfile.TemporaryDirectory() as td:
                conv = Path(td) / "converted.dxf"
                autocad.dwg_to_dxf(p, conv, jobs, "2018")
                res = autocad.audit_dxf(conv, jobs)
        else:
            res = autocad.audit_dxf(p, jobs)
        res["passed"] = not res["import_rejected"] and res["audit_errors"] == 0
        return {"drawing": self._rel(p), "backend": "autocad", **res}

    @tool
    def autocad_live(self, action: str = "status", path: str | None = None, start: bool = False,
                     discard: bool = False, window: list | None = None, ids: list[str] | None = None,
                     command: str | None = None, label: str | None = None, force: bool = False) -> dict[str, Any]:
        """Work alongside the user's running AutoCAD (backends/acad_live.py): status | open | reload | pull |
        zoom | command. ``pull`` commits the edits made in AutoCAD like any other change (checkpoint, journal,
        diff, validation); the drawing is then re-opened in AutoCAD from the committed file.

        New documents are opened read-only so the runtime can replace the DXF on Windows; edits in AutoCAD
        can still be pulled. An already-open document is left as-is; reload a saved write-open drawing to switch.

        The version AutoCAD opened is recorded (open / reload). If the runtime committed changes since, AutoCAD's
        copy is stale and ``pull`` would revert them: it refuses unless ``force`` (the overwritten version stays
        in a checkpoint)."""
        from .backends import acad_live
        if action not in LIVE_ACTIONS:
            raise input_error("INVALID_ENUM", f"Unknown action {action!r}", hint=f"One of {list(LIVE_ACTIONS)}")
        with acad_live.com_thread():
            app = self.live_connect(start and action == "open")
            if app is None:
                if action == "status":
                    return {"running": False, "hint": "action='open' with start=true launches AutoCAD"}
                raise AgentCADError("AUTOCAD_NOT_RUNNING", "AutoCAD is not running", category="dependency",
                                    hint="action='open' with start=true launches it", retryable=True)
            s = acad_live.Session(app)
            if action == "status":
                st = s.status()
                for d in st["documents"]:
                    try:
                        d["drawing"] = self._rel(Path(d["path"]).resolve())
                    except ValueError:
                        pass  # outside the workspace
                return {"running": True, **st}
            if not path:
                raise input_error("MISSING_PATH", f"action={action!r} needs the drawing path")
            p, store = self._drawing(path)
            rel = self._rel(p)
            if action == "open":
                with self._lock(store):
                    was_open = s.find(p) is not None
                    doc = s.open(p)
                    if not was_open:
                        _live_base(store, p)
                    # already open (by the user, or earlier): AutoCAD shows what it read then, which this
                    # runtime cannot know, so an unrecorded base stays unknown and pull asks for reload or force
                    out = {"drawing": rel, "open_in_autocad": True, **s.describe(doc)}
                hints = []
                if was_open and _live_base(store) is None:
                    hints.append("AutoCAD already had this drawing open, possibly an older version: reload it "
                                 "before pulling, or pull with force=true to take AutoCAD's version")
                if out["read_only"]:
                    hints.append("AutoCAD has the drawing open read-only so AgentCAD can update it; edits made in "
                                 "AutoCAD can be committed with action='pull'")
                else:
                    hints.append("AutoCAD has the drawing open for writing and may prevent AgentCAD from replacing "
                                 "it on Windows. Pull unsaved edits, or reload a saved drawing to reopen read-only")
                out["hint"] = "; ".join(hints)
                return out
            if action == "reload":
                with self._lock(store):  # the recorded base is the file AutoCAD re-read: no commit in between
                    res = s.reload(p, discard)
                    if res.get("reloaded"):
                        _live_base(store, p)
                return {"drawing": rel, **res}
            if action == "zoom":
                win = window
                if win is None and ids:
                    ext = bbox.extents(select(store.load(), ids), fast=True)
                    if ext.has_data:
                        pad = max(ext.size.x, ext.size.y, 1.0) * 0.1
                        win = [[ext.extmin.x - pad, ext.extmin.y - pad], [ext.extmax.x + pad, ext.extmax.y + pad]]
                s.zoom(p, win)
                return {"drawing": rel, "window": win or "extents"}
            if action == "command":
                self.policy.check_live_commands_allowed()
                if not command or not command.strip():
                    raise input_error("INVALID_STRING", "command must be a non-empty command line")
                idle = s.command(p, command)
                store.journal({"tool": "autocad_live", "ok": True, "action": "command", "command": command})
                return {"drawing": rel, "sent": command, "finished": idle,
                        "hint": "The command changed the drawing in AutoCAD only; action='pull' commits its edits"
                                + ("" if idle else ". AutoCAD is still busy (the command waits for input?)")}
            # pull
            self.policy.check_write()
            with self._lock(store):
                if s.find(p) is None:
                    raise AgentCADError("NOT_OPEN_IN_AUTOCAD", f"{p.name} is not open in AutoCAD", category="input",
                                        hint="autocad_live action='open' first")
                base = _live_base(store)
                current = sha256_file(p)
                if base != current and not force:
                    raise AgentCADError(
                        "LIVE_CONFLICT", "AutoCAD shows an older version of the drawing: pulling it would revert "
                        "changes committed since AutoCAD opened it" if base else "This runtime did not open the "
                        "drawing in AutoCAD, so it cannot tell which version AutoCAD shows", category="policy",
                        hint="If AutoCAD has no edits to keep: reload. To keep AutoCAD's version anyway: pull with "
                             "force=true (the newer version stays in a checkpoint, see get_diff / rollback)")
                tmp = self.policy.state_dir() / "live" / f"pull-{int(time.time() * 1000)}.dxf"
                gui_doc, view, dirty = s.save_copy(p, tmp)
                # from here the temporary DXF is the only saved copy of the user's edits: keep it on any failure
                try:
                    new = read_dxf(tmp, self.policy)
                    diff = diff_docs(store.load(), new)
                    changes = {k: [e["id"] for e in diff[k]] for k in ("added", "modified", "deleted")}
                    # unsaved edits count even when no entity changed (a new layer, style, block, setting)
                    changed = dirty or any(changes.values()) or any(diff["layers"].values())
                    info: dict[str, Any] = {}
                    seq = None
                    if changed:
                        info = store.commit(new, label=label or "autocad_live pull")
                        seq = store.journal({"tool": "autocad_live", "action": "pull", "ok": True, "label": label,
                                             "forced": base != current, "changes": changes, **info})
                except Exception as exc:  # noqa: BLE001 - whatever failed, say where the user's edits are
                    if not isinstance(exc, AgentCADError):
                        exc = AgentCADError("INTERNAL_ERROR", f"pull failed: {type(exc).__name__}: {exc}",
                                            category="internal",
                                            details={"traceback": traceback.format_exc(limit=8)})
                    exc.details = {**(exc.details or {}), "autocad_copy": self._rel(tmp)}
                    exc.hint = (exc.hint or "") + f" AutoCAD's edits are saved in {self._rel(tmp)}, which is the " \
                                                  "document now open in AutoCAD"
                    raise exc
                out = {"drawing": rel, "changed": changed, "changes": changes, "diff_summary": diff["summary"],
                       "layers": diff["layers"], **info}
                if base != current:
                    out["forced"] = True
                try:
                    acad_live._retry(lambda: gui_doc.Close(False))
                    s.open(p)
                    s.set_view(view)
                    tmp.unlink(missing_ok=True)
                    _live_base(store, p)
                except Exception as exc:  # noqa: BLE001 - the pull is committed; only re-opening failed
                    e = exc.to_dict() if isinstance(exc, AgentCADError) else {
                        "code": "AUTOCAD_COM_ERROR", "message": f"{type(exc).__name__}: {exc}"}
                    out["live"] = {"reopened": False, "error": {k: e[k] for k in ("code", "message") if k in e},
                                   "autocad_copy": self._rel(tmp)}
        if changed:
            out["validation"] = _brief(validate_file(p))
            out["journal_seq"] = seq
        return out

    @tool
    def standard_library(self, item: str | None = None, size: str | None = None,
                         drawing: str | None = None) -> dict[str, Any]:
        """Industry libraries (stdlib.py). No arguments: a compact index of P&ID symbols, GD&T characteristics,
        standard parts and holes with their sizes. ``item`` (with optional ``size``): that item's dimensions.
        ``item="iso_fit", size="25 H7/g6"``: sourced hole/shaft limits in mm (H7, h6, g6; 10 < size <= 500).
        ``drawing``: the parts list of a drawing (standard parts by part/standard/size, P&ID symbols with tags)."""
        from . import stdlib
        from .ops import REGISTRY
        if drawing:
            p, store = self._drawing(drawing)
            return {"drawing": self._rel(p), **bill_of_materials(store.load())}
        if item is None:
            return {**stdlib.index(), "ops": sorted(k for k, d in REGISTRY.items() if d.category == "library"),
                    "hint": "item=<name> (and size=...) gives dimensions; drawing=<path> gives its parts list"}
        try:
            return stdlib.table(item, size)
        except KeyError:
            known = sorted([*stdlib.PARTS, *stdlib.HOLE_KINDS, *stdlib.PID, *stdlib.GDT])
            if item in known:
                raise input_error("INVALID_SIZE", f"{item} has no size {size!r}", hint="See standard_library()")
            raise input_error("UNKNOWN_ITEM", f"No library item {item!r}", hint=f"Items: {known}")

    @tool
    def understand_drawing(self, path: str) -> dict[str, Any]:
        """Describe foreign drawing units, distant clusters, outlier handles and process services with evidence."""
        from .engineering.plant import describe
        p, store = self._drawing(path)
        return {"drawing":self._rel(p), **describe(store.load())}

    @tool
    def plant_takeoff(self, pid: str, layout: str, services: list[str] | None = None,
                      allowance: float = .2) -> dict[str, Any]:
        """Read pipe networks, sizes and stated electrical loads/circuits; estimate layout routing with an RMST.

        Supports millimetre plant drawings, orthogonal straight polylines and arc bends. Returns uncertainty,
        missing tags and chosen plan copy; cable allowance is a fraction, not a percent.
        """
        from .engineering.plant import takeoff
        _, ps = self._drawing(pid)
        _, ls = self._drawing(layout)
        return takeoff(ps.load(),ls.load(),services,allowance)

    @tool
    def read_engineering(self, path: str, kind: str) -> dict[str, Any]:
        """Reconstruct saved engineering records and geometry. kind: pid, architecture or mechanical."""
        p, store = self._drawing(path)
        if kind == "pid":
            from .engineering.pid import read
        elif kind == "architecture":
            from .engineering.architecture import read
        elif kind == "mechanical":
            from .engineering.mechanical import read
        else:
            raise input_error("UNKNOWN_DOMAIN", f"Unknown engineering kind {kind!r}")
        result = read(store.load())
        if kind in {"architecture", "mechanical"}:
            from .quality import score
            validation = validate_file(p)
            result.update(validation=validation, quality_score=max(0,score(validation)-15*len(result["critique"])))
        return {"drawing":self._rel(p), **result}

    @tool
    def preflight(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Validate a design specification before drawing; hash the exact accepted intent."""
        raw = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            compiled = specmod.compile_spec(spec)
        except AgentCADError as exc:
            return {"ready": False, "issues": [exc.to_dict()], "spec_hash": None}
        return {"ready": True, "spec_hash": "sha256:" + hashlib.sha256(raw.encode()).hexdigest(),
                "operation_count": len(compiled["operations"]), "requirements": compiled["requirements"]}

    @tool
    def measure_entities(self, path: str, target: Any) -> dict[str, Any]:
        """Exact DXF entity measurements by handle/selector; or final 3D solid measurements in mm.

        FCStd target={kind:"planar_levels", axis:"z"} lists plane positions, normals and gaps.
        target={kind:"face_distance", from:"Face1", to:"Face2"} measures parallel plane spacing.
        from/to also accept face selectors; multiple faces must be coplanar. Default is the final
        Body; optional feature names an intermediate feature for diagnosis. Inspect actual faces
        with inspect_entities(filter={kind:"faces"}); never infer a measured gap from parameters.
        """
        if part.is_part(path):
            return part.measure(self, path, target)
        from .measure import measure_entity
        p, store = self._drawing(path)
        doc = store.load()
        return {"drawing": self._rel(p), "units": _units_of(doc),
                "measurements": [measure_entity(e) for e in select(doc, target)]}

    @tool
    def verify_dimensions(self, path: str, requirements: list[dict]) -> dict[str, Any]:
        """Verify physical geometry bound to DIMENSION handles; flag misleading text and DIMLFAC separately.

        Each requirement: {id, handle, value, tolerance?}. This explicitly compares physical drawing units;
        normal validate_drawing dimension requirements retain their displayed-value semantics.
        """
        from .verification import verify_dimensions
        p, store = self._drawing(path)
        return {"drawing": self._rel(p), **verify_dimensions(store.load(), requirements)}

    @tool
    def refine_drawing(self, path: str, max_iterations: int = 3) -> dict[str, Any]:
        """Score independent file validation and remove exact duplicates until no supported repair remains."""
        from .quality import score
        if not 1 <= max_iterations <= 10:
            raise input_error("BAD_PARAMETER", "max_iterations must be between 1 and 10")
        p, _ = self._drawing(path)
        report = validate_file(p)
        initial = score(report)
        iterations = []
        for _ in range(max_iterations):
            if not any(i["code"] == "DUPLICATE_ENTITY" for i in report["issues"]):
                break
            result = self.apply_operations(path, [{"op": "remove_duplicates"}])
            if not result["ok"]:
                return {"initial_score": initial, "final_score": score(report), "iterations": iterations,
                        "repair_error": result["error"], "validation": report}
            report = validate_file(p)
            iterations.append({"changes": result["changes"], "score": score(report)})
            if not result["changes"].get("deleted"):
                break
        return {"initial_score": initial, "final_score": score(report), "iterations": iterations,
                "validation": report}

    @tool
    def deliver_drawing(self, path: str, output_dir: str, formats: list[str] | None = None,
                        min_score: float = 90, strict: bool = True) -> dict[str, Any]:
        """Export, reread and hash delivery artifacts; write a manifest tied to a validated source revision."""
        from .quality import deliver
        return deliver(self, path, output_dir, formats or ["dxf"], min_score, strict)

    @tool
    def search_tools(self, query: str, limit: int = 3) -> dict[str, Any]:
        """Rank tool and operation descriptions, names and AutoCAD command aliases."""
        from .discovery import search
        return {"results": search(query, limit, TOOLS)}

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


def _plot_layouts(doc, layout: str | None) -> list[str]:
    paper = [n for n in doc.layouts.names_in_taborder() if not is_model(n)]
    if layout is None:
        used = [n for n in paper if any(e.dxftype() != "VIEWPORT" or e.dxf.get("id", 1) != 1
                                        for e in doc.layouts.get(n))]
        return used or ["Model"]
    if layout == "*":
        return paper or ["Model"]
    if is_model(layout):
        return ["Model"]
    if layout not in doc.layouts:
        raise input_error("LAYOUT_NOT_FOUND", f"No layout named {layout!r}", hint=f"Layouts: {['Model', *paper]}")
    return [layout]


def _min_model_text(doc) -> float | None:
    from .validate.checks import _model_text_heights
    hs = [h for _, _, h, _ in _model_text_heights(doc) if h > 0]
    return min(hs) if hs else None


def bill_of_materials(doc) -> dict[str, Any]:
    """Standard parts (blocks with PART / STANDARD / SIZE attributes) and P&ID symbols in every layout."""
    parts: dict[tuple, int] = {}
    symbols, instruments = [], []
    for sp in layout_spaces(doc, "*"):
        for e in sp.query("INSERT"):
            name = e.dxf.name
            vals = {a.dxf.tag: a.dxf.text for a in e.attribs}
            if "PART" in vals:
                if not vals["PART"]:
                    continue  # another view of a part counted elsewhere
                key = (vals["PART"], vals.get("STANDARD", ""), vals.get("SIZE", ""))
                parts[key] = parts.get(key, 0) + 1
            elif name.startswith("PID_") and name != "PID_FLOW_ARROW":
                sym = name[4:].lower()
                if "FUNC" in vals:
                    instruments.append({"symbol": sym, "tag": "-".join(v for v in (vals["FUNC"], vals.get("LOOP"))
                                                                        if v), "id": e.dxf.handle})
                else:
                    symbols.append({"symbol": sym, "tag": vals.get("TAG", ""), "id": e.dxf.handle})
    return {"parts": [{"part": k[0], "standard": k[1], "size": k[2], "quantity": n}
                      for k, n in sorted(parts.items())],
            "pid_symbols": sorted(symbols, key=lambda r: (r["symbol"], r["tag"])),
            "instruments": sorted(instruments, key=lambda r: r["tag"])}


def _changes(res: dict[str, Any]) -> dict[str, Any]:
    return {"added": res["added"], "modified": res["modified"], "deleted": res["deleted"]}


def _journal_line(r: dict[str, Any]) -> dict[str, Any]:
    """A journal record without its payload: what ran, the outcome, change counts and the checkpoint."""
    line = {k: r[k] for k in ("seq", "ts", "tool", "ok", "label", "checkpoint_before") if r.get(k) is not None}
    ops = r.get("operations") or r.get("plan")
    if ops:
        counts: dict[str, int] = {}
        for o in ops:
            name = o.get("op", "?") if isinstance(o, dict) else "?"
            counts[name] = counts.get(name, 0) + 1
        line["ops"] = [f"{n} x{c}" if c > 1 else n for n, c in counts.items()]
    for k in ("changes_requested", "checkpoint"):
        if k in r:
            line[k] = r[k]
    ch = r.get("changes")
    if isinstance(ch, dict):
        line["changes"] = {k: len(v) for k, v in ch.items() if isinstance(v, list)}
    err = r.get("error")
    if isinstance(err, dict):
        line["error"] = {k: err[k] for k in ("code", "message", "op_index", "op") if k in err}
    if r.get("tool") == "run_script":
        line["script_lines"] = len(str(r.get("code", "")).splitlines())
    return line


MAX_ISSUES = 50
MAX_BATCH_JOBS = 200
CREATE_FIELDS = {"units", "template", "dxf_version", "annotation_scale"}


def _requirements(reqs: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """Failed requirements in full, passed ones by id only. A passed requirement that carries warnings (fields the
    validator ignored) stays listed, without expected/actual."""
    out["requirements"] = [r if r["status"] != "pass" else {k: r[k] for k in ("id", "type", "status", "warnings")}
                           for r in reqs if r["status"] != "pass" or r.get("warnings")]
    out["requirements_passed"] = [r["id"] for r in reqs if r["status"] == "pass"]


def _issues(report: dict[str, Any], out: dict[str, Any]) -> None:
    out["issues"] = report["issues"][:MAX_ISSUES]
    if len(report["issues"]) > MAX_ISSUES:
        out["issues_omitted"] = len(report["issues"]) - MAX_ISSUES


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    """The validation attached to edit results: validate_drawing's compact report (recognized counts and coverage
    included, so the agent need not call validate_drawing again), without the file name and the detail hint."""
    out = compact_report(report)
    for k in ("file", "readable", "detail_hint", "requirements_source"):
        out.pop(k, None)
    return out


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """validate_drawing without detail: verdict, issues, failed requirements and counts of what was recognized.
    The full report repeats expected/actual for every passed requirement and lists every circle and dimension,
    which made validate_drawing a third of all tool output in the Claude Code trials."""
    out = {k: report[k] for k in ("file", "readable", "passed", "summary") if k in report}
    _issues(report, out)
    _requirements(report["requirements"], out)
    if "coverage" in report:
        out["coverage"] = {"checked_layout": report["coverage"]["checked_layout"],
                           "unchecked_layouts": [u["layout"] for u in report["coverage"]["unchecked_layouts"]]}
    rec = report.get("recognized")
    if rec:
        diam: dict[str, int] = {}
        for c in rec["circles"]:
            k = f"{c['diameter']:g}"
            diam[k] = diam.get(k, 0) + 1
        kinds: dict[str, int] = {}
        for d in rec["dimensions"]:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        out["recognized"] = {"outline": rec["outline"] and {"size": rec["outline"]["size"], "bbox": rec["outline"]["bbox"]},
                             "circles": {"count": len(rec["circles"]), "by_diameter": diam},
                             "dimensions": {"count": len(rec["dimensions"]), "by_kind": kinds},
                             "closed_contours": rec["closed_contours"], "entity_count": rec["entity_count"]}
    if "requirements_source" in report:
        out["requirements_source"] = report["requirements_source"]
    out["detail_hint"] = "detail=true: expected/actual of passed requirements, each circle and dimension"
    return out


def diff_docs(old, new) -> dict[str, Any]:
    a = {e.dxf.handle: entity_to_dict(e) for sp in layout_spaces(old, "*") for e in sp}
    b = {e.dxf.handle: entity_to_dict(e) for sp in layout_spaces(new, "*") for e in sp}
    added = [b[h] for h in b if h not in a]
    deleted = [a[h] for h in a if h not in b]
    modified = []
    for h in a.keys() & b.keys():
        if a[h] != b[h]:
            fields = {k: {"old": a[h].get(k), "new": b[h].get(k)} for k in set(a[h]) | set(b[h]) if a[h].get(k) != b[h].get(k)}
            m = {"id": h, "type": b[h]["type"], "tag": b[h].get("tag"), "changes": fields}
            if b[h].get("layout"):
                m["layout"] = b[h]["layout"]
            modified.append(m)
    modified.sort(key=lambda m: m["id"])
    unchanged = len([h for h in a.keys() & b.keys() if a[h] == b[h]])
    layers_old = {l.dxf.name for l in old.layers}
    layers_new = {l.dxf.name for l in new.layers}
    return {"summary": {"added": len(added), "deleted": len(deleted), "modified": len(modified), "unchanged": unchanged},
            "added": added, "deleted": deleted, "modified": modified,
            "layers": {"added": sorted(layers_new - layers_old), "deleted": sorted(layers_old - layers_new)}}
