"""Independent validator.

``validate_file`` re-reads the DXF from disk (never an in-memory document from
the generator) and checks it against generic integrity rules and, optionally,
explicit requirements. It shares no state with the operation engine.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import ezdxf

from ..errors import AgentCADError
from .checks import run_generic_checks
from .features import extract, pick_outline
from .requirements import check_requirements


def validate_file(path: Path, *, requirements: list[dict[str, Any]] | None = None, bounds: list | None = None,
                  tolerance: float = 1e-6, contour_layers: list[str] | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    report: dict[str, Any] = {"file": str(path), "readable": False, "issues": [], "requirements": []}
    try:
        from ..policy import Policy
        from ..store import read_dxf
        doc = read_dxf(path, Policy(root=path.parent))
    except AgentCADError as exc:
        report["issues"].append({"code": exc.code, "severity": "error", "category": "file",
                                 "message": exc.message, "entities": []})
        report["passed"] = False
        report["summary"] = {"errors": 1, "warnings": 0, "requirements_failed": 0}
        report["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return report
    report["readable"] = True
    # re-readability sanity: the parsed document must pass ezdxf's structural audit
    auditor = doc.audit()
    for err in auditor.errors:
        report["issues"].append({"code": "DXF_AUDIT_ERROR", "severity": "error", "category": "file",
                                 "message": str(err.message), "entities": []})
    feats = extract(doc)
    report["issues"].extend(run_generic_checks(doc, feats, bounds=bounds, tolerance=tolerance,
                                               contour_layers=contour_layers))
    if requirements:
        counts = [(e.dxftype(), e.dxf.layer, e.dxf.handle) for e in doc.modelspace()]
        report["requirements"] = check_requirements(feats, requirements, counts)
    o = pick_outline(feats, (contour_layers or [None])[0])
    report["recognized"] = {
        "outline": None if o is None else {"entities": o.entities, "bbox": [round(v, 9) for v in o.bbox],
                                           "size": [round(v, 9) for v in o.size]},
        "circles": [{"id": h.id, "center": [round(h.center[0], 9), round(h.center[1], 9)],
                     "diameter": round(h.diameter, 9)} for h in feats.circles],
        "dimensions": [{"id": d["id"], "kind": d["kind"],
                        "measurement": None if d["measurement"] is None else round(d["measurement"], 9)}
                       for d in feats.dimensions],
        "closed_contours": len(feats.contours),
        "entity_count": len(doc.modelspace()),
        "ezdxf_version": ezdxf.__version__,
    }
    errors = sum(1 for i in report["issues"] if i["severity"] == "error")
    warnings = sum(1 for i in report["issues"] if i["severity"] == "warning")
    failed = sum(1 for r in report["requirements"] if r["status"] != "pass")
    report["summary"] = {"errors": errors, "warnings": warnings, "requirements_total": len(report["requirements"]),
                         "requirements_failed": failed}
    report["passed"] = errors == 0 and failed == 0
    report["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return report
