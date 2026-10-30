"""Observable drawing quality and delivery evidence."""

from __future__ import annotations

import json
import math

from .errors import AgentCADError, input_error
from .delivery import verify_artifact
from .store import now, sha256_file


def score(report):
    summary = report["summary"]
    return max(
        0, 100 - 15 * summary["errors"] - 3 * summary["warnings"] - 15 * summary.get("requirements_failed", 0)
    )


def assess(rt, p, doc):
    """Reopen the source, restore its intent, and check every saved native domain."""
    report = rt._drawing_validation(p)
    if not report["readable"]:
        return report
    # Generic validation is layout-scoped; delivery checks every nonempty paper layout too.
    layouts = [s.name for s in doc.layouts if s.name != "Model" and len(s)]
    issues = [i for i in report["issues"] if i["code"] != "LAYOUT_NOT_VALIDATED"]
    seen = {json.dumps(i, sort_keys=True) for i in issues}
    for layout in layouts:
        other = rt._drawing_validation(p, use_stored_spec=False, layout=layout)
        for issue in other["issues"]:
            key = json.dumps(issue, sort_keys=True)
            if issue["code"] != "LAYOUT_NOT_VALIDATED" and key not in seen:
                issues.append({**issue, "layout": layout})
                seen.add(key)
    from .engineering import architecture, mechanical, pid
    domains = {}
    for name, app, reader in (("architecture", "ARCH", architecture.read),
                              ("mechanical", "MECH", mechanical.read), ("pid", "PID", pid.read)):
        if "AGENTCAD_" + app in doc.appids:
            critique = reader(doc)["critique"]
            outside = [(s.name, e.dxf.handle) for s in doc.layouts if s.name != "Model"
                       for e in s if e.has_xdata("AGENTCAD_" + app)]
            outside.extend((b.name, e.dxf.handle) for b in doc.blocks if not b.block_record.is_any_layout
                           for e in b if e.has_xdata("AGENTCAD_" + app))
            critique.extend({"code": "DOMAIN_LAYOUT_UNSUPPORTED", "handle": handle, "space": space}
                            for space, handle in outside)
            domains[name] = {"critique": critique, "passed": not critique}
            issues.extend({"code": i["code"], "severity": "error", "category": "engineering",
                           "message": f"{name}: {i['code']}", "entities": [i["handle"]] if i.get("handle") else [],
                           "details": i, "domain": name} for i in critique)
    report["issues"] = issues
    report["engineering"] = domains
    report["coverage"] = {"checked_layouts": ["Model", *layouts], "unchecked_layouts": []}
    report["summary"].update(errors=sum(i["severity"] == "error" for i in issues),
                             warnings=sum(i["severity"] == "warning" for i in issues))
    report["passed"] = not report["summary"]["errors"] and not report["summary"].get("requirements_failed", 0)
    return report


def deliver(rt, path, output_dir, formats, min_score, strict):
    rt.policy.check_write()
    if (
        isinstance(min_score, bool) or not isinstance(min_score, (int, float))
        or not math.isfinite(min_score) or not 0 <= min_score <= 100
        or not formats
        or set(formats) - {"dxf", "pdf", "svg", "json", "csv", "xlsx"}
    ):
        raise input_error("BAD_PARAMETER", "Delivery needs supported formats and min_score in 0..100")
    p, store = rt._drawing(path)
    folder = rt.policy.resolve(output_dir)
    if folder.exists() and any(folder.iterdir()):
        raise input_error("FILE_EXISTS", "Delivery directory must be empty; earlier manifests are preserved")
    with rt._lock(store):
        source = sha256_file(p)
        doc = store.load()
        report = assess(rt, p, doc)
        quality = score(report)
        if quality < min_score or strict and not report["passed"]:
            raise AgentCADError(
                "DELIVERY_REJECTED",
                "Drawing does not meet delivery quality",
                category="validation",
                details={"score": quality, "validation": report},
            )
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for fmt in dict.fromkeys(formats):
            target = folder / f"{p.stem}.{fmt}"
            result = rt.export_drawing(path, rt._rel(target), fmt)
            if not result["ok"]:
                raise AgentCADError(
                    "DELIVERY_EXPORT_FAILED", f"Export {fmt} failed", category="file", details=result
                )
            verification = verify_artifact(doc, target, fmt, result)
            files.append(
                {
                    "path": rt._rel(target),
                    "sha256": sha256_file(target),
                    "bytes": target.stat().st_size,
                    "format": fmt,
                    "reread_ok": True,
                    "verification": verification,
                }
            )
        if sha256_file(p) != source:
            raise input_error("STALE_REVISION", "Source changed during export; no delivery manifest issued")
        manifest = {
            "version": 2,
            "created": now(),
            "source": rt._rel(p),
            "source_sha256": source,
            "revision": store.head().get("revision", 0),
            "quality_score": quality,
            "validation": report,
            "artifacts": files,
        }
        dest = folder / "manifest.json"
        dest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"status": "success", "manifest": rt._rel(dest), "sha256": sha256_file(dest), **manifest}
