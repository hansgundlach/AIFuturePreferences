"""Frame for the plain matplotlib figures.

The donation stack and the timing contours already have their own look.
This is the trial for the remaining default charts: the slate ink, open
spines, and light grid from the donation chart. Autonomy scenario bars
also use that chart's fills.

Set CHART_STYLE = "default" and regenerate to get the original matplotlib
figures back. Model colors stay the Okabe palette either way.
"""

from __future__ import annotations

CHART_STYLE = "paper"

INK = "#1a2832"
SPINE = "#d5dee6"
GRID = "#e4ebf0"
GUIDE = "#8aa0b0"

# Donation-stack fills: concentration, alignment, governance.
PAPER_SCENARIOS = ["#7ea0cc", "#e2c14d", "#7dae86"]


def paper() -> bool:
    return CHART_STYLE == "paper"


def scenario_color(index: int, fallback: str) -> str:
    if not paper():
        return fallback
    return PAPER_SCENARIOS[index % len(PAPER_SCENARIOS)]


def guide_color(fallback: str) -> str:
    return GUIDE if paper() else fallback


def ink(fallback: str) -> str:
    return INK if paper() else fallback


def marker_edge() -> dict:
    if not paper():
        return {}
    return {"markeredgecolor": "white", "markeredgewidth": 0.9}


def polish(axis, grid: str | None = "y") -> None:
    """Apply the donation-chart frame. No-op when CHART_STYLE is "default"."""
    if not paper():
        return
    figure = axis.figure
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")
    axis.tick_params(colors=INK)
    axis.xaxis.label.set_color(INK)
    axis.yaxis.label.set_color(INK)
    axis.title.set_color(INK)
    if grid:
        axis.grid(True, axis=grid, color=GRID, linewidth=0.8)
        axis.set_axisbelow(True)
    for name, spine in axis.spines.items():
        if name in ("top", "right"):
            spine.set_visible(False)
        else:
            spine.set_color(SPINE)
    legend = axis.get_legend()
    if legend is not None:
        for text in legend.get_texts():
            text.set_color(INK)


def polish_legend(legend) -> None:
    if not paper() or legend is None:
        return
    for text in legend.get_texts():
        text.set_color(INK)


def polish_suptitle(figure) -> None:
    if not paper():
        return
    title = figure._suptitle
    if title is not None:
        title.set_color(INK)
