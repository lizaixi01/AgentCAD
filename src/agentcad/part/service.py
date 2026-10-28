"""3D parts (``.FCStd``) behind the same tools as drawings. ``service.Runtime`` hands a call here when the path is a
part; the store, journal, checkpoints, lock and result envelope are the ones drawings use.

A batch runs in a FreeCAD process on a copy of the part and is saved to a candidate file. The runner re-opens that
file as a fresh document and validates it; only then is it committed (checkpoint, atomic replace, journal). A failed
batch never touches the part.
"""
from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..backends import freecad
from ..errors import AgentCADError, file_error, input_error
from ..policy import Policy
from ..store import DrawingStore
from ..units import normalize_unit
from .ops import prevalidate

if TYPE_CHECKING:
    from ..service import Runtime

SUFFIX = ".fcstd"
EXPORTS = {"step": (".step", ".stp"), "iges": (".iges", ".igs"), "brep": (".brep", ".brp"), "stl": (".stl",),
           "obj": (".obj",)}


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
         outputs: dict[str, Path] | None = None) -> dict[str, Any]:
    res = freecad.run(job, inputs, outputs)
    if not res.get("ok"):
        e = res.get("error") or {}
        cat = e.get("category", "internal")
        raise AgentCADError(e.get("code", "FREECAD_ERROR"), e.get("message", "FreeCAD job failed"),
                            category=cat if cat in ("input", "geometry", "file", "internal", "validation") else "internal",
                            entities=e.get("entities"), op_index=e.get("op_index"), op=e.get("op"),
                            hint=e.get("hint"), details=e.get("details"))
    return res


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
    prevalidate(operations, rt.policy)
    cand = _candidate(rt)
    try:
        with rt._lock(store):
            if not new:
                store.load()
            job = {"action": "apply", "ops": operations, "requirements": requirements}
            if new:
                job.update(input=None, units=units)
            try:
                res = _run(rt, job, inputs=None if new else {"input": p}, outputs={"output": cand})
            except AgentCADError as exc:
                store.journal({"tool": "apply_operations", "kind": "part", "ok": False, "label": label,
                               "operations": operations, "error": exc.to_dict(), "file_unchanged": True})
                raise
            report = res["report"]
            if dry_run:
                return {"drawing": rt._rel(p), "dry_run": True, "would_change": res["changes"],
                        "results": res["results"], "validation": _brief(report)}
            if strict and not report["passed"]:
                snap = _snapshot(rt, store, cand)
                store.journal({"tool": "apply_operations", "kind": "part", "ok": False, "label": label,
                               "operations": operations, "error": {"code": "VALIDATION_FAILED"},
                               "failure_snapshot": snap})
                raise AgentCADError("VALIDATION_FAILED", "Post-operation validation failed; nothing was saved",
                                    category="validation", hint="Inspect validation.issues; fix the operations and retry",
                                    details={"validation": _brief(report), "failure_snapshot": snap})
            info = store.commit_bytes(cand.read_bytes(), label=label or "apply_operations")
            seq = store.journal({"tool": "apply_operations", "kind": "part", "ok": True, "label": label,
                                 "operations": operations, "changes": res["changes"],
                                 **({"created": {"units": units}} if new else {}), **info})
    finally:
        cand.unlink(missing_ok=True)
    return {"drawing": rt._rel(p), "changes": res["changes"], "results": res["results"],
            "validation": _brief(report), "journal_seq": seq, **({"created": {"units": units}} if new else {}),
            **info}


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


def export(rt: "Runtime", path: str, output: str, format: str, overwrite: bool) -> dict[str, Any]:  # noqa: A002
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
    tmp = _jobs(rt) / f"export-{uuid.uuid4().hex[:12]}{out.suffix}"
    try:
        res = _run(rt, {"action": "export", "format": fmt}, inputs={"input": p}, outputs={"output": tmp})
        shutil.move(str(tmp), out)
    finally:
        tmp.unlink(missing_ok=True)
    store.journal({"tool": "export_drawing", "kind": "part", "ok": True, "output": rt._rel(out), "format": fmt})
    return {"drawing": rt._rel(p), "output": rt._rel(out), "format": fmt, "bytes": out.stat().st_size,
            "shape": res["shape"], **({"readback": res["readback"]} if "readback" in res else {})}


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
