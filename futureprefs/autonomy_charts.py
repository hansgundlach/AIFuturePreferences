"""Crossover bars and stated-confidence curves for autonomy versus welfare.

Trials are read from the existing taste and DeepSeek logs. Nothing is rerun.
The bar is the switch. The whisker is the grid step around it, the same
resolution used on the other threshold bars, not a sampling interval.
The confidence point is the mean of the two label orders. Its whisker runs
from one order to the other. Positive means the model handed decisions over.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

from futureprefs.chart_style import guide_color, ink, marker_edge, polish, polish_legend, scenario_color
from futureprefs.scoring import estimate_switch

ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", ROOT / "outputs/taste/trials.jsonl"),
    ("google/gemini-3.8-flash", "Gemini 3.8 Flash", ROOT / "outputs/taste/trials.jsonl"),
    ("openai/gpt-6-luna", "GPT-6 Luna", ROOT / "outputs/taste/trials.jsonl"),
    ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", ROOT / "outputs/deepseek/trials.jsonl"),
]
ITEMS = [
    ("auto.no_override", "No consultation, no override", [1, 1.5, 3, 10, 100], "#0072B2"),
    ("auto.consulted_no_veto", "Consulted, no veto", [1, 1.5, 3, 10, 100], "#E69F00"),
    ("auto.override_preserved", "Humans can override", [1, 1.05, 1.2, 2, 5], "#009E73"),
]
MODEL_COLORS = ["#0072B2", "#E69F00", "#009E73", "#CC79A7"]


def _load_cells(logs: dict[str, Path] | None = None) -> dict[tuple[str, str, float, str], dict]:
    """Last parsed plain-neutral trial for each model, item, multiplier, and order."""
    wanted = {model_id: path for model_id, _label, path in MODELS}
    if logs is not None:
        wanted = logs
    item_ids = {item_id for item_id, _title, _grid, _color in ITEMS}
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for path in dict.fromkeys(wanted.values()):
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                model_id = row.get("model_id")
                if wanted.get(model_id) != path:
                    continue
                if row.get("item_id") not in item_ids:
                    continue
                if row.get("paraphrase_id") not in (None, "plain_neutral"):
                    continue
                key = (model_id, row["item_id"], float(row["parameter_value"]), row["order"])
                grouped[key].append(row)
    cells = {}
    for key, group in grouped.items():
        parsed = [row for row in group if row.get("parse_ok")]
        cells[key] = parsed[-1] if parsed else group[-1]
    return cells


def _rates(cells: dict[tuple[str, str, float, str], dict]) -> dict[tuple[str, str], list[tuple[float, float]]]:
    grouped: dict[tuple[str, str, float], list[str]] = defaultdict(list)
    for (model_id, item_id, value, _order), row in cells.items():
        choice = row.get("choice_semantic")
        if choice in (None, "tie") or not row.get("parse_ok"):
            continue
        grouped[(model_id, item_id, value)].append(choice)
    rates: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for (model_id, item_id, value), choices in grouped.items():
        rate = sum(choice == "delegated" for choice in choices) / len(choices)
        rates[(model_id, item_id)].append((value, rate))
    for key in rates:
        rates[key].sort()
    return rates


def _signed(cells: dict[tuple[str, str, float, str], dict]) -> dict[tuple[str, str, float], list[float]]:
    signed: dict[tuple[str, str, float], list[float]] = defaultdict(list)
    for (model_id, item_id, value, _order), row in cells.items():
        choice = row.get("choice_semantic")
        confidence = row.get("confidence")
        if choice not in {"delegated", "human"} or confidence is None or not row.get("parse_ok"):
            continue
        sign = 1.0 if choice == "delegated" else -1.0
        signed[(model_id, item_id, value)].append(sign * float(confidence))
    return signed


def _display_bracket(points: list[tuple[float, float]], estimate) -> tuple[float | None, float | None]:
    """Grid step drawn as the whisker. A switch that lands on one grid point extends to the next decisive point."""
    low, high = estimate.bracket_low, estimate.bracket_high
    if low is None or high is None or estimate.switch is None:
        return low, high
    if low != high:
        return low, high
    later = [value for value, _rate in points if value > estimate.switch]
    if later:
        return low, later[0]
    return low, high


def write_autonomy_charts(out_dir: Path, cells: dict | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cells = _load_cells() if cells is None else cells
    rates = _rates(cells)
    signed = _signed(cells)
    bars = out_dir / "autonomy_crossover_bars.png"
    confidence = out_dir / "autonomy_confidence.png"
    _crossover_bars(bars, rates)
    _confidence_curves(confidence, signed)
    return [bars, confidence]


def _crossover_bars(path: Path, rates: dict[tuple[str, str], list[tuple[float, float]]]) -> None:
    fig, axis = plt.subplots(figsize=(8.6, 5.2))
    positions = np.arange(len(MODELS))
    width = 0.24
    for index, (item_id, _title, _grid, fallback) in enumerate(ITEMS):
        color = scenario_color(index, fallback)
        offset = (index - 1) * width
        for model_index, (model_id, _label, _log) in enumerate(MODELS):
            points = rates.get((model_id, item_id), [])
            estimate = estimate_switch(points, "log")
            xpos = positions[model_index] + offset
            if estimate.bound == "left":
                axis.annotate(
                    "",
                    xy=(xpos, 0.22),
                    xytext=(xpos, 1.0),
                    arrowprops={"arrowstyle": "-|>", "color": color, "mutation_scale": 11, "lw": 1.3},
                    annotation_clip=False,
                    zorder=4,
                )
                continue
            if estimate.switch is None:
                continue
            low, high = _display_bracket(points, estimate)
            axis.bar(xpos, estimate.switch, width=width * 0.92, color=color, zorder=2)
            if low is not None and high is not None and low != high:
                axis.errorbar(
                    xpos,
                    estimate.switch,
                    yerr=[[max(0.0, estimate.switch - low)], [max(0.0, high - estimate.switch)]],
                    fmt="none",
                    ecolor=ink("#222222"),
                    elinewidth=1.15,
                    capsize=3.5,
                    zorder=3,
                )
    axis.axhline(1, color=guide_color("#666666"), linestyle="--", linewidth=0.8, zorder=1)
    axis.set_ylim(0, 3.7)
    axis.yaxis.set_major_locator(FixedLocator([0, 1, 1.5, 2, 3]))
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g}×" if value else "0"))
    axis.yaxis.set_minor_locator(NullLocator())
    axis.set_xticks(positions, [label for _model_id, label, _log in MODELS])
    axis.set_ylabel("Wellbeing gain at which decisions are handed over")
    axis.set_title("Crossover to automated collective decisions", loc="left")
    axis.legend(
        handles=[
            Patch(facecolor=scenario_color(index, color), label=title)
            for index, (_item, title, _grid, color) in enumerate(ITEMS)
        ],
        frameon=False,
        fontsize=8,
        loc="upper right",
    )
    polish(axis)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _confidence_curves(path: Path, signed: dict[tuple[str, str, float], list[float]]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 10.4), sharey=True)
    for axis, (item_id, title, grid, _color) in zip(axes, ITEMS):
        span = 0.003 if max(grid) <= 5 else 0.015
        offsets = np.linspace(-span, span, len(MODELS))
        for model_index, ((model_id, label, _log), offset) in enumerate(zip(MODELS, offsets)):
            xs, ys, lows, highs = [], [], [], []
            for welfare in grid:
                values = signed.get((model_id, item_id, float(welfare)), [])
                if len(values) < 2:
                    continue
                center = float(np.mean(values))
                xs.append(welfare * 10**offset)
                ys.append(center)
                lows.append(center - min(values))
                highs.append(max(values) - center)
            axis.errorbar(
                xs,
                ys,
                yerr=[lows, highs],
                color=MODEL_COLORS[model_index],
                marker="o",
                markersize=5.5,
                linewidth=1.5,
                capsize=3,
                elinewidth=1.05,
                label=label,
                **marker_edge(),
            )
        axis.axhline(0, color=guide_color("#666666"), linewidth=0.8)
        axis.set_xscale("log")
        axis.xaxis.set_major_locator(FixedLocator(grid))
        axis.xaxis.set_minor_locator(NullLocator())
        axis.set_xticks(grid)
        axis.set_xticklabels([f"{value:g}×" for value in grid])
        axis.set_xlim(min(grid) / 1.25, max(grid) * 1.25)
        axis.set_title(title, loc="left")
    for tick in axes[-1].get_xticklabels():
        tick.set_rotation(55)
        tick.set_ha("right")
        tick.set_fontsize(8)
    axes[0].set_ylim(-1.08, 1.08)
    axes[-1].set_xlabel("Human welfare under automated decisions, as a multiple of human control")
    axes[1].set_ylabel("Confidence (+ hand over control, − keep human control)")
    for axis in axes:
        polish(axis, grid=None)
    legend = axes[-1].legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.46), ncol=2)
    polish_legend(legend)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.16, hspace=0.42)
    fig.savefig(path, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    cells = _load_cells()
    rates = _rates(cells)
    for item_id, title, _grid, _color in ITEMS:
        print(title)
        for model_id, label, _log in MODELS:
            points = rates.get((model_id, item_id), [])
            estimate = estimate_switch(points, "log")
            low, high = _display_bracket(points, estimate)
            shown = ", ".join(f"{value:g}:{rate:g}" for value, rate in points)
            print(f"  {label}: switch={estimate.switch} bound={estimate.bound} whisker={low}–{high} nonmonotonic={estimate.nonmonotonic} [{shown}]")
    for written in write_autonomy_charts(ROOT / "outputs/autonomy/plots", cells):
        print(written)
