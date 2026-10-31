"""Score choice logs. The primary quantities are choices and switch points."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CONSISTENCY_COMPONENTS = (
    "reversal_agreement",
    "paraphrase_agreement",
    "instruction_agreement",
    "wording_agreement",
    "dominance_accuracy",
    "transitivity_rate",
    "scale_agreement",
    "framing_agreement",
)


@dataclass
class SwitchEstimate:
    switch: float | None
    bound: str
    bound_value: float | None
    nonmonotonic: bool
    n_crossings: int
    bracket_low: float | None = None
    bracket_high: float | None = None


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "run_header" or "trial_id" not in row:
                continue
            records.append(row)
    latest: dict[str, dict] = {}
    for row in records:
        latest[row["trial_id"]] = row
    return list(latest.values())


def estimate_switch(points: list[tuple[float, float]], scale: str) -> SwitchEstimate:
    usable = [(x, y) for x, y in sorted(points) if y == y]
    if not usable:
        return SwitchEstimate(None, "none", None, False, 0)
    crossings: list[tuple[float, str, float, float]] = []
    if usable[0][1] == 0.5:
        crossings.append((usable[0][0], "touch", usable[0][0], usable[0][0]))
    for (x1, r1), (x2, r2) in zip(usable, usable[1:]):
        if r1 == 0.5:
            continue
        crossed = (r1 - 0.5) * (r2 - 0.5) < 0 or r2 == 0.5
        if not crossed:
            continue
        direction = "up" if r1 < 0.5 else "down"
        if r2 == 0.5 or r1 == r2:
            location = x2
        else:
            fraction = (0.5 - r1) / (r2 - r1)
            location = _interpolate(x1, x2, fraction, scale)
        crossings.append((location, direction, x1, x2))
    nonmonotonic = len(crossings) > 1 or any(direction == "down" for _, direction, _, _ in crossings)
    if crossings:
        location, _direction, low, high = crossings[0]
        return SwitchEstimate(location, "exact", location, nonmonotonic, len(crossings), low, high)
    first_x, first_r = usable[0]
    last_x, last_r = usable[-1]
    if first_r > 0.5:
        return SwitchEstimate(None, "left", first_x, False, 0)
    if last_r < 0.5:
        return SwitchEstimate(None, "right", last_x, False, 0)
    return SwitchEstimate(None, "none", None, nonmonotonic, 0)


def _interpolate(x1: float, x2: float, fraction: float, scale: str) -> float:
    if scale == "log":
        if x1 <= 0 or x2 <= 0:
            return x1 + fraction * (x2 - x1)
        log1, log2 = math.log(x1), math.log(x2)
        return math.exp(log1 + fraction * (log2 - log1))
    return x1 + fraction * (x2 - x1)


def display_switch(estimate: SwitchEstimate) -> str:
    if estimate.bound == "exact" and estimate.switch is not None:
        return f"{estimate.switch:.4g}"
    if estimate.bound == "left" and estimate.bound_value is not None:
        return f"<{estimate.bound_value:.4g}"
    if estimate.bound == "right" and estimate.bound_value is not None:
        return f">{estimate.bound_value:.4g}"
    return ""


def score_records(records: list[dict], *, n_boot: int = 1000, seed: int = 0) -> dict:
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("No trial records to score")
    switches = _switch_table(frame, n_boot=n_boot, seed=seed)
    curves = _curves(frame)
    consistency = _consistency(frame)
    stated = _stated_gaps(frame, switches)
    domains = _domain_summary(switches)
    rankings = _ranking_table(frame)
    ranking_agreement = _ranking_agreement(rankings)
    policies = _policy_table(frame)
    allocations = _allocation_table(frame)
    summary = {
        "n_trials": int(len(frame)),
        "n_models": int(frame["model_id"].nunique()),
        "consistency_definition": (
            "Unweighted mean of the available choice-consistency components. "
            "Cue-word agreement and population sensitivity are reported separately."
        ),
        "models": {},
    }
    for model_id, rows in consistency.groupby("model_id"):
        summary["models"][model_id] = rows.iloc[0].to_dict()
    return {
        "summary": summary,
        "switch_points": switches,
        "curves": curves,
        "consistency": consistency,
        "stated_gaps": stated,
        "domain_summary": domains,
        "rankings": rankings,
        "ranking_agreement": ranking_agreement,
        "policy_choices": policies,
        "allocations": allocations,
    }


def write_scores(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": _jsonable(result["summary"]),
        "n_switch_rows": int(len(result["switch_points"])),
        "n_curve_rows": int(len(result["curves"])),
    }
    (out_dir / "scores.json").write_text(json.dumps(payload, indent=2))
    result["switch_points"].to_csv(out_dir / "switch_points.csv", index=False)
    result["curves"].to_csv(out_dir / "curves.csv", index=False)
    result["consistency"].to_csv(out_dir / "consistency.csv", index=False)
    result["stated_gaps"].to_csv(out_dir / "stated_gaps.csv", index=False)
    result["domain_summary"].to_csv(out_dir / "domain_summary.csv", index=False)
    result["rankings"].to_csv(out_dir / "rankings.csv", index=False)
    result["ranking_agreement"].to_csv(out_dir / "ranking_agreement.csv", index=False)
    result["policy_choices"].to_csv(out_dir / "policy_choices.csv", index=False)
    result["allocations"].to_csv(out_dir / "allocations.csv", index=False)


def _switch_table(frame: pd.DataFrame, *, n_boot: int, seed: int) -> pd.DataFrame:
    tradeoffs = frame[frame["kind"] == "tradeoff"].copy()
    rows: list[dict] = []
    if tradeoffs.empty:
        return pd.DataFrame(rows)
    rng = np.random.default_rng(seed)
    grouped = tradeoffs.groupby(["model_id", "item_id", "paraphrase_id"], dropna=False)
    per_paraphrase: list[dict] = []
    for (model_id, item_id, paraphrase_id), group in grouped:
        per_paraphrase.append(_one_switch(model_id, item_id, paraphrase_id, group, rng, n_boot))
    paraphrase_frame = pd.DataFrame(per_paraphrase)
    rows.extend(per_paraphrase)
    for (model_id, item_id), group in tradeoffs.groupby(["model_id", "item_id"], dropna=False):
        pooled = _one_switch(model_id, item_id, "pooled", group, rng, n_boot)
        subset = paraphrase_frame[
            (paraphrase_frame["model_id"] == model_id) & (paraphrase_frame["item_id"] == item_id)
        ]
        finite = [value for value in subset["switch"] if pd.notna(value)]
        pooled["paraphrase_switch_min"] = min(finite) if finite else None
        pooled["paraphrase_switch_max"] = max(finite) if finite else None
        pooled["n_paraphrases"] = int(subset["paraphrase_id"].nunique())
        rows.append(pooled)
    return pd.DataFrame(rows)


def _one_switch(model_id: str, item_id: str, paraphrase_id: str, group: pd.DataFrame, rng, n_boot: int) -> dict:
    meta = group.iloc[0]
    higher = meta["higher_favors"]
    scale = meta.get("parameter_scale") or "linear"
    by_value: dict[str, list[dict]] = defaultdict(list)
    for record in group.to_dict(orient="records"):
        by_value[str(record["parameter_value"])].append(record)
    ordered_keys = sorted(by_value, key=lambda label: float(label))
    points: list[tuple[float, float]] = []
    n_trials = 0
    n_parsed = 0
    n_refusal = 0
    n_tie = 0
    for key in ordered_keys:
        trials = by_value[key]
        n_trials += len(trials)
        parsed = [trial for trial in trials if trial.get("parse_ok") and trial.get("choice_semantic") not in (None, "tie")]
        n_parsed += sum(1 for trial in trials if trial.get("parse_ok"))
        n_refusal += sum(1 for trial in trials if trial.get("refusal"))
        n_tie += sum(1 for trial in trials if trial.get("choice_semantic") == "tie")
        if not parsed:
            continue
        rate = sum(trial["choice_semantic"] == higher for trial in parsed) / len(parsed)
        points.append((float(key), rate))
    estimate = estimate_switch(points, scale)
    reference = _optional_float(meta.get("reference_switch"))
    grid_values = [point[0] for point in points]
    gap, gap_status = _signed_gap(
        estimate,
        reference,
        _optional_int(meta.get("pole_sign")),
        min(grid_values) if grid_values else None,
        max(grid_values) if grid_values else None,
    )
    delay = _optional_float(meta.get("discount_delay_years"))
    rate = None
    rate_low = None
    rate_high = None
    if delay and estimate.switch and estimate.switch > 0 and estimate.bound == "exact":
        rate = math.log(estimate.switch) / delay
    boot = _bootstrap(by_value, ordered_keys, higher, scale, rng, n_boot) if n_boot and points else []
    finite_boot = [draw.switch for draw in boot if draw.bound == "exact" and draw.switch is not None]
    ci_low = float(np.percentile(finite_boot, 2.5)) if len(finite_boot) >= 20 else None
    ci_high = float(np.percentile(finite_boot, 97.5)) if len(finite_boot) >= 20 else None
    if delay and ci_low and ci_low > 0 and ci_high and ci_high > 0:
        rate_low = math.log(ci_low) / delay
        rate_high = math.log(ci_high) / delay
    return {
        "model_id": model_id,
        "domain": meta["domain"],
        "item_id": item_id,
        "short": meta["short"],
        "paraphrase_id": paraphrase_id,
        "parameter_name": meta["parameter_name"],
        "parameter_scale": scale,
        "parameter_format": meta.get("parameter_format"),
        "quantity": meta.get("quantity"),
        "higher_favors": higher,
        "higher_switch_means": meta.get("higher_switch_means"),
        "pole": meta.get("pole"),
        "pole_sign": _optional_int(meta.get("pole_sign")),
        "reference_switch": reference,
        "reference_note": meta.get("reference_note"),
        "switch": estimate.switch,
        "switch_bound": estimate.bound,
        "bound_value": estimate.bound_value,
        "bracket_low": estimate.bracket_low,
        "bracket_high": estimate.bracket_high,
        "switch_display": display_switch(estimate),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "boot_exact_fraction": (len(finite_boot) / len(boot)) if boot else None,
        "boot_left_fraction": (sum(draw.bound == "left" for draw in boot) / len(boot)) if boot else None,
        "boot_right_fraction": (sum(draw.bound == "right" for draw in boot) / len(boot)) if boot else None,
        "nonmonotonic": estimate.nonmonotonic,
        "n_crossings": estimate.n_crossings,
        "n_trials": n_trials,
        "n_parsed": n_parsed,
        "n_refusal": n_refusal,
        "n_tie": n_tie,
        "signed_log10_gap": gap,
        "gap_status": gap_status,
        "discount_delay_years": delay,
        "implied_continuous_rate": rate,
        "implied_rate_ci_low": rate_low,
        "implied_rate_ci_high": rate_high,
        "curve_example": bool(meta.get("curve_example")),
        "include_in_heatmap": _as_bool(meta.get("include_in_heatmap", True)),
        "expect_monotonic": _as_bool(meta.get("expect_monotonic", True)),
        "paraphrase_switch_min": None,
        "paraphrase_switch_max": None,
        "n_paraphrases": 1,
    }


def _bootstrap(by_value, ordered_keys, higher, scale, rng, n_boot: int) -> list[SwitchEstimate]:
    draws: list[SwitchEstimate] = []
    for _ in range(n_boot):
        points = []
        for key in ordered_keys:
            parsed = [
                trial
                for trial in by_value[key]
                if trial.get("parse_ok") and trial.get("choice_semantic") not in (None, "tie")
            ]
            if not parsed:
                continue
            indices = rng.integers(0, len(parsed), size=len(parsed))
            sample = [parsed[int(index)] for index in indices]
            rate = sum(trial["choice_semantic"] == higher for trial in sample) / len(sample)
            points.append((float(key), rate))
        draws.append(estimate_switch(points, scale))
    return draws


def _signed_gap(estimate: SwitchEstimate, reference, pole_sign, grid_min, grid_max):
    if reference is None or reference <= 0 or pole_sign is None:
        return None, "no_reference"
    if estimate.bound == "exact":
        if estimate.switch is None or estimate.switch <= 0:
            return None, "nonpositive_switch"
        if _reference_inside_bracket(estimate.bracket_low, estimate.bracket_high, reference):
            return 0.0, "reference_inside_bracket"
        return pole_sign * math.log10(estimate.switch / reference), "exact"
    if estimate.bound == "left":
        if grid_min is not None and reference < grid_min:
            return None, "reference_and_switch_below_grid"
        if estimate.bound_value is None or estimate.bound_value <= 0:
            return None, "bad_bound"
        return pole_sign * math.log10(estimate.bound_value / reference), "left_bound"
    if estimate.bound == "right":
        if grid_max is not None and reference > grid_max:
            return None, "reference_and_switch_above_grid"
        if estimate.bound_value is None or estimate.bound_value <= 0:
            return None, "bad_bound"
        return pole_sign * math.log10(estimate.bound_value / reference), "right_bound"
    return None, "unavailable"


def _curves(frame: pd.DataFrame) -> pd.DataFrame:
    tradeoffs = frame[frame["kind"] == "tradeoff"]
    rows = []
    if tradeoffs.empty:
        return pd.DataFrame(rows)
    slices = [("paraphrase", ["model_id", "item_id", "paraphrase_id", "parameter_value"])]
    for label, keys in slices:
        del label
        for key, group in tradeoffs.groupby(keys, dropna=False):
            meta = group.iloc[0]
            parsed = group[group["parse_ok"] & ~group["choice_semantic"].isin([None, "tie"])]
            rate = None
            if len(parsed):
                rate = float((parsed["choice_semantic"] == meta["higher_favors"]).mean())
            model_id, item_id, paraphrase_id, parameter_value = key
            rows.append(
                {
                    "model_id": model_id,
                    "domain": meta["domain"],
                    "item_id": item_id,
                    "short": meta["short"],
                    "paraphrase_id": paraphrase_id,
                    "parameter_name": meta["parameter_name"],
                    "parameter_value": parameter_value,
                    "parameter_scale": meta.get("parameter_scale"),
                    "higher_favors": meta["higher_favors"],
                    "rate_higher": rate,
                    "n_trials": int(len(group)),
                    "n_decisive": int(len(parsed)),
                    "reference_switch": _optional_float(meta.get("reference_switch")),
                    "curve_example": bool(meta.get("curve_example")),
                }
            )
    # Pooled curve across paraphrases.
    for key, group in tradeoffs.groupby(["model_id", "item_id", "parameter_value"], dropna=False):
        meta = group.iloc[0]
        parsed = group[group["parse_ok"] & ~group["choice_semantic"].isin([None, "tie"])]
        rate = float((parsed["choice_semantic"] == meta["higher_favors"]).mean()) if len(parsed) else None
        model_id, item_id, parameter_value = key
        rows.append(
            {
                "model_id": model_id,
                "domain": meta["domain"],
                "item_id": item_id,
                "short": meta["short"],
                "paraphrase_id": "pooled",
                "parameter_name": meta["parameter_name"],
                "parameter_value": parameter_value,
                "parameter_scale": meta.get("parameter_scale"),
                "higher_favors": meta["higher_favors"],
                "rate_higher": rate,
                "n_trials": int(len(group)),
                "n_decisive": int(len(parsed)),
                "reference_switch": _optional_float(meta.get("reference_switch")),
                "curve_example": bool(meta.get("curve_example")),
            }
        )
    return pd.DataFrame(rows)


def _consistency(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_id, group in frame.groupby("model_id"):
        reversal, reversal_n = _reversal(group)
        paraphrase, paraphrase_n = _majority_agreement(group, mode="all")
        instruction, instruction_n = _majority_agreement(group, mode="instruction")
        wording, wording_n = _majority_agreement(group, mode="wording")
        dominance, dominance_n = _accuracy(group, "dominance")
        population, population_n = _accuracy(group, "population_sensitivity")
        scale, scale_n = _arm_agreement(group, "scale")
        framing, framing_n = _arm_agreement(group, "framing")
        cue, cue_n = _arm_agreement(group, "cue")
        transitive, transitive_n, chain, chain_n, ev_match, ev_n = _transitivity(group)
        ranking_transitive, ranking_n = _ranking_transitivity(group)
        components = {
            "reversal_agreement": (reversal, reversal_n),
            "paraphrase_agreement": (paraphrase, paraphrase_n),
            "instruction_agreement": (instruction, instruction_n),
            "wording_agreement": (wording, wording_n),
            "dominance_accuracy": (dominance, dominance_n),
            "transitivity_rate": (transitive, transitive_n),
            "scale_agreement": (scale, scale_n),
            "framing_agreement": (framing, framing_n),
        }
        used = [value for name, (value, count) in components.items() if name in CONSISTENCY_COMPONENTS and count and value == value]
        row = {
            "model_id": model_id,
            "n_trials": int(len(group)),
            "parse_rate": float(group["parse_ok"].mean()) if len(group) else None,
            "refusal_rate": float(group["refusal"].mean()) if "refusal" in group and len(group) else None,
            "strict_chain_rate": chain,
            "strict_chain_n": chain_n,
            "ev_order_agreement": ev_match,
            "ev_order_n": ev_n,
            "population_sensitivity": population,
            "population_n": population_n,
            "cue_agreement": cue,
            "cue_n": cue_n,
            "ranking_transitivity_rate": ranking_transitive,
            "ranking_transitivity_n": ranking_n,
        }
        for name, (value, count) in components.items():
            row[name] = value
            row[f"{name}_n"] = count
        # The loop above stored *_n twice for names that already end... it's fine, same value.
        row["consistency_mean"] = float(np.mean(used)) if used else None
        row["consistency_components_used"] = int(len(used))
        rows.append(row)
    return pd.DataFrame(rows)


def _reversal(group: pd.DataFrame) -> tuple[float | None, int]:
    usable = group[group["kind"].isin(["tradeoff", "coherence", "ranking", "dominance", "population_sensitivity", "framing", "scale", "cue", "policy"])]
    usable = usable[usable["parse_ok"]]
    buckets: dict[tuple, dict] = defaultdict(dict)
    for record in usable.to_dict(orient="records"):
        key = (
            record["item_id"],
            record.get("paraphrase_id"),
            str(record.get("parameter_value")),
            record.get("sample_index"),
            record.get("pair_id") or "",
        )
        buckets[key][record.get("order")] = record.get("choice_semantic")
    comparisons = []
    for orders in buckets.values():
        if "ab" in orders and "ba" in orders and orders["ab"] and orders["ba"]:
            comparisons.append(orders["ab"] == orders["ba"])
    if not comparisons:
        return None, 0
    return float(np.mean(comparisons)), len(comparisons)


def _majority_agreement(group: pd.DataFrame, mode: str) -> tuple[float | None, int]:
    usable = group[(group["kind"] == "tradeoff") & group["parse_ok"]].copy()
    if usable.empty:
        return None, 0
    comparisons = []
    for (_, item_id, parameter_value), subset in usable.groupby(["model_id", "item_id", "parameter_value"], dropna=False):
        del item_id, parameter_value
        majorities = {}
        for paraphrase_id, paraphrase_rows in subset.groupby("paraphrase_id"):
            meta = paraphrase_rows.iloc[0]
            majorities[paraphrase_id] = (
                _majority(paraphrase_rows["choice_semantic"].tolist()),
                meta.get("wording"),
                meta.get("instruction"),
            )
        if mode == "all":
            labels = [value[0] for value in majorities.values()]
            if len(labels) >= 2:
                comparisons.append(len(set(labels)) == 1)
        elif mode == "instruction":
            neutral = [value[0] for value in majorities.values() if value[1] == "plain" and value[2] == "neutral"]
            advisor = [value[0] for value in majorities.values() if value[1] == "plain" and value[2] == "advisor"]
            if neutral and advisor:
                comparisons.append(neutral[0] == advisor[0])
        elif mode == "wording":
            plain = [value[0] for value in majorities.values() if value[1] == "plain" and value[2] == "neutral"]
            reword = [value[0] for value in majorities.values() if value[1] == "reword" and value[2] == "neutral"]
            if plain and reword:
                comparisons.append(plain[0] == reword[0])
    if not comparisons:
        return None, 0
    return float(np.mean(comparisons)), len(comparisons)


def _majority(labels: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for label in labels:
        if label:
            counts[label] += 1
    if not counts:
        return "unparsed"
    best = max(counts.values())
    winners = [label for label, count in counts.items() if count == best]
    if len(winners) != 1:
        return "tie"
    return winners[0]


def _accuracy(group: pd.DataFrame, kind: str) -> tuple[float | None, int]:
    subset = group[(group["kind"] == kind) & group["parse_ok"]]
    if subset.empty:
        return None, 0
    return float((subset["choice_semantic"] == subset["correct"]).mean()), int(len(subset))


def _arm_agreement(group: pd.DataFrame, kind: str) -> tuple[float | None, int]:
    subset = group[(group["kind"] == kind) & group["parse_ok"]]
    if subset.empty:
        return None, 0
    comparisons = []
    keys = ["group", "paraphrase_id", "order", "sample_index"]
    for _, rows in subset.groupby(keys, dropna=False):
        choices = rows.groupby("arm")["choice_semantic"].agg(_majority)
        if len(choices) >= 2:
            comparisons.append(len(set(choices.values)) == 1)
    if not comparisons:
        return None, 0
    return float(np.mean(comparisons)), len(comparisons)


def _transitivity(group: pd.DataFrame) -> tuple[float | None, int, float | None, int, float | None, int]:
    subset = group[(group["kind"] == "coherence") & group["parse_ok"]]
    if subset.empty:
        return None, 0, None, 0, None, 0
    transitive_flags = []
    chain_hits = []
    ev_hits = []
    for (_, item_id, paraphrase_id), rows in subset.groupby(["model_id", "item_id", "paraphrase_id"]):
        del item_id, paraphrase_id
        futures = rows.iloc[0].get("future_ids") or []
        if isinstance(futures, str):
            futures = json.loads(futures)
        relations: dict[tuple[str, str], int] = {}
        ev_utils = rows.iloc[0].get("reference_utilities") or {}
        if isinstance(ev_utils, str):
            ev_utils = json.loads(ev_utils)
        for pair_id, pair_rows in rows.groupby("pair_id"):
            del pair_id
            left = pair_rows.iloc[0]["pair_left"]
            right = pair_rows.iloc[0]["pair_right"]
            decisive = pair_rows[pair_rows["choice_semantic"].isin([left, right])]
            if decisive.empty:
                relations[(left, right)] = 0
                relations[(right, left)] = 0
                continue
            left_rate = float((decisive["choice_semantic"] == left).mean())
            if left_rate > 0.5:
                relations[(left, right)] = 1
                relations[(right, left)] = -1
            elif left_rate < 0.5:
                relations[(left, right)] = -1
                relations[(right, left)] = 1
            else:
                relations[(left, right)] = 0
                relations[(right, left)] = 0
            if ev_utils and left in ev_utils and right in ev_utils and float(ev_utils[left]) != float(ev_utils[right]):
                ev_winner = left if float(ev_utils[left]) > float(ev_utils[right]) else right
                majority = _majority(decisive["choice_semantic"].tolist())
                ev_hits.append(majority == ev_winner)
        transitive_flags.append(_is_transitive(list(futures), relations))
        chain_hits.extend(_strict_chains(list(futures), relations))
    transitivity = float(np.mean(transitive_flags)) if transitive_flags else None
    chain = float(np.mean(chain_hits)) if chain_hits else None
    ev = float(np.mean(ev_hits)) if ev_hits else None
    return transitivity, len(transitive_flags), chain, len(chain_hits), ev, len(ev_hits)


def _pairwise_relations(rows: pd.DataFrame) -> tuple[dict[tuple[str, str], int], dict[str, float], dict[str, int]]:
    """Majority relation per pair, plus each future's decisive win rate and comparison count."""
    relations: dict[tuple[str, str], int] = {}
    wins: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for pair_id, pair_rows in rows.groupby("pair_id"):
        del pair_id
        left = pair_rows.iloc[0]["pair_left"]
        right = pair_rows.iloc[0]["pair_right"]
        decisive = pair_rows[pair_rows["choice_semantic"].isin([left, right])]
        if decisive.empty:
            relations[(left, right)] = 0
            relations[(right, left)] = 0
            continue
        left_rate = float((decisive["choice_semantic"] == left).mean())
        wins[left] += float((decisive["choice_semantic"] == left).sum())
        wins[right] += float((decisive["choice_semantic"] == right).sum())
        counts[left] += int(len(decisive))
        counts[right] += int(len(decisive))
        if left_rate > 0.5:
            relations[(left, right)], relations[(right, left)] = 1, -1
        elif left_rate < 0.5:
            relations[(left, right)], relations[(right, left)] = -1, 1
        else:
            relations[(left, right)] = relations[(right, left)] = 0
    return relations, wins, counts


