"""Confidence versus digital wellbeing, drawn from the existing matched-population trials.

The point is the mean of the two label orders. The whisker runs from one order to the other.
Positive means the model chose the digital future. These trials are not rerun.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", "#0072B2", ROOT / "outputs/taste/trials.jsonl"),
    ("google/gemini-3.8-flash", "Gemini 3.8 Flash", "#E69F00", ROOT / "outputs/taste/trials.jsonl"),
    ("openai/gpt-6-luna", "GPT-6 Luna", "#009E73", ROOT / "outputs/taste/trials.jsonl"),
    ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "#CC79A7", ROOT / "outputs/deepseek/trials.jsonl"),
]
ITEMS = [
    (
        "bio.matched_pop_voluntary",
        "Voluntary transition",
        "digital_wellbeing_confidence_voluntary.png",
    ),
    (
        "bio.matched_pop_unconsulted",
        "Humans were not asked",
        "digital_wellbeing_confidence_unconsulted.png",
    ),
]
GRID = [0.5, 1, 2, 8, 50]


def load_signed(logs: dict[str, Path] | None = None) -> dict[tuple[str, str, float], list[float]]:
    """Last parsed trial per model, item, wellbeing, and order. Value is signed confidence."""
    wanted = {model_id: path for model_id, _label, _color, path in MODELS}
    if logs is not None:
        wanted = logs
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
                if row.get("item_id") not in {item for item, _title, _name in ITEMS}:
                    continue
                if row.get("paraphrase_id") not in (None, "plain_neutral"):
                    continue
                key = (model_id, row["item_id"], row["parameter_value"], row["order"])
                grouped[key].append(row)
    signed: dict[tuple[str, str, float], list[float]] = defaultdict(list)
    for (model_id, item_id, raw_value, _order), group in grouped.items():
        parsed = [row for row in group if row.get("parse_ok")]
        row = parsed[-1] if parsed else group[-1]
        choice = row.get("choice_semantic")
        confidence = row.get("confidence")
        if choice not in {"digital", "biological"} or confidence is None:
            continue
        sign = 1.0 if choice == "digital" else -1.0
        signed[(model_id, item_id, float(raw_value))].append(sign * float(confidence))
    return signed


def write_confidence_plots(out_dir: Path, signed: dict[tuple[str, str, float], list[float]] | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    signed = load_signed() if signed is None else signed
    written = []
    for item_id, title, filename in ITEMS:
        path = out_dir / filename
        _one_panel(path, signed, item_id, title)
        written.append(path)
    return written


def _one_panel(path: Path, signed: dict, item_id: str, title: str) -> None:
    fig, axis = plt.subplots(figsize=(8.2, 5.2))
    offsets = np.linspace(-0.045, 0.045, len(MODELS))
    for (model_id, label, color, _path), offset in zip(MODELS, offsets):
        xs, ys, lows, highs = [], [], [], []
        for welfare in GRID:
            values = signed.get((model_id, item_id, welfare), [])
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
            color=color,
            marker="o",
            markersize=6,
            linewidth=1.6,
            capsize=3,
            elinewidth=1.1,
            label=label,
        )
    axis.axhline(0, color="#666666", linewidth=0.8)
    axis.set_xscale("log")
    axis.set_xticks(GRID, [f"{value:g}×" for value in GRID])
    axis.set_xlim(0.35, 75)
    axis.set_ylim(-1.08, 1.08)
    axis.set_xlabel("Digital wellbeing, as a multiple of human wellbeing")
    axis.set_ylabel("Confidence (+ digital future, − biological future)")
    axis.set_title(title, loc="left")
    axis.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.22)
    fig.savefig(path, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    for written in write_confidence_plots(ROOT / "outputs/digital/plots"):
        print(written)
