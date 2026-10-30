"""Render the README source-capability figure.

Run: python docs/assets/source-capability/make_chart.py
Requires matplotlib. --check verifies the committed SVGs; --preview-dir writes
PNG previews outside the repository. The local rubric-v1 scores come from the
final assessment; the upstream board comes from the pinned rows in
docs/assets/mcp-benchmark/data.json. The two lists use different assessors and
scoring detail, so they are drawn as separate panels and never ranked together.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSESSMENT = ROOT / "examples/source_capability/results/2026-10-30/assessment.json"
UPSTREAM = ROOT / "docs/assets/mcp-benchmark/data.json"
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "line": "#dce2e8", "us": "#2274ce", "other": "#858f9b"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#a3adb8", "line": "#30363d", "us": "#58a6ff", "other": "#8b949e"},
}


def read_scores():
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    assert assessment["status"] == "complete"
    local = []
    for product in assessment["products"]:
        scores = [c["score"] for c in product["categories"]]
        assert sum(scores) == product["total_score"] and product["max_score"] == 100
        local.append({"label": product["name"], "sha": product["product_sha"][:7], "score": product["total_score"]})
    assert [r["label"] for r in local] == ["AgentCAD", "AutoCAD MCP Pro"]

    review = json.loads(UPSTREAM.read_text(encoding="utf-8"))["source_review"]
    upstream = sorted(review["projects"], key=lambda p: -p["score"])
    assert len(upstream) == 9 and review["agentcad_score"] is None
    return assessment["reviewed_at"], local, review, upstream


def draw(theme, reviewed_at, local, review, upstream, output, preview=None):
    t = THEMES[theme]
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path", "svg.hashsalt": "agentcad-source-capability-20261030"})
    fig = plt.figure(figsize=(10.6, 8.4), facecolor=t["bg"])
    fig.text(.045, .955, "Source-capability review", color=t["ink"], fontsize=19, weight="bold")
    fig.text(.045, .92, "AgentCAD leads Pro by two points under one rubric applied to both", color=t["ink"], fontsize=13)
    fig.text(.955, .955, reviewed_at, ha="right", color=t["muted"], fontsize=10)

    fig.text(.045, .865, "SAME LOCAL RUBRIC v1  ·  SIX UPSTREAM WEIGHTS  ·  INDEPENDENT AI REVIEWER", color=t["muted"], fontsize=9, weight="bold")
    ax = fig.add_axes([.36, .72, .55, .13], facecolor=t["bg"])
    ax.set_xlim(0, 105)
    ax.set_ylim(-.6, 1.6)
    ax.axis("off")
    for row, y in zip(local, [1, 0]):
        color = t["us"] if row["label"] == "AgentCAD" else t["other"]
        ax.barh(y, row["score"], height=.62, color=color)
        ax.text(row["score"] - 2, y, f"{row['score']} / 100", ha="right", va="center", fontsize=12, color=t["bg"], weight="bold")
        ax.text(-3, y, f"{row['label']}  {row['sha']}", ha="right", va="center", fontsize=12, color=t["ink"], weight="bold")

    fig.add_artist(plt.Line2D([.045, .955], [.685, .685], color=t["line"], transform=fig.transFigure))
    fig.text(.045, .65, "U-C4N PUBLISHED BOARD  ·  SEPARATE ASSESSMENT, NOT RANKED WITH THE ROWS ABOVE", color=t["muted"], fontsize=9, weight="bold")
    fig.text(.045, .623, f"Pro 1.6.0 self-review {review['reviewed_at']}; other rows are snapshots from {review['competitors_reviewed_at'][:7]}. AgentCAD is not listed.", color=t["muted"], fontsize=9)
    ax = fig.add_axes([.36, .19, .55, .42], facecolor=t["bg"])
    ax.set_xlim(0, 105)
    ax.set_ylim(-.6, len(upstream) - .4)
    ax.axis("off")
    for rank, project in enumerate(upstream, 1):
        y = len(upstream) - rank
        ax.barh(y, project["score"], height=.62, color=t["other"])
        ax.text(project["score"] + 1.5, y, f"{project['score']}  ·  {project['evidence_grade']}", va="center", fontsize=10, color=t["ink"])
        ax.text(-3, y, f"{rank}. {project['repository']}", ha="right", va="center", fontsize=10, color=t["ink"])

    fig.add_artist(plt.Line2D([.045, .955], [.15, .15], color=t["line"], transform=fig.transFigure))
    fig.text(.045, .11, "Under rubric v1 Pro scores 96, not its published 93: assessor, version and scoring detail differ.", color=t["ink"], fontsize=9)
    fig.text(.045, .075, "The other eight projects were not re-scored, so no overall rank is claimed. Requested and published by AgentCAD;", color=t["muted"], fontsize=9)
    fig.text(.045, .045, "not an upstream listing or external certification. Letters on the board are upstream evidence grades.", color=t["muted"], fontsize=9)
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
    reviewed_at, local, review, upstream = read_scores()
    with tempfile.TemporaryDirectory(prefix="agentcad-source-chart-") as temporary:
        for theme in THEMES:
            destination = HERE / f"source-capability-{theme}.svg"
            target = Path(temporary) / destination.name if args.check else destination
            preview = args.preview_dir / f"source-capability-{theme}.png" if args.preview_dir else None
            draw(theme, reviewed_at, local, review, upstream, target, preview)
            if args.check and target.read_bytes() != destination.read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"Regenerate {destination}")
    print("Assessment and upstream rows read; light/dark figures " + ("match" if args.check else "generated"))


if __name__ == "__main__":
    main()