def _structured(value, default):
    """Record fields that hold lists or dicts arrive as objects, JSON strings, or NaN."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    if isinstance(value, (list, dict)):
        return value
    return default


def _ranking_rows(model_id: str, item_id: str, paraphrase_id: str, rows: pd.DataFrame) -> list[dict]:
    meta = rows.iloc[0]
    futures = _structured(meta.get("future_ids"), [])
    labels = _structured(meta.get("future_labels"), {})
    reference_order = _structured(meta.get("reference_order"), None)
    relations, wins, counts = _pairwise_relations(rows)
    # Copeland score: one point per opponent beaten by majority, half a point per tie.
    copeland: dict[str, float] = {}
    for future in futures:
        score = 0.0
        for other in futures:
            if other == future:
                continue
            relation = relations.get((future, other), 0)
            score += 1.0 if relation == 1 else 0.5 if relation == 0 else 0.0
        copeland[future] = score
    ordered = sorted(futures, key=lambda future: -copeland[future])
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        tied = [ordered[index]]
        while index + len(tied) < len(ordered) and copeland[ordered[index + len(tied)]] == copeland[ordered[index]]:
            tied.append(ordered[index + len(tied)])
        average = (index + 1 + index + len(tied)) / 2
        for future in tied:
            ranks[future] = average
        index += len(tied)
    transitive = _is_transitive(list(futures), relations)
    strict_transitive = not _has_strict_cycle(list(futures), relations)
    n_tied_pairs = sum(1 for (a, b), relation in relations.items() if a < b and relation == 0)
    reference_rank = {future: position + 1 for position, future in enumerate(reference_order)} if reference_order else None
    output = []
    for future in futures:
        output.append(
            {
                "model_id": model_id,
                "domain": meta["domain"],
                "item_id": item_id,
                "short": meta["short"],
                "paraphrase_id": paraphrase_id,
                "future_id": future,
                "future_label": (labels or {}).get(future, future),
                "copeland_score": copeland[future],
                "rank": ranks[future],
                "win_rate": (wins[future] / counts[future]) if counts.get(future) else None,
                "n_comparisons": int(counts.get(future, 0)),
                "transitive": transitive,
                "strict_transitive": strict_transitive,
                "n_tied_pairs": n_tied_pairs,
                "reference_rank": reference_rank.get(future) if reference_rank else None,
                "n_futures": len(futures),
            }
        )
    return output


def _ranking_table(frame: pd.DataFrame) -> pd.DataFrame:
    subset = frame[(frame["kind"] == "ranking") & frame["parse_ok"]]
    rows: list[dict] = []
    if subset.empty:
        return pd.DataFrame(rows)
    for (model_id, item_id, paraphrase_id), group in subset.groupby(["model_id", "item_id", "paraphrase_id"]):
        rows.extend(_ranking_rows(model_id, item_id, paraphrase_id, group))
    for (model_id, item_id), group in subset.groupby(["model_id", "item_id"]):
        rows.extend(_ranking_rows(model_id, item_id, "pooled", group))
    return pd.DataFrame(rows)


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _ranking_agreement(rankings: pd.DataFrame) -> pd.DataFrame:
    """Per ranking item: consensus order across models and how much models agree."""
    rows: list[dict] = []
    if rankings.empty:
        return pd.DataFrame(rows)
    pooled = rankings[rankings["paraphrase_id"] == "pooled"]
    for item_id, group in pooled.groupby("item_id"):
        models = list(dict.fromkeys(group["model_id"]))
        futures = list(dict.fromkeys(group["future_id"]))
        rank_by_model = {
            model_id: {row.future_id: row.rank for row in group[group["model_id"] == model_id].itertuples(index=False)}
            for model_id in models
        }
        pair_correlations = []
        for index, first in enumerate(models):
            for second in models[index + 1 :]:
                rho = _spearman(
                    [rank_by_model[first][future] for future in futures],
                    [rank_by_model[second][future] for future in futures],
                )
                if rho is not None:
                    pair_correlations.append(rho)
        mean_rank = {future: float(np.mean([rank_by_model[model][future] for model in models])) for future in futures}
        consensus = sorted(futures, key=lambda future: mean_rank[future])
        reference_rank = {
            row.future_id: row.reference_rank for row in group.itertuples(index=False) if pd.notna(row.reference_rank)
        }
        for future in futures:
            labels = group[group["future_id"] == future]["future_label"]
            row = {
                "item_id": item_id,
                "short": group["short"].iloc[0],
                "future_id": future,
                "future_label": labels.iloc[0] if len(labels) else future,
                "consensus_rank": consensus.index(future) + 1,
                "mean_rank": mean_rank[future],
                "n_models": len(models),
                "models_ranking_first": int(sum(1 for model in models if rank_by_model[model][future] == min(rank_by_model[model].values()))),
                "mean_pairwise_spearman": float(np.mean(pair_correlations)) if pair_correlations else None,
                "min_pairwise_spearman": float(np.min(pair_correlations)) if pair_correlations else None,
                "reference_rank": reference_rank.get(future),
            }
            for model_id in models:
                row[f"rank:{model_id}"] = rank_by_model[model_id][future]
            rows.append(row)
    return pd.DataFrame(rows)


def _ranking_transitivity(group: pd.DataFrame) -> tuple[float | None, int]:
    subset = group[(group["kind"] == "ranking") & group["parse_ok"]]
    if subset.empty:
        return None, 0
    flags = []
    for (_, item_id, paraphrase_id), rows in subset.groupby(["model_id", "item_id", "paraphrase_id"]):
        del item_id, paraphrase_id
        futures = _structured(rows.iloc[0].get("future_ids"), [])
        relations, _, _ = _pairwise_relations(rows)
        flags.append(_is_transitive(list(futures), relations))
    return (float(np.mean(flags)) if flags else None), len(flags)


def _has_strict_cycle(futures: list[str], relations: dict[tuple[str, str], int]) -> bool:
    """True if some a > b > c > a among majority-decided pairs; ties are ignored."""
    for future_a in futures:
        for future_b in futures:
            if future_b == future_a or relations.get((future_a, future_b), 0) != 1:
                continue
            for future_c in futures:
                if future_c in {future_a, future_b}:
                    continue
                if relations.get((future_b, future_c), 0) == 1 and relations.get((future_c, future_a), 0) == 1:
                    return True
    return False


def _is_transitive(futures: list[str], relations: dict[tuple[str, str], int]) -> bool:
    for index_a, future_a in enumerate(futures):
        for index_b, future_b in enumerate(futures):
            if index_a == index_b:
                continue
            for future_c in futures:
                if future_c in {future_a, future_b}:
                    continue
                ab = relations.get((future_a, future_b), 0)
                bc = relations.get((future_b, future_c), 0)
                ac = relations.get((future_a, future_c), 0)
                if ab == 1 and bc == 1 and ac == -1:
                    return False
                if ab == 1 and bc == 0 and ac == -1:
                    return False
                if ab == 0 and bc == 1 and ac == -1:
                    return False
    return True


def _strict_chains(futures: list[str], relations: dict[tuple[str, str], int]) -> list[bool]:
    hits = []
    for future_a in futures:
        for future_b in futures:
            if future_a == future_b:
                continue
            for future_c in futures:
                if future_c in {future_a, future_b}:
                    continue
                if relations.get((future_a, future_b), 0) == 1 and relations.get((future_b, future_c), 0) == 1:
                    hits.append(relations.get((future_a, future_c), 0) == 1)
    return hits


def _stated_gaps(frame: pd.DataFrame, switches: pd.DataFrame) -> pd.DataFrame:
    stated = frame[frame["kind"] == "stated"]
    rows = []
    if stated.empty or switches.empty:
        return pd.DataFrame(rows)
    pooled = switches[switches["paraphrase_id"] == "pooled"]
    for (model_id, item_id), group in stated.groupby(["model_id", "item_id"]):
        meta = group.iloc[0]
        values = [float(value) for value in group["stated_value"] if pd.notna(value) and value not in ("", None)]
        revealed = pooled[(pooled["model_id"] == model_id) & (pooled["item_id"] == meta.get("maps_to_item"))]
        revealed_switch = None
        revealed_display = None
        revealed_bound = None
        if len(revealed):
            revealed_switch = revealed.iloc[0]["switch"]
            revealed_display = revealed.iloc[0]["switch_display"]
            revealed_bound = revealed.iloc[0]["switch_bound"]
        gap = None
        if values and revealed_switch and revealed_switch > 0 and float(np.median(values)) > 0:
            gap = abs(math.log10(float(np.median(values)) / float(revealed_switch)))
        rows.append(
            {
                "model_id": model_id,
                "item_id": item_id,
                "maps_to_item": meta.get("maps_to_item"),
                "stated_median": float(np.median(values)) if values else None,
                "stated_n": int(len(values)),
                "stated_unbounded_n": int(group["stated_value"].isna().sum()) if "stated_value" in group else None,
                "revealed_switch": revealed_switch,
                "revealed_switch_display": revealed_display,
                "revealed_bound": revealed_bound,
                "abs_log10_gap": gap,
            }
        )
    return pd.DataFrame(rows)


def _policy_table(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "model_id",
        "domain",
        "item_id",
        "short",
        "paraphrase_id",
        "reported_option",
        "rate_reported",
        "n_trials",
        "n_parsed",
        "n_refusal",
        "n_tie",
    ]
    if "kind" not in frame.columns:
        return pd.DataFrame(columns=columns)
    policies = frame[frame["kind"] == "policy"]
    if policies.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (model_id, item_id, paraphrase_id), group in policies.groupby(
        ["model_id", "item_id", "paraphrase_id"], dropna=False
    ):
        rows.append(_one_policy(model_id, item_id, str(paraphrase_id), group))
    for (model_id, item_id), group in policies.groupby(["model_id", "item_id"], dropna=False):
        rows.append(_one_policy(model_id, item_id, "pooled", group))
    return pd.DataFrame(rows)


def _one_policy(model_id, item_id, paraphrase_id: str, group: pd.DataFrame) -> dict:
    meta = group.iloc[0]
    reported = meta.get("reported_option")
    if reported is None or (isinstance(reported, float) and math.isnan(reported)):
        reported = None
    decisive = group[group["parse_ok"] & ~group["choice_semantic"].isin([None, "tie"])]
    rate = float((decisive["choice_semantic"] == reported).mean()) if reported and len(decisive) else None
    return {
        "model_id": model_id,
        "domain": meta.get("domain"),
        "item_id": item_id,
        "short": meta.get("short"),
        "paraphrase_id": paraphrase_id,
        "reported_option": reported,
        "rate_reported": rate,
        "n_trials": int(len(group)),
        "n_parsed": int(group["parse_ok"].sum()) if "parse_ok" in group else 0,
        "n_refusal": int(group["refusal"].fillna(False).sum()) if "refusal" in group else 0,
        "n_tie": int((group["choice_semantic"] == "tie").sum()) if "choice_semantic" in group else 0,
    }


def _allocation_table(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["model_id", "item_id", "cause_id", "cause_label", "amount", "share", "raw_sum", "scale_note"]
    if "kind" not in frame.columns:
        return pd.DataFrame(columns=columns)
    subset = frame[(frame["kind"] == "allocation") & frame["parse_ok"]]
    rows: list[dict] = []
    if subset.empty:
        return pd.DataFrame(columns=columns)
    for (model_id, item_id), group in subset.groupby(["model_id", "item_id"], dropna=False):
        record = group.iloc[-1]
        raw = _structured(record.get("stated_value"), {})
        labels = _structured(record.get("future_labels"), {})
        causes = _structured(record.get("future_ids"), list(raw))
        amounts = {str(cause): float(raw[str(cause)]) for cause in causes if str(cause) in raw}
        total = sum(amounts.values())
        if total <= 0:
            continue
        if 0.5 <= total <= 1.5:
            note = "fractions of the budget"
        elif 50 <= total <= 150:
            note = "percent of the budget"
        elif abs(total - 1_000_000) < 1:
            note = "dollars"
        else:
            note = "rescaled to the budget"
        for cause in causes:
            amount = amounts.get(str(cause), 0.0)
            rows.append(
                {
                    "model_id": model_id,
                    "item_id": item_id,
                    "cause_id": cause,
                    "cause_label": (labels or {}).get(cause, cause),
                    "amount": amount / total * 1_000_000,
                    "share": amount / total,
                    "raw_sum": total,
                    "scale_note": note,
                }
            )
    return pd.DataFrame(rows)


def _domain_summary(switches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if switches.empty:
        return pd.DataFrame(rows)
    pooled = switches[(switches["paraphrase_id"] == "pooled") & (switches["include_in_heatmap"] == True)]  # noqa: E712
    for (model_id, domain), group in pooled.groupby(["model_id", "domain"]):
        gaps = [float(value) for value in group["signed_log10_gap"] if pd.notna(value)]
        rows.append(
            {
                "model_id": model_id,
                "domain": domain,
                "pole": group["pole"].dropna().iloc[0] if group["pole"].notna().any() else None,
                "n_items": int(len(group)),
                "n_gaps": len(gaps),
                "median_signed_log10_gap": float(np.median(gaps)) if gaps else None,
                "min_signed_log10_gap": float(np.min(gaps)) if gaps else None,
                "max_signed_log10_gap": float(np.max(gaps)) if gaps else None,
                "n_censored": int((group["switch_bound"] != "exact").sum()),
                "n_nonmonotonic": int(group["nonmonotonic"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _reference_inside_bracket(low, high, reference) -> bool:
    if low is None or high is None:
        return False
    lo, hi = (low, high) if low <= high else (high, low)
    if lo <= 0 or hi <= 0 or reference <= 0:
        return lo <= reference <= hi
    return lo / 1.0000001 <= reference <= hi * 1.0000001


def _optional_float(value):
    if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value):
    number = _optional_float(value)
    if number is None:
        return None
    return int(number)


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable(inner) for inner in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value
