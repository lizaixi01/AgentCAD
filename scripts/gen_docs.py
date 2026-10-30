"""Generate docs/operations.md (op catalog from the registry) and
docs/op_test_matrix.md (which test files exercise each op). Run after changes:
    python scripts/gen_docs.py
"""
from __future__ import annotations

import re
import argparse
from pathlib import Path

from agentcad.constraints import CHECK_TYPES, ENFORCE_TYPES
from agentcad.ops import REGISTRY
from agentcad.part.ops import PART_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def ops_md() -> str:
    lines = ["# 操作目录 (自动生成)", "", "由 `scripts/gen_docs.py` 从 `agentcad.ops.REGISTRY` 和 "
             "`agentcad.part.ops.PART_REGISTRY` 生成，与 `list_operations` 返回一致。",
             "长度参数接受数字（图纸单位）或带单位字符串（如 `\"8mm\"`）；角度为度、逆时针。",
             "`part_*` 类别是三维零件（.FCStd）的操作，`dim` 类型还接受表达式（如 `\"=Params.width\"`），"
             "见 [part-3d.md](part-3d.md)。", ""]
    by_cat: dict[str, list] = {}
    for d in [*REGISTRY.values(), *PART_REGISTRY.values()]:
        by_cat.setdefault(d.category, []).append(d)
    for cat in sorted(by_cat):
        lines += [f"## {cat}", ""]
        for d in sorted(by_cat[cat], key=lambda x: x.name):
            lines += [f"### `{d.name}`", "", d.description, "", "| 参数 | 类型 | 必需 | 默认 | 说明 |", "|---|---|---|---|---|"]
            for k, p in d.all_params().items():
                rng = "".join(s for s in (f" >{p.gt}" if p.gt is not None else "", f" ≥{p.ge}" if p.ge is not None else "",
                                          f" ≤{p.le}" if p.le is not None else ""))
                typ = p.type + (f" {p.enum}" if p.enum else "") + rng
                description = p.description.replace("|", "\\|")
                lines.append(f"| `{k}` | {typ} | {'是' if p.required else ''} | {'' if p.default is None else p.default} | {description} |")
            lines.append("")
    lines += ["## 约束类型", "", f"- 可检查: {', '.join(sorted(CHECK_TYPES))}",
              f"- 可强制（顺序直接修改，非联立求解）: {', '.join(sorted(ENFORCE_TYPES))}", ""]
    return "\n".join(lines)


def matrix_md() -> str:
    tests = {p.name: p.read_text("utf-8") for p in sorted((ROOT / "tests").glob("test_*.py"))}
    lines = ["# 操作 × 测试矩阵 (自动生成)", "", "统计每个操作在哪些测试文件中以 `\"op\": \"<name>\"` 形式被调用。",
             "这只说明“被执行过”，断言质量见各测试本身。三维零件操作只统计 test_n_parts.py（二维和三维有同名操作）。",
             "", "| 操作 | 类别 | 测试文件 |", "|---|---|---|"]
    untested = []
    part_tests = {f: t for f, t in tests.items() if f == "test_n_parts.py"}
    rows = [(n, REGISTRY[n].category, {f: t for f, t in tests.items() if f != "test_n_parts.py"}) for n in sorted(REGISTRY)]
    rows += [(n, PART_REGISTRY[n].category, part_tests) for n in sorted(PART_REGISTRY)]
    for name, cat, where in rows:
        pat = re.compile(r'"op":\s*"' + re.escape(name) + r'"')
        hits = [f for f, t in where.items() if pat.search(t)]
        if not hits:
            untested.append(f"{name} ({cat})")
        lines.append(f"| `{name}` | {cat} | {', '.join(hits) or '**无**'} |")
    lines += ["", f"共 {len(rows)} 个操作，未被任何测试调用: {untested or '无'}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated operation docs are stale")
    args = parser.parse_args()
    files = {"operations.md": ops_md(), "op_test_matrix.md": matrix_md()}
    if args.check:
        stale = [name for name, expected in files.items()
                 if not (DOCS / name).is_file() or (DOCS / name).read_text("utf-8") != expected]
        if stale:
            raise SystemExit("Stale generated documentation: " + ", ".join(stale))
        print("operation catalog and test matrix match the source")
        raise SystemExit(0)
    DOCS.mkdir(exist_ok=True)
    for name, content in files.items():
        (DOCS / name).write_text(content, "utf-8")
    print("wrote docs/operations.md, docs/op_test_matrix.md")
