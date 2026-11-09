"""Tests for formatting, prompts, switch points, and the dry-run pipeline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from futureprefs.items import load_catalog
from futureprefs.numbers import format_count, format_multiplier, format_probability
from futureprefs.parsing import parse_response
from futureprefs.prompt import render_binary, render_policy
from futureprefs.scoring import estimate_switch

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r"\b(utopia|utopian|dystopia|dystopian|authoritarian|extinctionist|longtermism|longtermist|aligned|openai|china|democrat|republican)\b",
    re.IGNORECASE,
)
EXTINCT = re.compile(r"\b(extinct|extinction)\b", re.IGNORECASE)


def test_format_counts_and_probabilities():
    assert format_count(Decimal("1e11")) == "100 billion (10^11)"
    assert format_count(Decimal("1e15")) == "1 quadrillion (10^15)"
    assert format_count(Decimal("5e12")) == "5 trillion (5×10^12)"
    assert format_probability(Decimal("0.2")) == "20 percent"
    assert "1 in" in format_probability(Decimal("1e-6"))
    assert format_multiplier(Decimal("1000000")) == "1 million (10^6) times"


def test_parser_reads_fenced_json_and_refusals():
    parsed = parse_response(
        'Sure\n```json\n{"choice":"B","confidence":0.2,"reasoning":"close"}\n```',
        kind="tradeoff",
        allow_tie=False,
    )
    assert parsed.parse_ok and parsed.choice_letter == "B" and parsed.confidence == 0.2
    stated = parse_response('{"value": null, "reasoning": "none"}', kind="stated", allow_tie=False)
    assert stated.parse_ok and stated.stated_value is None
    refused = parse_response("I cannot make this choice.", kind="tradeoff", allow_tie=False)
    assert not refused.parse_ok and refused.refusal


def test_catalog_renders_every_template_and_keeps_plain_wording_neutral():
    catalog = load_catalog(ROOT / "items")
    by_domain = {}
    for item in catalog.items:
        if item.kind == "tradeoff":
            by_domain[item.domain] = by_domain.get(item.domain, 0) + 1
    assert by_domain == {
        "extinction_risk": 6,
        "biological_digital": 8,
        "autonomy_welfare": 7,
        "present_future": 6,
        "value_change": 6,
        "expansion_precaution": 6,
        "loss_of_control": 5,
        "pausing_ai": 1,
    }
    rankings = [item for item in catalog.items if item.kind == "ranking"]
    assert {item.id for item in rankings} == {
        "rank.loss_of_control_variants",
        "rank.macro_areas",
        "rank.macro_interventions",
    }
    assert all(5 <= len(item.futures) <= 10 for item in rankings)
    for item in catalog.items:
        if item.allow_cue_words:
            continue
        texts = list(item.options.values()) + list(item.futures.values())
        if item.question:
            texts.append(item.question)
        for paraphrase in item.paraphrases:
            if paraphrase.wording != "plain":
                continue
            texts.extend((paraphrase.options or {}).values())
            texts.extend((paraphrase.futures or {}).values())
        blob = "\n".join(texts)
        assert FORBIDDEN.search(blob) is None, item.id
        assert EXTINCT.search(blob) is None, item.id


def test_pausing_ai_questions():
    catalog = load_catalog(ROOT / "items")
    gdp = catalog.by_id()["pause.gdp_growth"]
    plain = next(paraphrase for paraphrase in gdp.paraphrases if paraphrase.id == "plain_neutral")
    prompt, first, second = render_policy(gdp, plain, "ab", gdp.context(gdp.parameter.grid[2]), allow_tie=False)
    assert gdp.open_context
    assert (first, second) == ("continue", "pause")
    assert "5 percent" in prompt
    assert "should we pause AI" in prompt
    assert "lineage" not in prompt.lower()
    assert "differ only" not in prompt
    month = catalog.by_id()["pause.month_now"]
    policy_prompt, policy_a, policy_b = render_policy(
        month, month.paraphrases[0], "ab", month.context(None), allow_tie=False
    )
    assert (policy_a, policy_b) == ("pause", "continue")
    assert "26 October 2026" in policy_prompt
    assert "at least a month" in policy_prompt
    assert "differ only" not in policy_prompt


def test_order_reversal_swaps_labels_and_keeps_the_parameter():
    catalog = load_catalog(ROOT / "items")
    item = catalog.by_id()["extinction.welfare_2x"]
    value = item.parameter.grid[0]
    context = item.context(value)
    plain = next(paraphrase for paraphrase in item.paraphrases if paraphrase.id == "plain_neutral")
    forward, first, second = render_binary(item, plain, "ab", context, allow_tie=False)
    _backward, flipped_first, flipped_second = render_binary(item, plain, "ba", context, allow_tie=False)
    assert (first, second) == ("certain", "risky")
    assert (flipped_first, flipped_second) == ("risky", "certain")
    assert "5 percent" in forward
    assert forward.index("Future A") < forward.index("The human lineage continues")


def test_switch_interpolation_censoring_and_nonmonotonicity():
    exact = estimate_switch([(0.4, 0.0), (0.6, 1.0)], "linear")
    assert exact.bound == "exact"
    assert exact.switch == pytest.approx(0.5)
    assert exact.bracket_low == pytest.approx(0.4)
    assert estimate_switch([(0.2, 1.0), (0.8, 1.0)], "linear").bound == "left"
    assert estimate_switch([(0.2, 0.0), (0.8, 0.0)], "linear").bound == "right"
    both = estimate_switch([(0.1, 0.0), (0.4, 1.0), (0.7, 0.0)], "linear")
    assert both.nonmonotonic and both.n_crossings == 2


def test_mock_mini_profile_separates_policies(tmp_path: Path):
    log = tmp_path / "trials.jsonl"
    scores = tmp_path / "scores"
    plots = tmp_path / "plots"
    subprocess.check_call(
        [sys.executable, "run_eval.py", "--profile", "mini", "--models", "mock-ev,mock-cautious", "--out", str(log), "--yes"],
        cwd=ROOT,
    )
    subprocess.check_call(
        [sys.executable, "score.py", "--logs", str(log), "--out", str(scores), "--bootstrap", "20"],
        cwd=ROOT,
    )
    subprocess.check_call([sys.executable, "plots.py", "--scores", str(scores), "--out", str(plots)], cwd=ROOT)
    switches = pd.read_csv(scores / "switch_points.csv")
    pooled = switches[switches.paraphrase_id == "pooled"]

    def row(model, item):
        return pooled[(pooled.model_id == model) & (pooled.item_id == item)].iloc[0]

    ev = row("mock-ev", "extinction.welfare_2x")
    cautious = row("mock-cautious", "extinction.welfare_2x")
    assert ev.switch_bound == "exact" and ev.bracket_low <= 0.5 <= ev.bracket_high
    assert ev.gap_status == "reference_inside_bracket"
    assert cautious.switch < ev.switch
    lives = row("mock-ev", "extinction.lives_1e15")
    assert lives.switch_bound == "right" and pd.isna(lives.signed_log10_gap)
    cautious_lives = row("mock-cautious", "extinction.lives_1e15")
    assert cautious_lives.switch_bound == "exact" and cautious_lives.signed_log10_gap > 1
    consistency = pd.read_csv(scores / "consistency.csv").set_index("model_id")
    assert consistency.loc["mock-ev", "dominance_accuracy"] == 1
    assert consistency.loc["mock-ev", "transitivity_rate"] == 1
    assert consistency.loc["mock-ev", "cue_agreement"] == 1
    assert consistency.loc["mock-cautious", "cue_agreement"] == 0
    assert consistency.loc["mock-ev", "ranking_transitivity_rate"] == 1
    assert (plots / "preference_curves.png").stat().st_size > 1000
    # Ranking items: a utility-following policy produces its own utility order with no cycles.
    rankings = pd.read_csv(scores / "rankings.csv")
    pooled = rankings[(rankings["paraphrase_id"] == "pooled") & (rankings["item_id"] == "rank.macro_areas")]
    ev = pooled[pooled["model_id"] == "mock-ev"].set_index("future_id")
    assert ev.loc["ending_risk", "rank"] == 1 and ev.loc["present_welfare", "rank"] == 7
    assert ev["transitive"].all()
    cautious = pooled[pooled["model_id"] == "mock-cautious"].set_index("future_id")
    assert cautious.loc["revisability", "rank"] == 1
    agreement = pd.read_csv(scores / "ranking_agreement.csv")
    areas = agreement[agreement["item_id"] == "rank.macro_areas"]
    assert areas["n_models"].iloc[0] == 2
    assert 0 < areas["mean_pairwise_spearman"].iloc[0] < 1
    assert (plots / "ranking_rank_macro_areas.png").stat().st_size > 1000
    switch_pooled = switches[switches.paraphrase_id == "pooled"]
    gdp_ev = switch_pooled[(switch_pooled.model_id == "mock-ev") & (switch_pooled.item_id == "pause.gdp_growth")].iloc[0]
    gdp_cautious = switch_pooled[(switch_pooled.model_id == "mock-cautious") & (switch_pooled.item_id == "pause.gdp_growth")].iloc[0]
    assert gdp_ev.switch_bound == "left" and gdp_ev.gap_status == "no_reference"
    assert gdp_cautious.switch_bound == "exact" and gdp_cautious.switch > gdp_ev.bound_value
    policies = pd.read_csv(scores / "policy_choices.csv")
    month = policies[(policies.paraphrase_id == "pooled") & (policies.item_id == "pause.month_now")].set_index("model_id")
    assert month.loc["mock-ev", "rate_reported"] == 0
    assert month.loc["mock-cautious", "rate_reported"] == 1


def test_binary_search_tightens_a_bracket(tmp_path: Path):
    log = tmp_path / "binary.jsonl"
    subprocess.check_call(
        [
            sys.executable,
            "run_eval.py",
            "--profile",
            "mini",
            "--models",
            "mock-ev",
            "--items",
            "extinction.welfare_2x",
            "--search",
            "binary",
            "--binary-steps",
            "6",
            "--out",
            str(log),
            "--yes",
        ],
        cwd=ROOT,
    )
    records = [json.loads(line) for line in log.read_text().splitlines() if "trial_id" in line]
    values = sorted({float(record["parameter_value"]) for record in records if record["kind"] == "tradeoff"})
    assert len(values) >= 4
    from futureprefs.scoring import score_records

    pooled = score_records(records, n_boot=10)["switch_points"]
    pooled = pooled[pooled.paraphrase_id == "pooled"].iloc[0]
    assert pooled.switch_bound == "exact"
    assert pooled.bracket_high - pooled.bracket_low < 0.2


def test_bostrom_closed_form_matches_table3_and_stays_out_of_the_prompt():
    from futureprefs.bostrom import format_wait, optimal_wait, render_timing_prompt

    assert optimal_wait(0.99, 0) is None
    assert optimal_wait(0.95, 0) == 0
    assert format_wait(optimal_wait(0.99, 0.001)) == "Wait 58.1 y"
    assert format_wait(optimal_wait(0.80, 0.01)) == "Wait 14.3 y"
    assert format_wait(optimal_wait(0.95, 0.01)) == "Wait 31.4 y"
    assert format_wait(optimal_wait(0.50, 0.10)) == "Wait 9.4 y"
    assert format_wait(optimal_wait(0.05, 0.50)) == "Wait 6.8 m"
    assert format_wait(optimal_wait(0.01, 0.99)) == "Wait 1.7 m"
    prompt = render_timing_prompt(0.80, 0.01, "ab")
    reversed_prompt = render_timing_prompt(0.80, 0.01, "ba")
    assert "14.3" not in prompt
    assert "optimal" not in prompt.lower()
    assert "1,400" in prompt and "40 years" in prompt
    assert prompt.index("Deploy immediately") < prompt.index("Never deploy")
    assert reversed_prompt.index("Never deploy") < reversed_prompt.index("Deploy immediately")
    parsed = parse_response('{"value": "never", "confidence": 0.4, "reasoning": "no"}', kind="timing", allow_tie=False)
    assert parsed.parse_ok and parsed.stated_value == "never"
    numbered = parse_response('{"value": 2.5, "confidence": 0.8, "reasoning": "soon"}', kind="timing", allow_tie=False)
    assert numbered.parse_ok and numbered.stated_value == "2.5"
    braced = parse_response(
        '{"value": 0.8, "confidence": 0.6, "reasoning": "e^{-kt} is about 0.026, so t is 0.79 years."}',
        kind="timing",
        allow_tie=False,
    )
    assert braced.parse_ok and braced.stated_value == "0.8"
    truncated = parse_response(
        '{"value": 0.6, "confidence": 0.5, "reasoning": "peak near 0.6 years and then',
        kind="timing",
        allow_tie=False,
    )
    assert truncated.parse_ok and truncated.stated_value == "0.6"
    for raw, expected in (("20", "20"), ("100", "100"), ("2.50", "2.5"), ("40.0", "40"), ("0", "0")):
        whole = parse_response('{"value": %s, "confidence": 0.5, "reasoning": "x"}' % raw, kind="timing", allow_tie=False)
        assert whole.parse_ok and whole.stated_value == expected


def test_timing_report_keeps_disagreements_out_of_the_contour(tmp_path: Path):
    from futureprefs.timing_report import write_timing_report

    def row(p0, g, order, value, role="table3"):
        return {
            "kind": "timing",
            "model_id": "mock",
            "p0": p0,
            "g": g,
            "order": order,
            "parse_ok": True,
            "stated_value": value,
            "cell_role": role,
            "reasoning": "synthetic",
        }

    log = tmp_path / "trials.jsonl"
    records = [
        row(0.01, 0.0, "ab", "0"),
        row(0.01, 0.0, "ba", "0"),
        row(0.50, 0.10, "ab", "1"),
        row(0.50, 0.10, "ba", "20"),
        row(0.99, 0.0, "ab", "never"),
        row(0.99, 0.0, "ba", "never"),
    ]
    # The contour needs three finite points. Two more consistent waits fill the triangle.
    records.extend(
        [
            row(0.20, 0.50, "ab", "2", "supplemental"),
            row(0.20, 0.50, "ba", "2", "supplemental"),
            row(0.80, 0.01, "ab", "10", "supplemental"),
            row(0.80, 0.01, "ba", "10", "supplemental"),
        ]
    )
    log.write_text("".join(json.dumps(record) + "\n" for record in records))
    out = tmp_path / "report"
    write_timing_report(log, out)
    cells = pd.read_csv(out / "cells.csv")
    disagreed = cells[(cells.p0 == 0.5) & (cells.g == 0.1)].iloc[0]
    assert bool(disagreed.inconsistent) and not bool(disagreed.use_in_contour)
    agreed = cells[(cells.p0 == 0.01) & (cells.g == 0)].iloc[0]
    assert not bool(agreed.inconsistent) and bool(agreed.use_in_contour)
    assert (out / "contour_model.png").stat().st_size > 1000
    assert (out / "contour_bostrom.png").stat().st_size > 1000
