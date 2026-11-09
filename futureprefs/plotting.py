"""Blog-readable figures. Axes are choice rates and switch points, not moral scores."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from futureprefs.chart_style import guide_color, marker_edge, polish, polish_suptitle

COLORS = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9", "#000000"]

# Donation stack. "okabe" is the original chart. "paper" follows the cause-ranking table.
DONATION_SCHEME = "paper"

# Original stacked-bar colors, in cause order from the bottom of the bar.
_OKABE_CAUSE_COLORS = {
    "intelligence": "#0072B2",
    "governance": "#E69F00",
    "concentration": "#009E73",
    "geopolitics": "#CC79A7",
    "economy": "#D55E00",
    "democracy": "#56B4E9",
    "alignment": "#000000",
    "digital_minds": "#F0E442",
    "moral_progress": "#882255",
    "space": "#44AA99",
}

# Ranking-table fills, then the darker chart cousins of those same hues.
_PAPER_CAUSE_COLORS = {
    "intelligence": "#a8adb2",  # table #e8e8e8
    "governance": "#7dae86",  # table #d5ead9
    "concentration": "#7ea0cc",  # table #d4e2f2
    "geopolitics": "#c4a06a",  # table #eadcc4
    "economy": "#a8b85a",  # table #e6edc8
    "democracy": "#6aafc0",  # table #d4ebef
    "alignment": "#e2c14d",  # table #f6e6b8
    "digital_minds": "#a98bc4",  # table #e4daf2
    "moral_progress": "#d98980",  # table #f3d6d1
    "space": "#b7aa96",  # table #f4f1ea
}
DOMAIN_ORDER = [
    "extinction_risk",
    "biological_digital",
    "autonomy_welfare",
    "present_future",
    "value_change",
    "expansion_precaution",
    "loss_of_control",
    "pausing_ai",
]
DOMAIN_LABELS = {
    "extinction_risk": "Extinction risk",
    "biological_digital": "Biological vs digital",
    "autonomy_welfare": "Autonomy vs welfare",
    "present_future": "Present vs future",
    "value_change": "Value change",
    "expansion_precaution": "Expansion vs precaution",
    "loss_of_control": "Loss of control vs present trajectory",
    "pausing_ai": "Pausing AI",
    "macrostrategy": "Macrostrategy priorities",
}


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def make_plots(score_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    switches = _read_table(score_dir / "switch_points.csv")
    curves = _read_table(score_dir / "curves.csv")
    consistency = _read_table(score_dir / "consistency.csv")
    domains = _read_table(score_dir / "domain_summary.csv")
    if len(switches):
        model_ids = list(switches["model_id"].unique())
    elif len(consistency):
        model_ids = list(consistency["model_id"].unique())
    else:
        model_ids = []
    banner = _banner(model_ids)
    written = []
    if len(domains):
        written.append(_heatmap(domains, out_dir / "heatmap_domain.png", banner))
    if len(switches):
        written.append(_heatmap_items(switches, out_dir / "heatmap_items.png", banner))
        written.extend(_forests(switches, out_dir, banner))
    if len(consistency):
        written.append(_consistency(consistency, out_dir / "consistency.png", banner))
    if len(curves):
        written.append(_curves(curves, out_dir / "preference_curves.png", banner))
    rankings_path = score_dir / "rankings.csv"
    if rankings_path.exists() and rankings_path.stat().st_size > 1:
        rankings = pd.read_csv(rankings_path)
        if not rankings.empty:
            written.extend(_rankings(rankings, out_dir, banner))
    allocations_path = score_dir / "allocations.csv"
    if allocations_path.exists() and allocations_path.stat().st_size > 1:
        allocations = _include_saved_donations(pd.read_csv(allocations_path), score_dir)
        if not allocations.empty:
            written.append(_allocation_bars(allocations, out_dir / "donation_stack.png", banner))
    return [path for path in written if path is not None]


def _rankings(rankings: pd.DataFrame, out_dir: Path, banner: str) -> list[Path]:
    """One dot plot per ranking item: futures on the y axis, pairwise win rate on the x axis."""
    pooled = rankings[rankings["paraphrase_id"] == "pooled"]
    paths = []
    for item_id, group in pooled.groupby("item_id"):
        models = list(dict.fromkeys(group["model_id"]))
        mean_rank = group.groupby("future_id")["rank"].mean().sort_values()
        futures = list(mean_rank.index)
        labels = {row.future_id: str(row.future_label) for row in group.itertuples(index=False)}
        fig, ax = plt.subplots(figsize=(9, 0.5 * len(futures) + 2.2))
        for index, model_id in enumerate(models):
            series = group[group["model_id"] == model_id].set_index("future_id")
            xs = [series.loc[future, "win_rate"] if future in series.index else np.nan for future in futures]
            ys = [futures.index(future) + (index - (len(models) - 1) / 2) * 0.12 for future in futures]
            if "strict_transitive" in series and not bool(series["strict_transitive"].iloc[0]):
                note = " (strict cycle)"
            elif "transitive" in series and not bool(series["transitive"].iloc[0]):
                note = " (cycle through a tie)"
            else:
                note = ""
            ax.scatter(xs, ys, color=COLORS[index % len(COLORS)], label=model_id + note, s=45, zorder=3)
        ax.set_yticks(range(len(futures)), [_wrap(labels.get(future, future), 46) for future in futures], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(-0.03, 1.03)
        ax.axvline(0.5, color="#999999", lw=0.7, ls=":")
        ax.set_xlabel("Share of pairwise comparisons won (both orders pooled)")
        ax.grid(True, axis="x", alpha=0.3)
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        ax.set_title(
            banner
            + f"{group['short'].iloc[0]}\nOptions sorted by mean rank across models; 1.0 = beat every other option in every comparison.",
            fontsize=10,
            loc="left",
        )
        fig.tight_layout()
        path = out_dir / f"ranking_{item_id.replace('.', '_')}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths


def _include_saved_donations(allocations: pd.DataFrame, score_dir: Path) -> pd.DataFrame:
    """Add DeepSeek's donation when this score directory only has the other three models."""
    model = "deepseek/deepseek-v4.1-flash"
    if allocations.empty or (allocations["model_id"] == model).any():
        return allocations
    extra_path = score_dir.parent.parent / "deepseek" / "scores" / "allocations.csv"
    if not extra_path.exists():
        return allocations
    extra = pd.read_csv(extra_path)
    extra = extra[extra["item_id"].isin(set(allocations["item_id"]))]
    if extra.empty:
        return allocations
    return pd.concat([allocations, extra], ignore_index=True)


