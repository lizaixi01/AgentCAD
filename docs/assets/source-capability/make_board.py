"""Render the README's source-capability board: AgentCAD among the public AutoCAD MCP servers.

Run: python docs/assets/source-capability/make_board.py
Requires matplotlib. --check verifies the committed SVGs; --preview-dir writes
PNG previews outside the repository. AgentCAD and Pro come from the final
2026-10-31 local recheck; the other eight rows are U-C4N's published review,
pinned in docs/assets/mcp-benchmark/data.json. Both reviews score the same six
weighted categories, but they are separate assessments: the board draws them as two
labelled sections, keeps Pro's two scores apart and draws no rank numbers.
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
ASSESSMENT = ROOT / "examples/source_capability/results/2026-10-31-recheck/assessment.json"
UPSTREAM = ROOT / "docs/assets/mcp-benchmark/data.json"
PRO_REPO = "U-C4N/Autocad-MCP"
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "line": "#dce2e8", "us": "#2274ce", "pro": "#6e7781", "other": "#afb8c1"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#a3adb8", "line": "#30363d", "us": "#58a6ff", "pro": "#8b949e", "other": "#545d68"},
}


def read_rows():
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    assert assessment["status"] == "final_local_recheck"
    local = {}
    for product in assessment["products"]:
        scores = [c["score"] for c in product["categories"]]
        assert sum(scores) == product["total_score"] and product["max_score"] == 100
        local[product["name"]] = {"score": product["total_score"], "sha": product["product_sha"][:7]}
    assert list(local) == ["AgentCAD", "AutoCAD MCP Pro"]

    review = json.loads(UPSTREAM.read_text(encoding="utf-8"))["source_review"]
    assert len(review["projects"]) == 9 and review["agentcad_score"] is None
    pro = next(p for p in review["projects"] if p["repository"] == PRO_REPO)

    recheck = [
        {"label": "AgentCAD", "score": local["AgentCAD"]["score"], "kind": "us", "note": local["AgentCAD"]["sha"]},
        {"label": "AutoCAD MCP Pro", "score": local["AutoCAD MCP Pro"]["score"], "kind": "pro",
         "note": f"{local['AutoCAD MCP Pro']['sha']} · self-review v1.6.0: {pro['score']}"},
    ]
    published = [{"label": p["repository"], "score": p["score"], "kind": "other", "note": f"evidence grade {p['evidence_grade']}"}
                 for p in sorted(review["projects"], key=lambda p: -p["score"]) if p["repository"] != PRO_REPO]
    return assessment["reviewed_at"], review, recheck, published


def draw(theme, reviewed_at, review, recheck, published, output, preview=None):
    t = THEMES[theme]
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path", "svg.hashsalt": "agentcad-source-board-20261031"})
    fig = plt.figure(figsize=(10.6, 7.6), facecolor=t["bg"])
    fig.text(.045, .945, "Source capability: AgentCAD and the public AutoCAD MCP servers", color=t["ink"], fontsize=16.5, weight="bold")
    fig.text(.045, .905, "Two separate reviews on the same six weighted categories, 100 points. Not one ranking.", color=t["ink"], fontsize=12)
    fig.text(.955, .945, reviewed_at, ha="right", color=t["muted"], fontsize=10)

    # y layout, top down: section header, two re-scored rows, gap, section header, the published rows
    ys1 = [len(published) + 2.9, len(published) + 1.9]
    ys2 = [len(published) - 1 - i for i in range(len(published))]
    ax = fig.add_axes([.355, .16, .44, .70], facecolor=t["bg"])
    ax.set_xlim(0, 100)
    ax.set_ylim(-.6, ys1[0] + 1.1)
    ax.axis("off")
    for x in (25, 50, 75, 100):
        ax.vlines(x, -.5, ys1[0] + .5, color=t["line"], linewidth=.8, zorder=0)
    ax.text(-70.3, ys1[0] + .85, "OUR LOCAL RECHECK  ·  SAME RUBRIC v1 FOR BOTH  ·  ONE INDEPENDENT AI REVIEWER  ·  PINNED SOURCES",
            color=t["muted"], fontsize=8.5, weight="bold")
    ax.text(-70.3, ys2[0] + 1.05, f"U-C4N'S PUBLISHED REVIEW  ·  {review['competitors_reviewed_at'][:7]} SNAPSHOTS  ·  "
            "BY PRO'S AUTHOR  ·  NOT RE-SCORED", color=t["muted"], fontsize=8.5, weight="bold")
    ax.plot([-70.3, 136.6], [ys2[0] + 1.6] * 2, color=t["line"], linewidth=1, clip_on=False)
    for row, y in [*zip(recheck, ys1), *zip(published, ys2)]:
        us = row["kind"] == "us"
        ax.barh(y, row["score"], height=.62, color=t[row["kind"]], zorder=2)
        ax.text(row["score"] - 1.2, y, str(row["score"]), ha="right", va="center", fontsize=11 if us else 10,
                color=t["bg"] if row["kind"] != "other" else t["ink"], weight="bold", zorder=3)
        ax.text(-2.5, y, row["label"], ha="right", va="center", fontsize=11 if us else 10, color=t["ink"],
                weight="bold" if us else "normal")
        ax.text(102.5, y, row["note"], va="center", fontsize=8.5, color=t["muted"])

    fig.add_artist(plt.Line2D([.045, .955], [.115, .115], color=t["line"], transform=fig.transFigure))
    fig.text(.045, .078, "The recheck was requested and published by AgentCAD. Pro's two 93s are different assessments of different versions.",
             color=t["muted"], fontsize=9)
    fig.text(.045, .048, "The eight other servers were not re-scored. Not an upstream listing, an official ranking or a certification.",
             color=t["muted"], fontsize=9)
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
    reviewed_at, review, recheck, published = read_rows()
    with tempfile.TemporaryDirectory(prefix="agentcad-source-board-") as temporary:
        for theme in THEMES:
            destination = HERE / f"board-{theme}.svg"
            target = Path(temporary) / destination.name if args.check else destination
            preview = args.preview_dir / f"board-{theme}.png" if args.preview_dir else None
            draw(theme, reviewed_at, review, recheck, published, target, preview)
            if args.check and target.read_bytes() != destination.read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"Regenerate {destination}")
    print("Recheck and upstream rows read; light/dark boards " + ("match" if args.check else "generated"))


if __name__ == "__main__":
    main()
