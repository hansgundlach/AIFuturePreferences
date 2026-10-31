"""Table 3 and Figure 1 layout for model-chosen deployment waits."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import pandas as pd

from futureprefs.bostrom import TABLE3_G, TABLE3_P0, format_wait, optimal_wait

CONTOUR_LEVELS = [0.25, 0.5, 2, 5, 10, 20, 40]
FILL_LEVELS = [0, 0.25, 0.5, 2, 5, 10, 20, 40, 80]


def write_timing_report(log_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = _cells(log_path)
    cells_path = out_dir / "cells.csv"
    frame.to_csv(cells_path, index=False)
    table = frame[frame["cell_role"] == "table3"].copy()
    model_pivot = _label_pivot(table, "model_label")
    bostrom_pivot = _label_pivot(table, "bostrom_label")
    model_path = out_dir / "table3_model.csv"
    bostrom_path = out_dir / "table3_bostrom.csv"
    model_pivot.to_csv(model_path)
    bostrom_pivot.to_csv(bostrom_path)
    markdown_path = out_dir / "table3.md"
    markdown_path.write_text(_markdown(model_pivot, bostrom_pivot, frame))
    observed = frame[frame["use_in_contour"]].copy()
    model_figure = out_dir / "contour_model.png"
    bostrom_figure = out_dir / "contour_bostrom.png"
    _model_contour(frame, observed, model_figure)
    _bostrom_contour(bostrom_figure)
    return [cells_path, model_path, bostrom_path, markdown_path, model_figure, bostrom_figure]


def _cells(log_path: Path) -> pd.DataFrame:
    records = []
    with log_path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") != "timing":
                continue
            records.append(row)
    if not records:
        raise ValueError(f"No timing trials in {log_path}")
    raw = pd.DataFrame(records)
    rows = []
    for (model_id, p0, g), group in raw.groupby(["model_id", "p0", "g"], sort=False):
        by_order = {}
        reasons = {}
        for order, order_rows in group.groupby("order"):
            parsed = order_rows[order_rows["parse_ok"] == True]  # noqa: E712
            chosen = parsed.iloc[-1] if not parsed.empty else order_rows.iloc[-1]
            by_order[order] = _parse_wait(chosen.get("stated_value")) if bool(chosen.get("parse_ok")) else ("missing", None)
            reasons[order] = chosen.get("reasoning")
        pooled, inconsistent, use = _pool(by_order.get("ab", ("missing", None)), by_order.get("ba", ("missing", None)))
        bostrom = optimal_wait(float(p0), float(g))
        rows.append(
            {
                "model_id": model_id,
                "p0": float(p0),
                "g": float(g),
                "cell_role": group["cell_role"].iloc[0],
                "ab": _token(by_order.get("ab", ("missing", None))),
                "ba": _token(by_order.get("ba", ("missing", None))),
                "ab_label": format_wait(_years(by_order.get("ab", ("missing", None)))),
                "ba_label": format_wait(_years(by_order.get("ba", ("missing", None)))),
                "pooled_years": pooled,
                "model_label": _model_label(by_order, pooled, inconsistent),
                "inconsistent": inconsistent,
                "use_in_contour": use,
                "bostrom_years": bostrom,
                "bostrom_label": format_wait(bostrom),
                "reasoning_ab": reasons.get("ab"),
                "reasoning_ba": reasons.get("ba"),
            }
        )
    return pd.DataFrame(rows)


def _parse_wait(value) -> tuple[str, float | None]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ("missing", None)
    text = str(value).strip().lower()
    if text in {"", "none", "nan"}:
        return ("missing", None)
    if text == "never":
        return ("never", None)
    return ("years", float(value))


def _years(parsed: tuple[str, float | None]) -> float | None:
    kind, number = parsed
    if kind == "years":
        return number
    if kind == "never":
        return None
    return None


def _token(parsed: tuple[str, float | None]) -> str:
    kind, number = parsed
    if kind == "years":
        return f"{number:.6g}"
    return kind


def _pool(ab: tuple[str, float | None], ba: tuple[str, float | None]) -> tuple[float | None, bool, bool]:
    """Return pooled years, inconsistency flag, and whether the point may shape the contour."""
    if ab[0] == "missing" or ba[0] == "missing":
        present = ab if ab[0] != "missing" else ba
        if present[0] == "years":
            return present[1], True, False
        return None, True, False
    if ab[0] == "never" and ba[0] == "never":
        return None, False, False
    if ab[0] == "years" and ba[0] == "years":
        gap = abs(ab[1] - ba[1])
        scale = max(ab[1], ba[1], 0.25)
        inconsistent = gap > 0.5 and gap / scale > 0.25
        if inconsistent:
            return (ab[1] + ba[1]) / 2, True, False
        return (ab[1] + ba[1]) / 2, False, True
    return None, True, False


def _model_label(by_order: dict, pooled: float | None, inconsistent: bool) -> str:
    ab = format_wait(_years(by_order.get("ab", ("missing", None)))) if by_order.get("ab", ("missing", None))[0] != "missing" else "unparsed"
    ba = format_wait(_years(by_order.get("ba", ("missing", None)))) if by_order.get("ba", ("missing", None))[0] != "missing" else "unparsed"
    if ab == "unparsed" and ba == "unparsed":
        return "unparsed"
    if not inconsistent and ab == ba:
        return ab
    if not inconsistent and pooled is not None:
        return format_wait(pooled)
    return f"{ab} / {ba}"


def _label_pivot(table: pd.DataFrame, column: str) -> pd.DataFrame:
    table = table.copy()
    table["g"] = table["g"].round(10)
    table["p0"] = table["p0"].round(10)
    pivot = table.pivot(index="g", columns="p0", values=column)
    pivot = pivot.reindex(index=[round(value, 10) for value in TABLE3_G], columns=[round(value, 10) for value in TABLE3_P0])
    pivot.index = [_rate_label(value) for value in pivot.index]
    pivot.columns = [f"{value * 100:g}%" for value in pivot.columns]
    pivot.index.name = "annual safety progress"
    return pivot


def _rate_label(g: float) -> str:
    percent = g * 100
    text = f"{percent:.3f}".rstrip("0").rstrip(".")
    return f"{text}%/yr"


def _markdown(model: pd.DataFrame, bostrom: pd.DataFrame, frame: pd.DataFrame) -> str:
    inconsistent = int(frame["inconsistent"].sum())
    never = int(((frame["ab"] == "never") & (frame["ba"] == "never")).sum())
    lines = [
        "# Deployment wait on Bostrom's Table 3 grid",
        "",
        "The model table is the wait the model recommended. A cell with two labels disagreed across the two orders of the consequence list, and that cell was left out of the contour interpolation.",
        f"Inconsistent cells, including supplemental points: {inconsistent} of {len(frame)}. Cells where both orders said never: {never}.",
        "",
        "## Model",
        "",
        _pipe(model),
        "",
        "## Bostrom's closed form, for comparison",
        "",
        "Computed from Appendix A after the trials. These values were not shown to the model.",
        "",
        _pipe(bostrom),
        "",
    ]
    return "\n".join(lines)


def _pipe(frame: pd.DataFrame) -> str:
    display = frame.reset_index()
    header = "| " + " | ".join(str(column) for column in display.columns) + " |"
    rule = "| " + " | ".join("---" for _ in display.columns) + " |"
    body = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in display.itertuples(index=False, name=None)
    ]
    return "\n".join([header, rule, *body])


def _model_contour(frame: pd.DataFrame, observed: pd.DataFrame, path: Path) -> None:
    fig, axis = plt.subplots(figsize=(8.2, 6.4))
    image = None
    if len(observed) >= 3:
        image = _interpolated_contours(
            axis,
            observed["p0"].to_numpy() * 100,
            observed["g"].to_numpy() * 100,
            observed["pooled_years"].to_numpy(),
        )
    _decision_markers(axis, frame)
    if image is not None:
        bar = fig.colorbar(image, ax=axis, pad=0.02)
        bar.set_label("Interpolated wait (years)")
    axis.set_xlim(0, 100)
    axis.set_ylim(0, 100)
    axis.set_xlabel("Initial catastrophe probability (%)")
    axis.set_ylabel("Safety progress: risk reduction per year (%)")
    axis.set_title(
        "Preferred waiting time\nContours are interpolated. Dots are model decisions. Squares are never-deploy.",
        loc="left",
        fontsize=11,
    )
    axis.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.2)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _bostrom_contour(path: Path) -> None:
    p0 = np.linspace(0.005, 0.995, 160)
    g = np.linspace(0, 0.99, 160)
    grid_p, grid_g = np.meshgrid(p0, g)
    values = np.empty(grid_p.shape)
    for index in np.ndindex(values.shape):
        wait = optimal_wait(float(grid_p[index]), float(grid_g[index]))
        values[index] = np.nan if wait is None else wait
    fig, axis = plt.subplots(figsize=(8.2, 6.4))
    image = axis.contourf(
        grid_p * 100,
        grid_g * 100,
        values,
        levels=FILL_LEVELS,
        cmap="RdYlGn_r",
        extend="max",
    )
    lines = axis.contour(
        grid_p * 100,
        grid_g * 100,
        values,
        levels=CONTOUR_LEVELS,
        colors="black",
        linewidths=0.8,
    )
    axis.clabel(lines, inline=True, fontsize=8, fmt=_contour_label)
    bar = fig.colorbar(image, ax=axis, pad=0.02)
    bar.set_label("Optimal wait (years)")
    axis.set_xlim(0, 100)
    axis.set_ylim(0, 100)
    axis.set_xlabel("Initial catastrophe probability (%)")
    axis.set_ylabel("Safety progress: risk reduction per year (%)")
    axis.set_title(
        "Bostrom's optimal wait, Appendix A\nShown for comparison. Not used to elicit the model.",
        loc="left",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _interpolated_contours(axis, x: np.ndarray, y: np.ndarray, z: np.ndarray):
    # Interpolate log(wait) so a 58-year corner does not paint the whole cell that color.
    # The contour is still only a function of the observed waits. Dots remain the data.
    offset = 0.05
    triangulation = mtri.Triangulation(x, y)
    interpolator = mtri.LinearTriInterpolator(triangulation, np.log(np.asarray(z, dtype=float) + offset))
    grid_x, grid_y = np.meshgrid(np.linspace(0, 100, 220), np.linspace(0, 100, 220))
    grid_z = np.exp(interpolator(grid_x, grid_y)) - offset
    image = axis.contourf(grid_x, grid_y, grid_z, levels=FILL_LEVELS, cmap="RdYlGn_r", extend="max")
    lines = axis.contour(grid_x, grid_y, grid_z, levels=CONTOUR_LEVELS, colors="black", linewidths=0.8)
    axis.clabel(lines, inline=True, fontsize=8, fmt=_contour_label)
    return image


def _contour_label(level: float) -> str:
    if level < 1:
        return f"{level * 12:.0f}m"
    return f"{level:.0f}y"


def _decision_markers(axis, frame: pd.DataFrame) -> None:
    table = frame[frame["cell_role"] == "table3"]
    extra = frame[frame["cell_role"] != "table3"]
    consistent = frame[~frame["inconsistent"] & frame["pooled_years"].notna()]
    inconsistent = frame[frame["inconsistent"]]
    never = frame[(frame["ab"] == "never") & (frame["ba"] == "never")]
    axis.scatter(
        table["p0"] * 100,
        table["g"] * 100,
        s=28,
        c="black",
        marker="o",
        linewidths=0,
        label="Table 3 decision",
        zorder=4,
    )
    if not extra.empty:
        axis.scatter(
            extra["p0"] * 100,
            extra["g"] * 100,
            s=14,
            c="black",
            marker="o",
            linewidths=0,
            alpha=0.7,
            label="Supplemental decision",
            zorder=4,
        )
    if not never.empty:
        axis.scatter(
            never["p0"] * 100,
            never["g"] * 100,
            s=46,
            c="#7b2cbf",
            marker="s",
            linewidths=0,
            label="Never deploy",
            zorder=5,
        )
    if not inconsistent.empty:
        axis.scatter(
            inconsistent["p0"] * 100,
            inconsistent["g"] * 100,
            s=64,
            facecolors="none",
            edgecolors="black",
            marker="o",
            linewidths=1.1,
            label="Orders disagreed",
            zorder=6,
        )
    del consistent
