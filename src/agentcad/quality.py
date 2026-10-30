"""Observable drawing quality and delivery evidence."""

from __future__ import annotations

import json

from .errors import AgentCADError, input_error
from .store import now, sha256_file
from .validate import validate_file


def score(report):
    summary = report["summary"]
    return max(
        0, 100 - 15 * summary["errors"] - 3 * summary["warnings"] - 15 * summary.get("requirements_failed", 0)
    )


def deliver(rt, path, output_dir, formats, min_score, strict):
    rt.policy.check_write()
    if (
        not 0 <= min_score <= 100
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
        report = validate_file(p)
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
            reread = validate_file(target)["readable"] if fmt == "dxf" else target.stat().st_size > 0
            if not reread:
                raise input_error("DELIVERY_UNREADABLE", f"Cannot reread {target.name}")
            files.append(
                {
                    "path": rt._rel(target),
                    "sha256": sha256_file(target),
                    "bytes": target.stat().st_size,
                    "format": fmt,
                    "reread_ok": reread,
                }
            )
        if sha256_file(p) != source:
            raise input_error("STALE_REVISION", "Source changed during export; no delivery manifest issued")
        manifest = {
            "version": 1,
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
