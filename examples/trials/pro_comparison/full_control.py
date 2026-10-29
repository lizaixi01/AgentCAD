"""Repeat selected pairs with Pro's default full tool catalogue instead of discovery."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

source = Path(__file__).with_name("run.py")
spec = importlib.util.spec_from_file_location("pro_comparison_run", source)
bench = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(bench)

bench.ORIENT["B"] = "该服务直接提供图纸读取、编辑、标注和验证等 CAD 工具，请按需使用其工具说明。"
original_build_cmd = bench.build_cmd
original_prepare = bench.prepare


def build_cmd(arm, workspace, pro):
    command = original_build_cmd(arm, workspace, pro)
    if arm == "B":
        command = [v.replace('DISCOVERY_MODE="search"', 'DISCOVERY_MODE="off"') for v in command]
    return command


def prepare(out, pro, reps, tasks):
    original_prepare(out, pro, reps, tasks)
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    fixture_source = os.environ.get("AGENTCAD_COMPARE_FIXTURES")
    if fixture_source:
        for task in tasks:
            destination = out / "fixtures" / (task + ".dxf")
            shutil.copyfile(Path(fixture_source) / (task + ".dxf"), destination)
            manifest["fixtures"][task] = bench.sha(destination)
        manifest["fixture_source"] = "copied from a previous comparison"
    manifest["pro_config"]["discovery_mode"] = "off"
    manifest["pro_config"]["catalogue"] = "full"
    bench.write_json(path, manifest)


bench.build_cmd = build_cmd
bench.prepare = prepare
if __name__ == "__main__":
    bench.main()
