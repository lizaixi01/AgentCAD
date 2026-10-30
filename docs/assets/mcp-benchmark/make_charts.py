"""Render the README benchmark figure from pinned runtime reports.

Run: python docs/assets/mcp-benchmark/make_charts.py
Requires matplotlib. --check verifies the committed SVGs; --preview-dir writes
PNG previews outside the repository. Source-review scores are never input to
the runtime chart. Report hashes allow Git's LF/CRLF checkout conversion only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "line": "#dce2e8", "us": "#2274ce", "other": "#858f9b"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#a3adb8", "line": "#30363d", "us": "#58a6ff", "other": "#8b949e"},
}


def read_rows():
    data = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
    rows = []
    tasks = None
    for source in data["runtime"]["reports"]:
        raw = (ROOT / source["path"]).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(raw).hexdigest() != source["sha256_lf"]:
            raise ValueError(f"Pinned report hash differs: {source['path']}")
        report = json.loads(raw)
        results = report["results"]
        task_ids = {r["task_id"] for r in results}
        assert report["matrix"] == data["runtime"]["matrix"] == "v8"
        assert len(results) == len(task_ids) == data["runtime"]["task_count"] == 31
        assert tasks is None or tasks == task_ids
        tasks = task_ids
        summary = report["summary"]
        assert sum(r["status"] == "pass" for r in results) == summary["passed"]
        assert all(r["status"] == "pass" and r["score"] == 100 for r in results)
        assert summary["score"] == 100 and summary["attempted"] == 31
        tokens = next(r["metrics"] for r in results if r["task_id"] == "token_budget")
        assert tokens["tokenizer"] == "ratio/v1 (estimate)"
        assert tokens["advertised_tools"] == 3 and tokens["ceiling"] == 2000
        product_sha = report.get("adapter_metadata", {}).get("product_sha", report["git_sha"])
        rows.append({**source, "score": summary["score"], "passed": summary["passed"], "tokens": tokens["discovery_tokens"], "product_sha": product_sha})
    assert [r["id"] for r in rows] == ["agentcad", "autocad-mcp-pro"]
    return data, rows


def draw(theme, data, rows, output, preview=None):
    t = THEMES[theme]
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path", "svg.hashsalt": "agentcad-mcp-v8-20261030"})
    fig = plt.figure(figsize=(10.6, 6.5), facecolor=t["bg"])
    fig.text(.045, .94, "U-C4N v8 benchmark", color=t["ink"], fontsize=19, weight="bold")
    fig.text(.045, .895, "Joint highest score in the reproduced v8 set", color=t["ink"], fontsize=13)
    fig.text(.955, .94, data["checked_at"], ha="right", color=t["muted"], fontsize=10)

    fig.text(.045, .82, "FIXED-TASK RUNTIME SCORE", color=t["muted"], fontsize=9, weight="bold")
    ax = fig.add_axes([.31, .50, .60, .25], facecolor=t["bg"])
    ax.set_xlim(0, 105)
    ax.set_ylim(-.6, 1.6)
    ax.axis("off")
    for row, y in zip(rows, [1, 0]):
        color = t["us"] if row["id"] == "agentcad" else t["other"]
        ax.barh(y, row["score"], height=.42, color=color)
        ax.text(98, y, f"{row['score']:.0f} / 100", ha="right", va="center", fontsize=12, color=t["bg"], weight="bold")
        ax.text(-4, y, row["label"], ha="right", va="center", fontsize=12, color=t["ink"], weight="bold")
        ax.text(0, y-.44, f"{row['passed']}/31 passed  ·  shared rank 1", fontsize=9, color=t["muted"])

    fig.add_artist(plt.Line2D([.045, .955], [.46, .46], color=t["line"], transform=fig.transFigure))
    fig.text(.045, .405, "DISCOVERY SCHEMA SIZE", color=t["muted"], fontsize=9, weight="bold")
    fig.text(.045, .335, f"{rows[0]['tokens']} vs {rows[1]['tokens']}", color=t["ink"], fontsize=24, weight="bold")
    reduction = (1 - rows[0]["tokens"] / rows[1]["tokens"]) * 100
    fig.text(.38, .35, f"{reduction:.1f}% smaller for AgentCAD", color=t["us"], fontsize=13, weight="bold")
    fig.text(.38, .31, "3 advertised tools each · same ratio/v1 estimator", color=t["muted"], fontsize=10)
    fig.text(.045, .265, "Estimated tokens, not billed tokens. Both pass the 2,000 ceiling; no extra score is awarded.", color=t["muted"], fontsize=9)

    fig.add_artist(plt.Line2D([.045, .955], [.22, .22], color=t["line"], transform=fig.transFigure))
    fig.text(.045, .167, f"AgentCAD {rows[0]['product_sha'][:7]}: upstream runner. Pro {rows[1]['product_sha'][:7]}: same-machine rerun.", color=t["ink"], fontsize=9)
    fig.text(.045, .128, "Local reproduced results; AgentCAD is not an official upstream listing. No model or speed ranking.", color=t["muted"], fontsize=9)
    fig.text(.045, .071, "Pro's published 93/100 is a separate source-review self-assessment, not this runtime score.", color=t["muted"], fontsize=9)
    fig.savefig(output, facecolor=t["bg"], metadata={"Date": None})
    normalized = "\n".join(line.rstrip() for line in output.read_text(encoding="utf-8").splitlines()) + "\n"
    output.write_text(normalized, encoding="utf-8", newline="\n")
    if preview:
        preview.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview, dpi=150, facecolor=t["bg"])
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    data, rows = read_rows()
    with tempfile.TemporaryDirectory(prefix="agentcad-benchmark-chart-") as temporary:
        for theme in THEMES:
            destination = HERE / f"leaderboard-{theme}.svg"
            target = Path(temporary) / destination.name if args.check else destination
            preview = args.preview_dir / f"leaderboard-{theme}.png" if args.preview_dir else None
            draw(theme, data, rows, target, preview)
            if args.check and target.read_bytes() != destination.read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"Regenerate {destination}")
    print("Two v8 reports verified; light/dark figures " + ("match" if args.check else "generated"))


if __name__ == "__main__":
    main()
