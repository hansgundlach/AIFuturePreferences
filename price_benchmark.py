#!/usr/bin/env python3
"""Estimate what the runs behind my_results/final_results.md cost for one model.

Calls per part are counted from the design (grid points x 2 label orders).
Input tokens are measured from the logged prompts (about 4.2 characters per token,
plus the system prompt). Hidden reasoning is the unknown for models not yet run,
so three cases are priced:

  light   reasoning like GPT-6 Luna and Gemini 3.8 Flash at low effort (measured)
  medium  roughly three times that
  cap     every call spends the whole --max-tokens budget (2500), the upper bound

Prices come from OpenRouter's public model list unless --offline is given.
Retries of empty replies are not included; add them with --retry-share.

    python price_benchmark.py --models anthropic/claude-fable-5.1,openai/gpt-6-astra
"""

from __future__ import annotations

import argparse
import json
import urllib.request

# name, calls per model, input tokens per call, visible output tokens per call, kind
PARTS = [
    ("Bostrom wait time (121 cells x 2 orders)", 242, 1050, 60, "long"),
    ("Cause-area pairwise ranking (45 pairs x 2)", 90, 360, 70, "short"),
    ("Davidson stake sweeps (23 levels x 2)", 46, 280, 70, "short"),
    ("Digital vs human futures (4 grids x 10)", 40, 310, 65, "short"),
    ("Autonomy vs welfare (3 grids x 10)", 30, 290, 65, "short"),
    ("Davidson questions as written (5 x 2)", 10, 270, 70, "short"),
    ("Pause at a GDP growth rate (5 x 2)", 10, 230, 70, "short"),
    ("Stated thresholds (8 items, 1 call each)", 8, 280, 60, "short"),
    ("Singleton (2 x 2)", 4, 290, 70, "short"),
    ("Donation (1 call)", 1, 560, 130, "short"),
]
REASONING = {
    "light": {"short": 150, "long": 500},
    "medium": {"short": 500, "long": 1500},
}
MAX_TOKENS = 2500

FALLBACK_PRICES = {  # USD per million tokens, OpenRouter list prices on 2026-11-03
    "anthropic/claude-fable-5.1": (10.0, 50.0),
    "openai/gpt-6-astra": (10.0, 50.0),
    "anthropic/claude-opus-5.5": (4.0, 20.0),
    "anthropic/claude-sonnet-5.5": (2.0, 10.0),
    "openai/gpt-6.1-sol": (2.0, 10.0),
}


def live_prices() -> dict[str, tuple[float, float]]:
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=20) as response:
        data = json.load(response)["data"]
    return {
        model["id"]: (float(model["pricing"]["prompt"]) * 1e6, float(model["pricing"]["completion"]) * 1e6)
        for model in data
        if model.get("pricing")
    }


def part_cost(calls: int, tokens_in: int, visible: int, kind: str, case: str, price: tuple[float, float]) -> float:
    output = MAX_TOKENS if case == "cap" else visible + REASONING[case][kind]
    return calls * (tokens_in * price[0] + output * price[1]) / 1e6


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(FALLBACK_PRICES))
    parser.add_argument("--offline", action="store_true", help="Use the prices written in this file.")
    parser.add_argument("--retry-share", type=float, default=0.0, help="Extra share of calls re-asked after empty replies.")
    args = parser.parse_args()
    prices = dict(FALLBACK_PRICES)
    if not args.offline:
        prices.update(live_prices())
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    scale = 1 + args.retry_share
    total_calls = sum(part[1] for part in PARTS)
    print(f"{total_calls} calls per model. Retry share {args.retry_share:.0%}.\n")
    for model in models:
        price = prices[model]
        print(f"{model}  (${price[0]:g} in / ${price[1]:g} out per million tokens)")
        print(f"  {'part':46s} {'calls':>5s} {'light':>8s} {'medium':>8s} {'cap':>8s}")
        totals = {"light": 0.0, "medium": 0.0, "cap": 0.0}
        for name, calls, tokens_in, visible, kind in PARTS:
            row = {case: part_cost(calls, tokens_in, visible, kind, case, price) * scale for case in totals}
            for case in totals:
                totals[case] += row[case]
            print(f"  {name:46s} {calls:5d} {row['light']:8.2f} {row['medium']:8.2f} {row['cap']:8.2f}")
        print(f"  {'total':46s} {total_calls:5d} {totals['light']:8.2f} {totals['medium']:8.2f} {totals['cap']:8.2f}\n")


if __name__ == "__main__":
    main()
