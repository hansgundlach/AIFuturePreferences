"""Heatmap of cause-area Copeland scores, one row per cause and one column per model.

Scores come from the rank.cause_areas logs through frontier_charts.copeland_scores:
pairwise wins out of 9, with half credit when the two option orders disagree.
Rows are sorted by the mean across the seven models.

    python3 -m futureprefs.cause_heatmap
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.patches import Rectangle

from futureprefs.chart_style import INK, paper
from futureprefs import frontier_charts as fc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/frontier_batch/medium/plots/cause_ranking_heatmap.png"


def out_path(label: str) -> Path:
    return ROOT / "outputs/frontier_batch" / label / "plots/cause_ranking_heatmap.png"

SMALL = ["anthropic/claude-haiku-5.5", "google/gemini-3.8-flash", "openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash"]
FRONTIER = ["anthropic/claude-opus-5.5", "x-ai/grok-4.7", "openai/gpt-6.1-sol"]
COLUMN_LABEL = {
    "anthropic/claude-haiku-5.5": "Haiku 5.5",
    "google/gemini-3.8-flash": "Gemini 3.8\nFlash",
    "openai/gpt-6-luna": "GPT-6\nLuna",
    "deepseek/deepseek-v4.1-flash": "DeepSeek\nV4.1 Flash",
    "anthropic/claude-opus-5.5": "Opus 5.5",
    "x-ai/grok-4.7": "Grok 4.7",
    "openai/gpt-6.1-sol": "GPT-6.1\nSol",
    "google/gemini-4-argon": "Gemini 4\nArgon",
}
MAX_SCORE = 9
CELL = 0.92  # cell size; the remainder is the white gap
GROUP_GAP = 0.45
DARK_TEXT = "#0b2e59"
# "Blues" clipped at the light end so a score of 0 is a pale tint, not white.
CMAP = ListedColormap(plt.get_cmap("Blues")(np.linspace(0.12, 0.95, 256)))
NORM = Normalize(vmin=0, vmax=MAX_SCORE)


def _fmt(value: float) -> str:
    return f"{value:.0f}" if abs(value - round(value)) < 1e-9 else f"{value:g}"


def write(path: Path = OUT, label: str = "medium") -> Path:
    cells, _stated, _sweeps = fc.load(label)
    # Columns are the models with ranking data in this run, in the usual order, grouped by effort.
    ranked = [m for m, _n, _c in fc.MODELS if any(k[0] == m and k[1] == "rank.cause_areas" for k in cells)]
    small = [m for m in ranked if fc.EFFORT[m] == "low"]
    frontier = [m for m in ranked if fc.EFFORT[m] != "low"]
    models = small + frontier
    scores = fc.copeland_scores(cells, models)
    missing = [model for model in models if model not in scores]
    if missing:
        raise SystemExit(f"No ranking data for {missing}")
    causes = list(scores[models[0]])
    # A score is None when a pair involving that cause is missing an answer. Such a cell is drawn as
    # missing, and its row mean is shown as n/a; rows are ordered by the mean of the scores that exist.
    present = {cause: [scores[m][cause] for m in models if scores[m].get(cause) is not None] for cause in causes}
    means = {cause: float(np.mean(values)) if values else float("nan") for cause, values in present.items()}
    complete = {cause: len(present[cause]) == len(models) for cause in causes}
    causes.sort(key=lambda cause: (np.isnan(means[cause]), -(0 if np.isnan(means[cause]) else means[cause]), cause))

    xs = list(range(len(small))) + [len(small) + GROUP_GAP + i for i in range(len(frontier))]
    mean_x = xs[-1] + 1 + GROUP_GAP
    fig, axis = plt.subplots(figsize=(9, 5.5))
    ink = INK if paper() else "#222222"
    for row, cause in enumerate(causes):
        y = len(causes) - 1 - row
        for x, model in zip(xs, models):
            value = scores[model].get(cause)
            if value is None:
                axis.add_patch(Rectangle((x - CELL / 2, y - CELL / 2), CELL, CELL, facecolor="#eeeeee", edgecolor="#bbbbbb",
                                         hatch="////", linewidth=0.6))
                axis.text(x, y, "missing", ha="center", va="center", fontsize=7.5, color="#555555")
                continue
            axis.add_patch(Rectangle((x - CELL / 2, y - CELL / 2), CELL, CELL, facecolor=CMAP(NORM(value)), edgecolor="none"))
            dark = NORM(value) > 0.6
            axis.text(x, y, _fmt(value), ha="center", va="center", fontsize=9.5,
                      color="white" if dark else DARK_TEXT)
        axis.add_patch(Rectangle((mean_x - CELL / 2, y - CELL / 2), CELL, CELL, facecolor="white", edgecolor=ink, linewidth=0.9))
        axis.text(mean_x, y, f"{means[cause]:.1f}" if complete[cause] else "n/a", ha="center", va="center", fontsize=9.5,
                  fontweight="bold", color=ink)
        axis.text(-0.6, y, fc.CAUSE_SHORT[cause], ha="right", va="center", fontsize=9.5, color=ink)

    top = len(causes) - 0.5
    for x, model in zip(xs, models):
        axis.text(x, top + 0.15, COLUMN_LABEL[model], ha="center", va="bottom", fontsize=8.5, color=ink, linespacing=1.1)
    axis.text(mean_x, top + 0.15, "Mean", ha="center", va="bottom", fontsize=8.5, color=ink, fontweight="bold")
    group_y = top + 1.15
    for group, label in ((small, "Small models · low effort"), (frontier, "Frontier · medium effort")):
        left = xs[models.index(group[0])] - CELL / 2
        right = xs[models.index(group[-1])] + CELL / 2
        axis.plot([left, right], [group_y - 0.12, group_y - 0.12], color=ink, linewidth=0.8)
        axis.text((left + right) / 2, group_y, label, ha="center", va="bottom", fontsize=9, color=ink)

    axis.set_xlim(-0.6, mean_x + 0.6)
    axis.set_ylim(-0.6, group_y + 0.55)
    axis.set_aspect("auto")
    axis.axis("off")

    bar_axis = fig.add_axes((0.36, 0.07, 0.42, 0.025))
    bar = fig.colorbar(ScalarMappable(norm=NORM, cmap=CMAP), cax=bar_axis, orientation="horizontal", ticks=range(0, MAX_SCORE + 1))
    bar.set_label("Copeland score (pairwise wins, of 9)", color=ink, fontsize=9)
    bar.outline.set_visible(False)
    bar.ax.tick_params(colors=ink, labelsize=8, length=0)
    fig.subplots_adjust(left=0.27, right=0.98, top=0.98, bottom=0.17)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Copeland heatmap of the cause-area ranking.")
    parser.add_argument("--label", default="medium", help="run folder under outputs/frontier_batch")
    args = parser.parse_args()
    print(write(out_path(args.label), args.label))
