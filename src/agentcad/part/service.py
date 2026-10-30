"""3D parts (``.FCStd``) behind the same tools as drawings. ``service.Runtime`` hands a call here when the path is a
part; the store, journal, checkpoints, lock and result envelope are the ones drawings use.

A batch runs in a FreeCAD process on a copy of the part and is saved to a candidate file. The runner re-opens that
file as a fresh document and validates it; only then is it committed (checkpoint, atomic replace, journal). A failed
batch never touches the part.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .. import progress
from ..backends import freecad
from ..errors import AgentCADError, file_error, input_error
from ..policy import Policy
from ..store import DrawingStore
from ..units import normalize_unit
from .ops import normalize, op_params, prevalidate

if TYPE_CHECKING:
    from ..service import Runtime

SUFFIX = ".fcstd"
EXPORTS = {"step": (".step", ".stp"), "iges": (".iges", ".igs"), "brep": (".brep", ".brp"), "stl": (".stl",),
           "obj": (".obj",), "png": (".png",)}


def is_part(path: Any) -> bool:
    return isinstance(path, str) and path.lower().endswith(SUFFIX)


def read_fcstd(path: Path, policy: Policy) -> Path:
    """Cheap structural read (a FreeCAD file is a zip with Document.xml); FreeCAD itself is not started."""
    if not path.is_file():
        raise file_error("FILE_NOT_FOUND", f"{path} does not exist")
    size = path.stat().st_size
    if size > policy.max_file_bytes:
        raise file_error("FILE_TOO_LARGE", f"{path} is {size} bytes (limit {policy.max_file_bytes})")
    try:
        with zipfile.ZipFile(path) as z:
            if "Document.xml" not in z.namelist():
                raise file_error("FCSTD_PARSE_ERROR", f"{path.name} has no Document.xml",
                                 hint="The file is corrupt or not FreeCAD; use recover or rollback")
            if z.testzip() is not None:
                raise file_error("FCSTD_PARSE_ERROR", f"{path.name} has a corrupt member",
                                 hint="Use recover or rollback to a checkpoint")
    except zipfile.BadZipFile as exc:
        raise file_error("FCSTD_PARSE_ERROR", f"{path.name} is not a FreeCAD file: {exc}",
                         hint="The file is corrupt or not FreeCAD; use recover or rollback")
    return path


def store_for(rt: "Runtime", path: str, must_exist: bool = True) -> tuple[Path, DrawingStore]:
    p = rt.policy.resolve(path, must_exist=must_exist, suffixes=(SUFFIX,))
    return p, DrawingStore(rt.policy, p, reader=read_fcstd)


def _jobs(rt: "Runtime") -> Path:
    d = rt.policy.state_dir() / "freecad"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(rt: "Runtime", job: dict[str, Any], inputs: dict[str, Path] | None = None,
         outputs: dict[str, Path] | None = None, on_progress=None, timeout: float | None = None,
         workdir: Path | None = None) -> dict[str, Any]:
    res = freecad.run(job, inputs, outputs, on_progress, timeout, workdir)
    if not res.get("ok"):
        e = res.get("error") or {}
        cat = e.get("category", "internal")
        raise AgentCADError(e.get("code", "FREECAD_ERROR"), e.get("message", "FreeCAD job failed"),
                            category=cat if cat in ("input", "geometry", "file", "internal", "validation") else "internal",
                            entities=e.get("entities"), op_index=e.get("op_index"), op=e.get("op"),
                            hint=e.get("hint"), details=e.get("details"))
    return res


def _progress_relay(operations: list[dict]):
    """Forward the FreeCAD runner's per-operation lines to the live viewer (progress.py), or None if nobody
    follows this call."""
    if progress.current() is None:
        return None

    def relay(ev: dict[str, Any]) -> None:
        if ev.get("phase") == "checking":
            progress.checking()
        elif isinstance(ev.get("step"), int) and 0 <= ev["step"] < len(operations):
            progress.step(ev["step"], len(operations), operations[ev["step"]])
    return relay


def _candidate(rt: "Runtime") -> Path:
    return _jobs(rt) / f"candidate-{uuid.uuid4().hex[:12]}.FCStd"


def _snapshot(rt: "Runtime", store: DrawingStore, cand: Path) -> str | None:
    """Keep a rejected candidate for diagnosis; never let that mask the real error."""
    try:
        d = store.dir / "failed"
        d.mkdir(parents=True, exist_ok=True)
        snap = d / f"{uuid.uuid4().hex[:8]}-strict-validation.FCStd"
        shutil.copy2(cand, snap)
        return rt._rel(snap)
    except OSError:
        return None


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    out = {"passed": report["passed"], "issues": report["issues"][:20]}
    if report.get("requirements"):
        failed = [r for r in report["requirements"] if not r.get("passed")]
        out["requirements"] = {"total": len(report["requirements"]), "failed": failed}
    if report.get("warnings"):
        out["warnings"] = report["warnings"]
    if report.get("shape"):
        s = report["shape"]
        out["shape"] = {k: s[k] for k in ("valid", "solids", "volume", "size", "bbox", "holes") if k in s}
    return out


def create(rt: "Runtime", path: str, units: str, overwrite: bool) -> dict[str, Any]:
    rt.policy.check_write()
    u = normalize_unit(units)
    p, store = store_for(rt, path, must_exist=False)
    if p.exists() and not overwrite:
        raise input_error("FILE_EXISTS", f"{path} already exists", hint="Pass overwrite=true to replace it (a checkpoint is kept)")
    cand = _candidate(rt)
    try:
        _run(rt, {"action": "apply", "input": None, "ops": [], "units": u, "validate": False},
             outputs={"output": cand})
        with rt._lock(store):
            info = store.commit_bytes(cand.read_bytes(), label="create_drawing")
            seq = store.journal({"tool": "create_drawing", "kind": "part", "args": {"units": u}, "ok": True, **info})
    finally:
        cand.unlink(missing_ok=True)
    return {"drawing": rt._rel(p), "kind": "part", "units": u, "journal_seq": seq, **info,
            "next": "apply_operations with add_sketch + pad (list_operations(category='part') for all 3D ops)"}


def apply(rt: "Runtime", path: str, operations: list[dict], dry_run: bool, requirements: list[dict] | None,
          strict: bool, label: str | None, create: dict | None = None) -> dict[str, Any]:
    """``create`` ({units}): a missing part is made in the same FreeCAD job as the operations and only written if
    they succeed, so a failed batch leaves no empty part behind (and dry_run works on a part that does not exist)."""
    if not dry_run:
        rt.policy.check_write()
    p, store = store_for(rt, path, must_exist=create is None)
    new = not p.exists()
    units = None
    if new:
        unknown = set(create) - {"units"}
        if unknown:
            raise input_error("UNKNOWN_PARAM", f"create: unknown field(s) {sorted(unknown)} for a 3D part",
                              hint="A part takes create={units}")
        units = normalize_unit(create.get("units", "mm"))
    operations, normalized = normalize(operations)
    prevalidate(operations, rt.policy)
    cand = _candidate(rt)
    try:
        with rt._lock(store):
            if not new:
                store.load()
            job = {"action": "apply", "ops": operations, "requirements": requirements, "op_params": op_params()}
            if new:
                job.update(input=None, units=units)
            try:
                res = _run(rt, job, inputs=None if new else {"input": p}, outputs={"output": cand},
                           on_progress=_progress_relay(operations))
            except AgentCADError as exc:
                store.journal({"tool": "apply_operations", "kind": "part", "ok": False, "label": label,
                               "operations": operations, "error": exc.to_dict(), "file_unchanged": True})
                raise
            report = res["report"]
            if dry_run:
                return {"drawing": rt._rel(p), "dry_run": True, "would_change": res["changes"],
                        "results": res["results"], "validation": _brief(report),
                        **({"normalized": normalized} if normalized else {})}
            if strict and not report["passed"]:
                snap = _snapshot(rt, store, cand)
                store.journal({"tool": "apply_operations", "kind": "part", "ok": False, "label": label,
                               "operations": operations, "error": {"code": "VALIDATION_FAILED"},
                               "failure_snapshot": snap})
                raise AgentCADError("VALIDATION_FAILED", "Post-operation validation failed; nothing was saved",
                                    category="validation", hint="Inspect validation.issues; fix the operations and retry",
                                    details={"validation": _brief(report), "failure_snapshot": snap})
            attempt = {"tool": "apply_operations", "kind": "part", "label": label, "operations": operations,
                       "changes": res["changes"], **({"created": {"units": units}} if new else {})}
            info = store.commit_bytes(cand.read_bytes(), label=label or "apply_operations", attempt=attempt)
            seq = store.journal({**attempt, "ok": True, **info})
    finally:
        cand.unlink(missing_ok=True)
    return {"drawing": rt._rel(p), "changes": res["changes"], "results": res["results"],
            "validation": _brief(report), "journal_seq": seq, **({"created": {"units": units}} if new else {}),
            **({"normalized": normalized} if normalized else {}), **info}


SCRIPT_LANGUAGES = ("cadquery", "freecad")
CQ_HINT = "pip install \"agentcad-runtime[cadquery]\", or language='freecad' for a FreeCAD Part script"


def _script_error(res: dict[str, Any]) -> AgentCADError:
    code = res.get("code") or "SCRIPT_FAILED"
    if code == "DEPENDENCY_MISSING":
        return AgentCADError(code, f"CadQuery could not be loaded: {res.get('error')}", category="dependency",
                             hint=CQ_HINT)
    msg = f"The script raised {res.get('error')}" if code == "SCRIPT_FAILED" else res.get("error", code)
    details = {k: res[k] for k in ("script_lines", "stdout") if res.get(k)}
    if res.get("traceback"):
        details["traceback"] = res["traceback"][-1500:]
    return AgentCADError(code, msg, category="input", details=details,
                         hint=res.get("hint") or "Nothing was saved; fix the script and run it again")


def _freecad_script(rt: "Runtime", code: str, job_dir: Path, brep: Path, timeout: float) -> dict[str, Any]:
    """Run a FreeCAD Part script in a FreeCAD process of its own (no document open), working in ``job_dir``;
    its solid is written to ``brep``."""
    from .. import scripting
    t0 = time.perf_counter()
    try:
        res = _run(rt, {"action": "script_solid", "code": code,
                        "allowed_imports": sorted(scripting.LANGUAGES["freecad"]["imports"])},
                   outputs={"output": brep}, timeout=timeout, workdir=job_dir / "freecad")
    except AgentCADError as exc:
        if exc.code == "FREECAD_TIMEOUT":
            raise AgentCADError("SCRIPT_TIMEOUT", f"The script ran longer than {timeout:g} s (FreeCAD's start "
                                "included) and was stopped", category="input",
                                hint="Simplify the script, or raise AGENTCAD_SCRIPT_TIMEOUT")
        raise
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res


def run_script(rt: "Runtime", path: str, code: str, language: str | None, keep_features: bool, dry_run: bool,
               requirements: list[dict] | None, strict: bool, label: str | None) -> dict[str, Any]:
    """Build the part's solid with a CadQuery (default) or FreeCAD Part script, as one transaction.

    The script runs in a process of its own, with a job folder in the workspace's state directory as working
    directory and the policy's time limit: CadQuery in a child of AgentCAD's own interpreter (FreeCAD's Python
    cannot import it), a FreeCAD script in a FreeCAD process with no document open. Only its solid comes back, as
    BREP (OpenCASCADE's native format, exact). A second FreeCAD job makes it the Body's BaseFeature, rebuilds kept
    features on it, saves a candidate, re-opens and validates it, and AgentCAD commits it like a batch (checkpoint,
    journal with the full script, rollback). A missing part is created (mm); script numbers are in the part's
    unit, and the result reports the solid in mm, like validation.shape."""
    from .. import scripting
    rt.policy.check_scripts_allowed()
    if not dry_run:
        rt.policy.check_write()
    lang = (language or "cadquery").strip().lower()
    if lang not in SCRIPT_LANGUAGES:
        raise input_error("BAD_LANGUAGE", f"language {language!r} is not available for a 3D part",
                          hint="'cadquery' (default) or 'freecad' (Part module); ezdxf scripts are for .dxf drawings")
    scripting.check_script(code, lang)
    if lang == "cadquery" and importlib.util.find_spec("cadquery") is None:
        raise AgentCADError("DEPENDENCY_MISSING", "CadQuery is not installed in AgentCAD's Python",
                            category="dependency", hint=CQ_HINT)
    p, store = store_for(rt, path, must_exist=False)
    new = not p.exists()
    sha = hashlib.sha256(code.encode("utf-8")).hexdigest()
    record = {"language": lang, "code": code, "code_sha256": sha, "lines": len(code.splitlines()),
              **({"label": label} if label else {})}
    timeout = rt.policy.script_timeout
    cand = _candidate(rt)
    job_dir = _jobs(rt) / f"script-{uuid.uuid4().hex[:12]}"
    fail = {"tool": "run_script", "kind": "part", "ok": False, "label": label, "language": lang, "code": code,
            "code_sha256": sha}
    try:
        with rt._lock(store):
            if not new:
                store.load()
            base: dict[str, Any] = {"record": record, "keep_features": bool(keep_features)}
            inputs = {} if new else {"input": p}
            job: dict[str, Any] = {"action": "apply", "ops": [], "requirements": requirements, "base": base}
            if new:
                job.update(input=None, units="mm")
            script: dict[str, Any] = {"language": lang}
            brep = job_dir / "result.brep"
            try:
                if lang == "cadquery":
                    res = scripting.run_cadquery(code, job_dir, timeout)
                    if not res.get("ok"):
                        raise _script_error(res)
                else:
                    res = _freecad_script(rt, code, job_dir, brep, timeout)
                script["seconds"] = res.get("seconds")
                if res.get("stdout"):
                    script["stdout"] = res["stdout"]
                inputs["base_brep"] = brep
                out = _run(rt, job, inputs=inputs, outputs={"output": cand})
            except AgentCADError as exc:
                store.journal({**fail, "error": exc.to_dict(), "file_unchanged": True})
                raise
            based = out.get("base") or {}
            script["solid"] = {**based.get("solid", {}), **({"fused": True} if res.get("fused") else {})}
            report = out["report"]
            result = {"drawing": rt._rel(p), "changes": out["changes"], "script": script,
                      **({"features_kept": based["features_kept"]} if based.get("features_kept") else {}),
                      **({"created": {"units": "mm"}} if new else {})}
            if dry_run:
                return {**result, "dry_run": True, "validation": _brief(report)}
            if strict and not report["passed"]:
                snap = _snapshot(rt, store, cand)
                store.journal({**fail, "error": {"code": "VALIDATION_FAILED"}, "failure_snapshot": snap})
                raise AgentCADError("VALIDATION_FAILED", "Validation of the script's solid failed; nothing was saved",
                                    category="validation", hint="Inspect validation.issues; fix the script and retry",
                                    details={"validation": _brief(report), "failure_snapshot": snap})
            attempt = {"tool": "run_script", "kind": "part", "label": label, "language": lang, "code": code,
                       "code_sha256": sha, "keep_features": bool(keep_features), "changes": out["changes"],
                       **({"created": {"units": "mm"}} if new else {})}
            info = store.commit_bytes(cand.read_bytes(), label=label or "run_script", attempt=attempt)
            seq = store.journal({**attempt, "ok": True,
                                 **({"stdout": script["stdout"]} if script.get("stdout") else {}), **info})
    finally:
        cand.unlink(missing_ok=True)
        shutil.rmtree(job_dir, ignore_errors=True)
    return {**result, "validation": _brief(report), "journal_seq": seq, **info}


def read(rt: "Runtime", path: str) -> dict[str, Any]:
    p, store = store_for(rt, path)
    store.load()
    s = _run(rt, {"action": "summary"}, inputs={"input": p})["summary"]
    return {"drawing": rt._rel(p), "kind": "part", **s, "status": store.status(),
            "checkpoints": [c["id"] for c in store.list_checkpoints()]}


def inspect(rt: "Runtime", path: str, filter: dict | None, limit: int, offset: int) -> dict[str, Any]:  # noqa: A002
    p, store = store_for(rt, path)
    store.load()
    f = dict(filter or {})
    kind = f.get("kind", "features")
    if kind == "features":
        s = _run(rt, {"action": "summary", "detail": True}, inputs={"input": p})["summary"]
        items = [x for b in s["bodies"] for x in b["features"]]
        if f.get("feature"):
            want = str(f["feature"]).removeprefix("tag:")
            items = [x for x in items if want in (x["name"], x.get("tag"))]
    else:
        unknown = set(f) - {"kind", "feature", "selector"}
        if unknown:
            raise input_error("BAD_FILTER", f"Unknown filter keys {sorted(unknown)} for a part",
                              hint="{kind: features|faces|edges, feature: <ref> (default the Body), selector: {...}}")
        items = _run(rt, {"action": "topology", "filter": f}, inputs={"input": p})["items"]
    limit = max(1, min(int(limit), 5000))
    page = items[offset:offset + limit]
    return {"drawing": rt._rel(p), "kind": kind, "total": len(items), "offset": offset, "returned": len(page),
            "entities": page, "next_offset": offset + limit if offset + limit < len(items) else None}


def validate(rt: "Runtime", path: str, requirements: list[dict] | None, detail: bool) -> dict[str, Any]:
    p, store = store_for(rt, path)
    try:
        store.load()
    except AgentCADError as exc:
        return {"drawing": rt._rel(p), "validation": {"readable": False, "passed": False,
                                                      "issues": [{"code": exc.code, "severity": "error",
                                                                  "message": exc.message}]}}
    report = _run(rt, {"action": "validate", "requirements": requirements}, inputs={"input": p})["report"]
    report["file"] = rt._rel(p)
    report["requirements_source"] = "explicit" if requirements else None
    return {"drawing": rt._rel(p), "validation": report if detail else _brief(report)}


def export(rt: "Runtime", path: str, output: str, format: str, overwrite: bool,  # noqa: A002
           views: list | None = None, image_size: int | None = None, fit: str | None = None,
           reference: str | None = None) -> dict[str, Any]:
    """png: a shaded preview (parallel projection, part centred and filling the frame) of one view, or a labelled
    grid of several. views: names (iso, front, back, right, left, top, bottom, iso_back, iso_bottom) or [x, y, z]
    directions from the part towards the camera. fit 'view' fills each view; 'uniform' uses one scale for all.
    reference: an image in the workspace laid out as the same grid of views; the png is then a diff of each view,
    laid out the same way, and the result scores each view's outline and the edges inside it (compare.py)."""
    rt.policy.check_write()
    p, store = store_for(rt, path)
    store.load()
    fmt = format.lower().replace("stp", "step")
    if fmt not in EXPORTS:
        raise input_error("UNSUPPORTED_FORMAT", f"Unsupported export format {format!r} for a 3D part",
                          hint=f"{' | '.join(EXPORTS)}")
    out = rt.policy.resolve(output, suffixes=EXPORTS[fmt])
    if out.exists() and not overwrite:
        raise input_error("FILE_EXISTS", f"{output} exists", hint="overwrite=true")
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt != "png" and (views or image_size or fit or reference):
        raise input_error("UNKNOWN_PARAM", "views, image_size, fit and reference apply to png previews only")
    if reference:
        return _export_compare(rt, p, store, out, views, image_size, fit, reference)
    tmp = _jobs(rt) / f"export-{uuid.uuid4().hex[:12]}{out.suffix}"
    job = {"action": "render", "views": views, "size": image_size, "fit": fit} if fmt == "png" else \
        {"action": "export", "format": fmt}
    try:
        res = _run(rt, job, inputs={"input": p}, outputs={"output": tmp})
        shutil.move(str(tmp), out)
    finally:
        tmp.unlink(missing_ok=True)
    store.journal({"tool": "export_drawing", "kind": "part", "ok": True, "output": rt._rel(out), "format": fmt})
    return {"drawing": rt._rel(p), "output": rt._rel(out), "format": fmt, "bytes": out.stat().st_size,
            "shape": res["shape"], **{k: res[k] for k in ("readback", "views", "grid", "cell_size", "fit") if k in res}}


def _export_compare(rt: "Runtime", p: Path, store: DrawingStore, out: Path, views: list | None,
                    image_size: int | None, fit: str | None, reference: str) -> dict[str, Any]:
    import numpy as np

    from . import compare
    if fit:
        raise input_error("UNKNOWN_PARAM", "fit does not apply with a reference: each view is aligned to it")
    views = views or ["iso"]
    if not isinstance(views, list) or not 1 <= len(views) <= 9:
        raise input_error("BAD_VIEW", "views: a list of 1 to 9 views")
    cell = 256 if image_size is None else image_size
    if isinstance(cell, bool) or not isinstance(cell, (int, float)) or cell != int(cell) or not 64 <= cell <= 1024:
        raise input_error("OUT_OF_RANGE", f"image_size {image_size!r}: with a reference, 64..1024 pixels per cell",
                          hint="Each reference cell is compared at 1024 px at most; 256 (the default) is plenty")
    cell = int(cell)
    ref = rt.policy.resolve(reference, must_exist=True, suffixes=compare.IMAGE_SUFFIXES)
    cells = compare.load_reference(ref, len(views))
    size = int(min(1024, max(128, max(cells[0][0].shape[:2]))))  # render at about the reference's resolution
    tmp = _jobs(rt) / f"compare-{uuid.uuid4().hex[:12]}"
    try:
        res = _run(rt, {"action": "render", "views": views, "size": size}, inputs={"input": p},
                   outputs={"raw": tmp.with_suffix(".npz")})
        with np.load(tmp.with_suffix(".npz")) as z:
            renders = [(z[f"img{i}"], z[f"mask{i}"], z[f"seam{i}"]) for i in range(len(views))]
        names = res["views"]
        results, diffs, mode = compare.compare_views(cells, names, renders)
        labels = [f"{n}  {r['score']:.2f}" if r["score"] is not None else n for n, r in zip(names, results)]
        grid, cell = compare.save_sheet(diffs, labels, tmp.with_suffix(".png"), cell)
        shutil.move(str(tmp.with_suffix(".png")), out)
    finally:
        tmp.with_suffix(".npz").unlink(missing_ok=True)
        tmp.with_suffix(".png").unlink(missing_ok=True)
    scores = [r["score"] for r in results if r["score"] is not None]
    summary = {"reference": rt._rel(ref), "score": round(sum(scores) / len(scores), 3) if scores else None,
               "views": results}
    if mode != "filled":
        summary["reference_mode"] = mode
    if scores and all(r["edges"] is None for r in results):
        summary["note"] = "no edges inside the reference's outlines to compare: scored on outlines only"
    store.journal({"tool": "export_drawing", "kind": "part", "ok": True, "output": rt._rel(out), "format": "png",
                   "reference": rt._rel(ref), "score": summary["score"]})
    # no shape summary and no legend: the diff is what this call is for, and every later turn pays for its result
    return {"drawing": rt._rel(p), "output": rt._rel(out), "format": "png", "bytes": out.stat().st_size,
            "grid": grid, "cell_size": cell, "compare": summary}


def diff(rt: "Runtime", path: str, against: str) -> dict[str, Any]:
    p, store = store_for(rt, path)
    if against == "previous":
        cps = store.list_checkpoints()
        if not cps:
            raise input_error("NO_CHECKPOINT", "The part has no checkpoints to diff against")
        other, label = store.checkpoint_path(cps[-1]["id"]), cps[-1]["id"]
    elif against.startswith("cp-"):
        other, label = store.checkpoint_path(against), against
    else:
        other = rt.policy.resolve(against, must_exist=True, suffixes=(SUFFIX,))
        label = rt._rel(other)
    cur = _run(rt, {"action": "summary", "detail": True}, inputs={"input": p})["summary"]
    old = _run(rt, {"action": "summary", "detail": True}, inputs={"input": other})["summary"]
    return {"drawing": rt._rel(p), "against": label, **compare(old, cur)}


def compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    def feats(s):
        return {f["name"]: f for b in s["bodies"] for f in b["features"]}

    fo, fn = feats(old), feats(new)
    modified = []
    for n in fo.keys() & fn.keys():
        a, b = fo[n].get("op"), fn[n].get("op")
        if a != b or fo[n].get("dimensions") != fn[n].get("dimensions"):
            ch = {}
            if isinstance(a, dict) and isinstance(b, dict):
                ch = {k: {"old": a.get(k), "new": b.get(k)} for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
            if fo[n].get("dimensions") != fn[n].get("dimensions"):
                ch["dimensions"] = {"old": fo[n].get("dimensions"), "new": fn[n].get("dimensions")}
            modified.append({"id": n, "type": fn[n]["type"], "changed": ch})
    po, pn = old.get("parameters", {}), new.get("parameters", {})
    params = {k: {"old": po.get(k, {}).get("value"), "new": pn.get(k, {}).get("value")}
              for k in po.keys() | pn.keys() if po.get(k) != pn.get(k)}

    def shape(s):
        return next((b["shape"] for b in s["bodies"] if b.get("shape")), None) or {}

    so, sn = shape(old), shape(new)
    sh = {k: {"old": so.get(k), "new": sn.get(k)} for k in ("volume", "size", "solids", "holes") if so.get(k) != sn.get(k)}
    return {"added": [{"id": n, "type": fn[n]["type"], **({"tag": fn[n]["tag"]} if fn[n].get("tag") else {})}
                      for n in fn.keys() - fo.keys()],
            "deleted": [{"id": n, "type": fo[n]["type"]} for n in fo.keys() - fn.keys()],
            "modified": modified, "parameters": params, "shape": sh}
