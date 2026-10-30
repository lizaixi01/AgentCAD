"""Run the unchanged reference gates, retaining artifacts before later tasks overwrite them."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

def preserve_artifacts(result, destination: Path):
    """Copy only returned artifacts; task inputs, verdict and metrics stay untouched."""
    kept = []
    for index, item in enumerate(result.artifacts):
        if isinstance(item, dict):
            source = Path(item["path"]) if item.get("path") else None
        else:
            source = Path(item)
        if source is None or not source.is_file():
            kept.append(item)
            continue
        target = destination / result.task_id / str(index) / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        kept.append({**item, "path": str(target)} if isinstance(item, dict) else str(target))
    result.artifacts = kept
    return result


def main():
    from run import PIN, digest, git

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    if git(upstream, "rev-parse", "HEAD") != PIN or git(upstream, "status", "--porcelain", "--untracked-files=no"):
        parser.error(f"upstream must be a clean checkout of {PIN}")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("--out must be new or empty")
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ["AUTOCAD_MCP_BACKEND"] = "ezdxf"
    sys.path.insert(0, str(upstream))
    from benchmarks.adapters.autocad_mcp_pro import AutoCADMCPProAdapter
    from benchmarks.run_competitors import run_tasks, _sanitize_for_publication
    from benchmarks.tasks_v8 import TASKS_V8

    class CapturedReference(AutoCADMCPProAdapter):
        async def run_task(self, task):
            print(f"START {task.task_id}", flush=True)
            result = await super().run_task(task)
            result = preserve_artifacts(result, args.out / "retained")
            print(f"END {task.task_id}: {result.status}", flush=True)
            return result

    report = asyncio.run(run_tasks(CapturedReference(backend="ezdxf"), TASKS_V8,
                                   args.out / "artifacts", timeout=180, matrix="v8"))
    report["artifact_capture"] = "Copy returned artifacts immediately after each original task; no fixture/gate/score changes."
    report["capture_script_sha256"] = digest(Path(__file__))
    (args.out / "report.json").write_text(json.dumps(_sanitize_for_publication(report), ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