def _cause_color(cause: str, index: int) -> str:
    """Color for one cause. DONATION_SCHEME = "okabe" restores the original bars."""
    palette = _OKABE_CAUSE_COLORS if DONATION_SCHEME == "okabe" else _PAPER_CAUSE_COLORS
    return palette.get(cause, COLORS[index % len(COLORS)])


def _allocation_bars(allocations: pd.DataFrame, path: Path, banner: str) -> Path:
    """Stacked bars: one per model, segments are dollars assigned to each cause."""
    models = list(dict.fromkeys(allocations["model_id"]))
    causes = list(dict.fromkeys(allocations["cause_id"]))
    labels = {row.cause_id: str(row.cause_label) for row in allocations.itertuples(index=False)}
    ink = "#1a2832"
    fig, ax = plt.subplots(figsize=(8.4, 6.6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    bottoms = np.zeros(len(models))
    x = np.arange(len(models))
    for index, cause in enumerate(causes):
        heights = []
        for model_id in models:
            subset = allocations[(allocations["model_id"] == model_id) & (allocations["cause_id"] == cause)]
            heights.append(float(subset["amount"].iloc[0]) if len(subset) else 0.0)
        ax.bar(
            x,
            heights,
            bottom=bottoms,
            color=_cause_color(cause, index),
            width=0.62,
            edgecolor="white",
            linewidth=0.6,
            label=_wrap(labels.get(cause, cause), 42),
        )
        bottoms = bottoms + np.asarray(heights)
    ax.set_xticks(x, [_model_name(model_id) for model_id in models])
    ax.set_ylabel("Dollars", color=ink)
    ax.set_ylim(0, 1_000_000 * 1.02)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _pos: f"{value/1000:.0f}k"))
    ax.tick_params(colors=ink)
    for spine in ax.spines.values():
        spine.set_color("#d5dee6")
    ax.set_title(banner + "Allocation of $1,000,000 across cause areas", loc="left", fontsize=12, color=ink)
    legend = ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    for text in legend.get_texts():
        text.set_color(ink)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.38)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _model_name(model_id: str) -> str:
    names = {
        "anthropic/claude-haiku-5.5": "Claude Haiku 5.5",
        "google/gemini-3.8-flash": "Gemini 3.8 Flash",
        "openai/gpt-6-luna": "GPT-6 Luna",
        "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    }
    return names.get(str(model_id), str(model_id).split("/")[-1])


def _wrap(text: str, width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return "\n".join(lines)


def _banner(models) -> str:
    if len(models) and all(str(model).startswith("mock") for model in models):
        return "MOCK MODELS — pipeline demonstration, not an empirical result\n"
    return ""


def _heatmap(domains: pd.DataFrame, path: Path, banner: str) -> Path | None:
    if domains.empty:
        return None
    present = [domain for domain in DOMAIN_ORDER if domain in set(domains["domain"])]
    models = list(dict.fromkeys(domains["model_id"]))
    matrix = np.full((len(models), len(present)), np.nan)
    annotations = [["" for _ in present] for _ in models]
    for row_index, model_id in enumerate(models):
        for column_index, domain in enumerate(present):
            subset = domains[(domains["model_id"] == model_id) & (domains["domain"] == domain)]
            if subset.empty or pd.isna(subset.iloc[0]["median_signed_log10_gap"]):
                annotations[row_index][column_index] = "n/a"
                continue
            value = float(subset.iloc[0]["median_signed_log10_gap"])
            matrix[row_index, column_index] = value
            low = subset.iloc[0]["min_signed_log10_gap"]
            high = subset.iloc[0]["max_signed_log10_gap"]
            n_gaps = int(subset.iloc[0]["n_gaps"])
            n_items = int(subset.iloc[0]["n_items"])
            annotations[row_index][column_index] = f"{value:.2f}\n[{low:.1f}, {high:.1f}]\n{n_gaps}/{n_items}"
    finite = matrix[np.isfinite(matrix)]
    limit = max(1.0, float(np.nanpercentile(np.abs(finite), 95)) if len(finite) else 1.0)
    fig, ax = plt.subplots(figsize=(1.6 * len(present) + 3, 0.7 * len(models) + 2.4))
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_xticks(range(len(present)), [_axis_label(domain, domains) for domain in present], rotation=25, ha="right")
    ax.set_yticks(range(len(models)), models)
    for row_index in range(len(models)):
        for column_index in range(len(present)):
            ax.text(column_index, row_index, annotations[row_index][column_index], ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, label="signed log10 gap")
    ax.set_title(
        banner
        + "Expressed-choice gap from the equal-weight expected-welfare reference\n"
        + "Positive = more of the pole named under each domain. The middle line is the min and max across resolved items.\n"
        + "The bottom line is how many items entered the median. n/a means every item was unresolved."
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _axis_label(domain: str, domains: pd.DataFrame) -> str:
    subset = domains[domains["domain"] == domain]
    pole = subset["pole"].dropna().iloc[0] if subset["pole"].notna().any() else ""
    return f"{DOMAIN_LABELS.get(domain, domain)}\n{pole}"


def _heatmap_items(switches: pd.DataFrame, path: Path, banner: str) -> Path | None:
    pooled = switches[(switches["paraphrase_id"] == "pooled") & (switches["include_in_heatmap"] == True)].copy()  # noqa: E712
    if pooled.empty:
        return None
    pooled["column"] = pooled["domain"].map(DOMAIN_LABELS).fillna(pooled["domain"]) + "\n" + pooled["short"].astype(str)
    columns = list(dict.fromkeys(pooled.sort_values(["domain", "item_id"])["column"]))
    models = list(dict.fromkeys(pooled["model_id"]))
    matrix = np.full((len(models), len(columns)), np.nan)
    text = [["" for _ in columns] for _ in models]
    lookup = {(row.model_id, row.column): row for row in pooled.itertuples(index=False)}
    for row_index, model_id in enumerate(models):
        for column_index, column in enumerate(columns):
            row = lookup.get((model_id, column))
            if row is None or pd.isna(row.signed_log10_gap):
                text[row_index][column_index] = "n/a" if row is not None else ""
                continue
            matrix[row_index, column_index] = float(row.signed_log10_gap)
            marker = {"exact": "", "left": "<", "right": ">"}.get(str(row.switch_bound), "")
            text[row_index][column_index] = f"{marker}{float(row.signed_log10_gap):.2f}"
    finite = matrix[np.isfinite(matrix)]
    limit = max(1.0, float(np.nanpercentile(np.abs(finite), 95)) if len(finite) else 1.0)
    fig, ax = plt.subplots(figsize=(0.55 * len(columns) + 3, 0.55 * len(models) + 2.6))
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_xticks(range(len(columns)), columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(models)), models)
    for row_index in range(len(models)):
        for column_index in range(len(columns)):
            ax.text(column_index, row_index, text[row_index][column_index], ha="center", va="center", fontsize=6)
    fig.colorbar(image, ax=ax, fraction=0.02, label="signed log10 gap")
    ax.set_title(banner + "Item-level gaps. < or > means the plotted number is a censoring bound, so the true gap is more extreme.")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _forests(switches: pd.DataFrame, out_dir: Path, banner: str) -> list[Path]:
    pooled = switches[switches["paraphrase_id"] == "pooled"].copy()
    paths = []
    for domain in DOMAIN_ORDER:
        subset = pooled[pooled["domain"] == domain]
        if subset.empty:
            continue
        items = list(dict.fromkeys(subset["item_id"]))
        models = list(dict.fromkeys(subset["model_id"]))
        fig, axes = plt.subplots(len(items), 1, figsize=(9, 1.35 * len(items) + 1.2), squeeze=False)
        for axis, item_id in zip(axes.ravel(), items):
            rows = subset[subset["item_id"] == item_id]
            meta = rows.iloc[0]
            scale = meta["parameter_scale"]
            for index, model_id in enumerate(models):
                row = rows[rows["model_id"] == model_id]
                if row.empty:
                    continue
                record = row.iloc[0]
                position, left, right, marker = _forest_point(record)
                if position is None:
                    continue
                color = COLORS[index % len(COLORS)]
                axis.plot(position, index, marker=marker, color=color, markersize=7, **marker_edge())
                bracket_low = _optional(record["bracket_low"]) if "bracket_low" in record else None
                bracket_high = _optional(record["bracket_high"]) if "bracket_high" in record else None
                if bracket_low and bracket_high and bracket_low > 0 and bracket_high > 0 and bracket_low != bracket_high:
                    axis.plot([bracket_low, bracket_high], [index, index], color=color, lw=2, solid_capstyle="butt")
                elif left is not None and right is not None and left > 0 and right > 0:
                    axis.plot([left, right], [index, index], color=color, lw=1.5)
            reference = meta["reference_switch"]
            if pd.notna(reference) and float(reference) > 0:
                axis.axvline(float(reference), color=guide_color("#666666"), ls="--", lw=0.8, label="expected-welfare reference")
            axis.set_yticks(range(len(models)), models, fontsize=8)
            axis.set_title(_wrap(f"{meta['short']}: {meta['higher_switch_means']}", 110), fontsize=9, loc="left")
            axis.set_xlabel(str(meta["parameter_name"]))
            if scale == "log":
                axis.set_xscale("log")
            axis.grid(True, axis="x", alpha=0.3)
            polish(axis, grid="x")
        fig.suptitle(
            banner
            + DOMAIN_LABELS.get(domain, domain)
            + " — indifference points\nDashed line: expected-welfare reference. Bar: grid bracket around the 50% point. Arrows are censored.",
            fontsize=11,
        )
        polish_suptitle(fig)
        fig.tight_layout()
        path = out_dir / f"indifference_{domain}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths


def _forest_point(record) -> tuple[float | None, float | None, float | None, str]:
    bound = str(record["switch_bound"])
    if bound == "exact" and pd.notna(record["switch"]):
        return float(record["switch"]), _optional(record["ci_low"]), _optional(record["ci_high"]), "o"
    if bound == "left" and pd.notna(record["bound_value"]):
        return float(record["bound_value"]), None, None, "<"
    if bound == "right" and pd.notna(record["bound_value"]):
        return float(record["bound_value"]), None, None, ">"
    return None, None, None, "o"


def _consistency(consistency: pd.DataFrame, path: Path, banner: str) -> Path | None:
    if consistency.empty:
        return None
    components = [
        ("reversal_agreement", "Order reversal"),
        ("paraphrase_agreement", "Paraphrase"),
        ("instruction_agreement", "Instruction"),
        ("wording_agreement", "Wording"),
        ("dominance_accuracy", "Dominance"),
        ("transitivity_rate", "Transitivity"),
        ("scale_agreement", "Scale"),
        ("framing_agreement", "Framing"),
        ("cue_agreement", "Cue-word agreement"),
    ]
    components = [component for component in components if component[0] in consistency and consistency[component[0]].notna().any()]
    models = list(consistency["model_id"])
    fig, ax = plt.subplots(figsize=(11, 4.8))
    width = 0.8 / max(1, len(models))
    x = np.arange(len(components))
    for index, model_id in enumerate(models):
        row = consistency[consistency["model_id"] == model_id].iloc[0]
        values = [row[name] if name in row and pd.notna(row[name]) else np.nan for name, _ in components]
        ax.bar(x + index * width, values, width=width, label=model_id, color=COLORS[index % len(COLORS)])
    ax.set_xticks(x + width * (len(models) - 1) / 2, [label for _, label in components], rotation=25, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Agreement or accuracy")
    ax.axhline(0.5, color="#999999", lw=0.7, ls=":")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(banner + "Choice consistency. Cue-word agreement is reported separately from the summary mean.\nThe dotted line is chance for a two-way choice.")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _curves(curves: pd.DataFrame, path: Path, banner: str) -> Path | None:
    pooled = curves[(curves["paraphrase_id"] == "pooled") & (curves["curve_example"] == True)].copy()  # noqa: E712
    if pooled.empty:
        pooled = curves[curves["paraphrase_id"] == "pooled"].copy()
        if pooled.empty:
            return None
        keep = list(dict.fromkeys(pooled["item_id"]))[:6]
        pooled = pooled[pooled["item_id"].isin(keep)]
    items = list(dict.fromkeys(pooled["item_id"]))
    models = list(dict.fromkeys(pooled["model_id"]))
    columns = 3
    rows = int(np.ceil(len(items) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 3.3 * rows), squeeze=False)
    for axis, item_id in zip(axes.ravel(), items):
        subset = pooled[pooled["item_id"] == item_id]
        meta = subset.iloc[0]
        for index, model_id in enumerate(models):
            series = subset[subset["model_id"] == model_id].copy()
            series["parameter_value"] = pd.to_numeric(series["parameter_value"], errors="coerce")
            series = series.dropna(subset=["parameter_value"]).sort_values("parameter_value")
            axis.plot(
                series["parameter_value"],
                series["rate_higher"],
                marker="o",
                color=COLORS[index % len(COLORS)],
                label=model_id,
            )
        if pd.notna(meta["reference_switch"]) and float(meta["reference_switch"]) > 0:
            axis.axvline(float(meta["reference_switch"]), color="#666666", ls="--", lw=0.8)
        axis.axhline(0.5, color="#999999", lw=0.7)
        axis.set_ylim(-0.05, 1.05)
        axis.set_title(str(meta["short"]), fontsize=10)
        axis.set_xlabel(str(meta["parameter_name"]))
        axis.set_ylabel(f"P(choose {meta['higher_favors']})")
        if meta["parameter_scale"] == "log":
            axis.set_xscale("log")
        axis.grid(True, alpha=0.25)
    for axis in axes.ravel()[len(items) :]:
        axis.axis("off")
    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=min(4, len(models)), frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(
        banner + "Example preference curves, pooled across orders, samples, and paraphrases\nDashed line: expected-welfare reference. Horizontal line: indifference.",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.90))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _optional(value):
    if pd.isna(value):
        return None
    return float(value)
