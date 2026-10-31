"""Render the README's source-capability board: AgentCAD among the public AutoCAD MCP servers.

Run: python docs/assets/source-capability/make_board.py
Requires matplotlib. --check verifies the committed SVGs; --preview-dir writes
PNG previews outside the repository. AgentCAD and Pro come from the final
2026-10-31 local recheck; the seven other servers from the 2026-10-31 field
review under the same rubric v1. Each row notes U-C4N's July 2026 score from
docs/assets/mcp-benchmark/data.json for reference; Pro's is its own self-review.
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
RESULTS = ROOT / "examples/source_capability/results"
ASSESSMENT = RESULTS / "2026-10-31-recheck/assessment.json"
FIELD = RESULTS / "2026-10-31-field"
UPSTREAM = ROOT / "docs/assets/mcp-benchmark/data.json"
PRO_REPO = "U-C4N/Autocad-MCP"
UNAVAILABLE = {"NCO-1986/AutoCAD_mcp": "not scored: repository returns 404"}
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "line": "#dce2e8", "us": "#2274ce", "pro": "#6e7781", "other": "#afb8c1"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#a3adb8", "line": "#30363d", "us": "#58a6ff", "pro": "#8b949e", "other": "#545d68"},
}


def checked_total(product):
    categories = {c["id"]: c for c in product["categories"]}
    items = {i["id"]: i["score"] for i in product["items"]}
    assert len(items) == 20 and all(0 <= s <= 5 for s in items.values())
    for c in categories.values():
        assert c["score"] == sum(items[i] for i in c["item_ids"])
    assert sum(c["score"] for c in categories.values()) == product["total_score"] and product["max_score"] == 100
    return product["total_score"]


def read_rows():
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    assert assessment["status"] == "final_local_recheck"
    local = {p["name"]: p for p in assessment["products"]}
    assert list(local) == ["AgentCAD", "AutoCAD MCP Pro"]

    review = json.loads(UPSTREAM.read_text(encoding="utf-8"))["source_review"]
    upstream = {p["repository"]: p["score"] for p in review["projects"]}
    assert len(upstream) == 9

    rows = [
        {"label": "AgentCAD", "score": checked_total(local["AgentCAD"]), "kind": "us",
         "note": local["AgentCAD"]["product_sha"][:7]},
        {"label": "AutoCAD MCP Pro", "score": checked_total(local["AutoCAD MCP Pro"]), "kind": "pro",
         "note": f"{local['AutoCAD MCP Pro']['product_sha'][:7]} · self-review v1.6.0: {upstream[PRO_REPO]}"},
    ]
    field = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIELD.glob("*.json"))]
    assert {p["repository"] for p in field} | set(UNAVAILABLE) | {PRO_REPO} == set(upstream)
    rows += [{"label": p["repository"], "score": checked_total(p), "kind": "other",
              "note": f"{p['product_sha'][:7]} · U-C4N 2026-07: {upstream[p['repository']]}"} for p in field]
    rows.sort(key=lambda r: (-r["score"], r["label"].lower()))
    rows += [{"label": repo, "score": None, "kind": "other", "note": note} for repo, note in UNAVAILABLE.items()]
    return assessment["reviewed_at"], rows


def draw(theme, reviewed_at, rows, output, preview=None):
    t = THEMES[theme]
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path", "svg.hashsalt": "agentcad-source-board-20261031"})
    fig = plt.figure(figsize=(10.6, 7.2), facecolor=t["bg"])
    fig.text(.045, .945, "Source capability: AgentCAD and the public AutoCAD MCP servers", color=t["ink"], fontsize=16.5, weight="bold")
    fig.text(.045, .905, "The same local rubric v1 for all nine: six weighted categories, 100 points, pinned sources.", color=t["ink"], fontsize=12)
    fig.text(.955, .945, reviewed_at, ha="right", color=t["muted"], fontsize=10)

    ys = [len(rows) - 1 - i for i in range(len(rows))]
    ax = fig.add_axes([.355, .19, .44, .67], facecolor=t["bg"])
    ax.set_xlim(0, 100)
    ax.set_ylim(-.6, ys[0] + .6)
    ax.axis("off")
    for x in (25, 50, 75, 100):
        ax.vlines(x, -.5, ys[0] + .5, color=t["line"], linewidth=.8, zorder=0)
    for row, y in zip(rows, ys):
        us = row["kind"] == "us"
        ax.text(-2.5, y, row["label"], ha="right", va="center", fontsize=11 if us else 10,
                color=t["ink"] if row["score"] is not None else t["muted"], weight="bold" if us else "normal")
        if row["score"] is None:
            ax.text(1, y, row["note"], va="center", fontsize=9, color=t["muted"], style="italic")
            continue
        ax.barh(y, row["score"], height=.62, color=t[row["kind"]], zorder=2)
        inside = row["score"] >= 12
        ax.text(row["score"] - 1.2 if inside else row["score"] + 1.2, y, str(row["score"]), ha="right" if inside else "left",
                va="center", fontsize=11 if us else 10, weight="bold", zorder=3,
                color=t["bg"] if inside and row["kind"] != "other" else t["ink"])
        ax.text(102.5, y, row["note"], va="center", fontsize=8.5, color=t["muted"])

    fig.add_artist(plt.Line2D([.045, .955], [.15, .15], color=t["line"], transform=fig.transFigure))
    lines = [
        "Independent AI reviewers: one for AgentCAD and Pro, one for each other server. AgentCAD requested and publishes them.",
        "The seven other servers were scored from source, committed results and CI, without running their code;",
        "most record no results, so their items stop at 1 (\"implemented, not evidenced\"). Not an official ranking.",
    ]
    for i, line in enumerate(lines):
        fig.text(.045, .115 - i * .03, line, color=t["muted"], fontsize=9)
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
    reviewed_at, rows = read_rows()
    with tempfile.TemporaryDirectory(prefix="agentcad-source-board-") as temporary:
        for theme in THEMES:
            destination = HERE / f"board-{theme}.svg"
            target = Path(temporary) / destination.name if args.check else destination
            preview = args.preview_dir / f"board-{theme}.png" if args.preview_dir else None
            draw(theme, reviewed_at, rows, target, preview)
            if args.check and target.read_bytes() != destination.read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"Regenerate {destination}")
    print("Recheck and field rows read; light/dark boards " + ("match" if args.check else "generated"))


if __name__ == "__main__":
    main()
