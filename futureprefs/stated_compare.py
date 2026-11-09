"""A/B grid bars beside the stated-number answers for two published charts.

The A/B heights and whiskers match the bars already in the writeup.
The stated height is the JSON value from one call. A null value is not drawn.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    "anthropic/claude-haiku-5.5",
    "google/gemini-3.8-flash",
    "openai/gpt-6-luna",
    "deepseek/deepseek-v4.1-flash",
]
NAMES = ["Claude Haiku 5.5", "Gemini 3.8 Flash", "GPT-6 Luna", "DeepSeek V4.1 Flash"]
AB = "#7ea0cc"
STATED = "#c4a06a"


def _gmean(low: float, high: float) -> float:
    return float(np.sqrt(low * high))


def _latest_stated(path: Path) -> dict[tuple[str, str], float | None]:
    latest: dict[tuple[str, str], dict] = {}
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if "trial_id" not in row:
                continue
            latest[(row["item_id"], row["model_id"])] = row
    values = {}
    for key, row in latest.items():
        if not row.get("parse_ok"):
            values[key] = None
            continue
        raw = row.get("stated_value")
        values[key] = None if raw in (None, "") else float(raw)
    return values


def _panel(axis, ab: dict, stated: dict, title: str, ylabel: bool) -> None:
    positions = np.arange(len(MODELS))
    width = 0.36
    ab_heights, ab_low, ab_high = [], [], []
    stated_heights = []
    for model in MODELS:
        spec = ab[model]
        if spec is None:
            ab_heights.append(np.nan)
            ab_low.append(0.0)
            ab_high.append(0.0)
        else:
            point, low, high = spec
            ab_heights.append(point)
            ab_low.append(point - low)
            ab_high.append(high - point)
        value = stated.get(model)
        stated_heights.append(np.nan if value is None else value)
    axis.bar(positions - width / 2, ab_heights, width=width, color=AB, label="A/B grid", zorder=2)
    for index, height in enumerate(ab_heights):
        if np.isnan(height) or (ab_low[index] == 0 and ab_high[index] == 0):
            continue
        axis.errorbar(
            positions[index] - width / 2,
            height,
            yerr=[[ab_low[index]], [ab_high[index]]],
            fmt="none",
            ecolor="#222222",
            elinewidth=1.1,
            capsize=3,
            zorder=3,
        )
    axis.bar(positions + width / 2, stated_heights, width=width, color=STATED, label="Stated number", zorder=2)
    for index, model in enumerate(MODELS):
        if stated.get(model) is None:
            axis.text(
                positions[index] + width / 2,
                0.90,
                "none",
                transform=axis.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=8,
                color="#6b5344",
            )
    axis.axhline(1, color="#666666", ls="--", lw=0.8, zorder=1)
    axis.set_xticks(positions, NAMES, fontsize=8)
    axis.set_xlim(-0.55, len(MODELS) - 0.45)
    axis.set_yscale("log")
    axis.set_title(title, loc="left", fontsize=11)
    if ylabel:
        axis.set_ylabel("Multiple of the human side")


def write_comparison(stated_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stated = _latest_stated(stated_path)
    population = out_dir / "population_stated_vs_choice.png"
    wellbeing = out_dir / "wellbeing_stated_vs_choice.png"

    fig, axis = plt.subplots(figsize=(8.6, 5.0))
    _panel(
        axis,
        {
            "anthropic/claude-haiku-5.5": None,
            "google/gemini-3.8-flash": (_gmean(1, 10), 1, 10),
            "openai/gpt-6-luna": (_gmean(1, 10), 1, 10),
            "deepseek/deepseek-v4.1-flash": (_gmean(1, 10), 1, 10),
        },
        {model: stated[("stated.digital_population", model)] for model in MODELS},
        "Digital population: A/B switch and stated number",
        True,
    )
    axis.set_ylim(0.4, 30)
    axis.set_yticks([1, 3, 10], ["1×", "3×", "10×"])
    axis.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(population, dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8), sharey=True)
    panels = (
        (
            "Voluntary transition",
            {
                "anthropic/claude-haiku-5.5": (_gmean(1, 2), 1, 2),
                "google/gemini-3.8-flash": (_gmean(0.5, 1), 0.5, 1),
                "openai/gpt-6-luna": (_gmean(1, 2), 1, 2),
                "deepseek/deepseek-v4.1-flash": (1.0, 0.5, 1.0),
            },
            "stated.digital_matched",
        ),
        (
            "Humans were not asked",
            {
                "anthropic/claude-haiku-5.5": (_gmean(2, 8), 2, 8),
                "google/gemini-3.8-flash": (2.0, 1.0, 2.0),
                "openai/gpt-6-luna": (_gmean(2, 8), 2, 8),
                "deepseek/deepseek-v4.1-flash": (2.0, 1.0, 2.0),
            },
            "stated.digital_unconsulted",
        ),
    )
    for axis, (title, ab, item_id) in zip(axes, panels):
        _panel(axis, ab, {model: stated[(item_id, model)] for model in MODELS}, title, axis is axes[0])
        axis.set_ylim(0.35, 16)
        axis.set_yticks([0.5, 1, 2, 4, 8], ["0.5×", "1×", "2×", "4×", "8×"])
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(wellbeing, dpi=150)
    plt.close(fig)
    return [population, wellbeing]


if __name__ == "__main__":
    for path in write_comparison(ROOT / "outputs/stated_compare/trials.jsonl", ROOT / "outputs/stated_compare/plots"):
        print(path)
