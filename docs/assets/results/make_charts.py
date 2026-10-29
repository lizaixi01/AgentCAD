"""Draw the README's results-at-a-glance chart (light and dark SVG) from the recorded experiments.

    python docs/assets/results/make_charts.py      (needs matplotlib)

Every number comes from a report in docs/ or examples/; the source is noted next to each row.
"""
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).parent
plt.rcParams.update({"svg.fonttype": "path", "font.family": "DejaVu Sans", "font.size": 10})

# Minutes to a correct result (lower is better): (task, alternative, AgentCAD, alternative)
SPEED = [
    ("Five-round revision with undo", "vs. writing code · Claude Code", 4.1, 12.9),        # comparison-claude-code.md
    ("Edit a real AutoCAD DWG", "vs. writing code · Claude Code", 2.9, 6.0),              # comparison-claude-code.md
    ("Clean up layers", "vs. AutoCAD MCP Pro · Codex", 57.24 / 60, 104.13 / 60),           # comparison-autocad-mcp-pro.md
    ("Dimension a part", "vs. AutoCAD MCP Pro · Codex", 110.60 / 60, 192.52 / 60),         # comparison-autocad-mcp-pro.md
    ("Edit native DWG, AutoCAD 2027 open", "vs. AutoCAD MCP Pro · Codex", 177.11 / 60, 339.83 / 60),  # native-dwg, 9 pairs
]
# Runs that fully succeeded: (task, alternative, AgentCAD ok, alternative ok, runs)
RELIABILITY = [
    ("Undo across sessions (five-round revision)", "vs. AutoCAD MCP Pro · Codex", 3, 0, 3),  # comparison-autocad-mcp-pro.md
    ("Native DWG, end to end in AutoCAD 2027", "vs. AutoCAD MCP Pro · Codex", 11, 10, 12),   # comparison-native-dwg.md
    ("12 drafting tasks", "vs. writing code · Claude Code", 24, 23, 24),                      # comparison-claude-code.md
]
# BenchCAD Vision2Code, 100 tasks, mean voxel IoU (both through AgentCAD)        # examples/benchcad/README.md
BENCH = [("Codex · gpt-6.1-sol", 0.872), ("Claude Code · Opus 5.5", 0.766)]

THEMES = {
    "light": dict(bg="#FFFFFF", ink="#1F2328", muted="#59636E", grid="#E4E7EB", us="#08776A", alt="#ABB1B8"),
    "dark": dict(bg="#0D1117", ink="#E6EDF3", muted="#9198A1", grid="#262C33", us="#1FCFB0", alt="#5A626B"),
}


def style(ax, t):
    ax.set_facecolor(t["bg"])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["muted"], length=0)
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def pair_rows(ax, rows, t, fmt, xmax):
    """Two thin bars per row: AgentCAD on top, the alternative below; value labels at the bar ends."""
    h, gap = 0.30, 0.04
    for i, (task, alt, a, b) in enumerate(rows):
        y = -i * 1.25
        ax.barh(y + (h + gap) / 2, a, height=h, color=t["us"])
        ax.barh(y - (h + gap) / 2, b, height=h, color=t["alt"])
        ax.text(xmax * 0.008 + a, y + (h + gap) / 2, fmt(a), va="center", color=t["ink"], fontsize=9, fontweight="bold")
        ax.text(xmax * 0.008 + b, y - (h + gap) / 2, fmt(b), va="center", color=t["muted"], fontsize=9)
        ax.text(-xmax * 0.02, y + 0.12, task, ha="right", va="center", color=t["ink"], fontsize=9.5)
        ax.text(-xmax * 0.02, y - 0.24, alt, ha="right", va="center", color=t["muted"], fontsize=8.5)
    ax.set_xlim(0, xmax)
    ax.set_ylim(-(len(rows) - 1) * 1.25 - 0.7, 0.7)
    ax.set_yticks([])


def draw(theme):
    t = THEMES[theme]
    fig = plt.figure(figsize=(9.2, 7.9), facecolor=t["bg"])
    gs = fig.add_gridspec(3, 1, height_ratios=[5, 3, 2], hspace=0.62, left=0.37, right=0.96, top=0.855, bottom=0.1)
    fig.text(0.02, 0.965, "AgentCAD vs. the alternatives, same agent and model", color=t["ink"], fontsize=13,
             fontweight="bold")
    # legend, as text with colored keys
    fig.patches.append(plt.Rectangle((0.02, 0.922), 0.014, 0.014, color=t["us"], transform=fig.transFigure))
    fig.text(0.04, 0.923, "Agent + AgentCAD", color=t["ink"], fontsize=9.5)
    fig.patches.append(plt.Rectangle((0.20, 0.922), 0.014, 0.014, color=t["alt"], transform=fig.transFigure))
    fig.text(0.22, 0.923, "Same agent, the alternative named on each row", color=t["ink"], fontsize=9.5)

    ax = fig.add_subplot(gs[0])
    style(ax, t)
    pair_rows(ax, SPEED, t, lambda v: f"{v:.1f} min", 14.5)
    ax.set_title("Minutes to a correct result (lower is better)", loc="left", color=t["ink"], fontsize=10.5,
                 fontweight="bold", x=-0.555)

    ax = fig.add_subplot(gs[1])
    style(ax, t)
    rows = [(task, alt, a / n, b / n) for task, alt, a, b, n in RELIABILITY]
    pair_rows(ax, rows, t, lambda v: "", 1.18)
    for i, (_, _, a, b, n) in enumerate(RELIABILITY):
        y = -i * 1.25
        ax.text(a / n + 0.012, y + 0.17, f"{a}/{n}", va="center", color=t["ink"], fontsize=9, fontweight="bold")
        ax.text(b / n + 0.012, y - 0.17, f"{b}/{n}", va="center", color=t["muted"], fontsize=9)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xticklabels(["0%", "50%", "100%"])
    ax.set_title("Runs that fully succeeded", loc="left", color=t["ink"], fontsize=10.5, fontweight="bold", x=-0.555)

    ax = fig.add_subplot(gs[2])
    style(ax, t)
    for i, (who, v) in enumerate(BENCH):
        ax.barh(-i * 0.8, v, height=0.34, color=t["us"])
        ax.text(v + 0.012, -i * 0.8, f"{v:.3f}", va="center", color=t["ink"], fontsize=9, fontweight="bold")
        ax.text(-0.02, -i * 0.8, who, ha="right", va="center", color=t["ink"], fontsize=9.5)
    ax.set_xlim(0, 1.18)
    ax.set_ylim(-1.3, 0.5)
    ax.set_yticks([])
    ax.set_xticks([0, 0.5, 1])
    ax.text(-0.555, -0.5, "Both agents build through AgentCAD · self-run, 100 sampled tasks · "
            "not comparable to the BenchCAD leaderboard", transform=ax.transAxes, color=t["muted"], fontsize=8.5)
    ax.set_title("3D: rebuild a part from 4 views, BenchCAD Vision2Code (mean IoU, 1 = exact)", loc="left",
                 color=t["ink"], fontsize=10.5, fontweight="bold", x=-0.555)
    fig.savefig(OUT / f"results-{theme}.svg", facecolor=t["bg"])
    plt.close(fig)


for theme in THEMES:
    draw(theme)
print("ok")
