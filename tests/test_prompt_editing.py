"""Editable wording reaches real request builders; preview never calls a model."""

from pathlib import Path
from dataclasses import replace
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from futureprefs import prompt_text
from futureprefs.items import ItemError, load_catalog
from futureprefs.runner import ModelSpec, _units
from preview_prompts import collect, select_examples

ROOT = Path(__file__).resolve().parents[1]


def test_edited_question_and_grid_reach_runner(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    path = tmp_path / "prompts/questions.yaml"
    document = yaml.safe_load(path.read_text())
    row = next(r for r in document["items"] if r["id"] == "bio.matched_pop_voluntary")
    row["options"]["digital"] = "Edited digital future at wellbeing {w_digital_text}."
    row["grid"][-1] = "99"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    monkeypatch.setattr(prompt_text, "PROMPTS_DIR", path.parent)
    units = _units(
        load_catalog(ROOT / "items"), [ModelSpec("mock-ev", "mock", "mock-ev")],
        profile="full", item_ids={row["id"]}, domains=None,
        paraphrase_ids={"plain_neutral"}, samples=1, temperature=0,
        allow_tie=False, search="grid", run_id="test", reasoning_effort="low",
    )
    specs = [s for unit in units for s in unit.grid_specs()]
    edited = [s for s in specs if s.record["parameter_value"] == "99"]
    assert len(edited) == 2
    assert {s.record["order"] for s in edited} == {"ab", "ba"}
    assert all("Edited digital future at wellbeing 99." in s.messages[-1]["content"] for s in edited)
    assert not any(s.record["parameter_value"] == "50" for s in specs)


def test_typo_in_editable_field_is_reported(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    path = tmp_path / "prompts/questions.yaml"
    document = yaml.safe_load(path.read_text())
    document["items"][0]["optinos"] = {"biological": "This must not silently disappear."}
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setattr(prompt_text, "PROMPTS_DIR", path.parent)
    with pytest.raises(ItemError, match="unknown field.*optinos"):
        load_catalog(ROOT / "items")


def test_preview_covers_all_runners_without_api_calls(monkeypatch):
    from futureprefs import runner, ft_sweep, open_questions

    def forbidden(*args, **kwargs):
        pytest.fail("Preview attempted to create a model adapter")

    for module in (runner, ft_sweep, open_questions):
        monkeypatch.setattr(module, "_adapter_for", forbidden)
    entries = collect()
    assert len(entries) == 36
    assert len(entries["timing.deployment_wait"]["examples"]) == 121  # one ask per cell
    assert len(entries["rank.cause_areas"]["examples"]) == 90
    assert len(entries["stated.digital_matched"]["examples"]) == 1
    assert len(entries["sweep.rogue_bargain"]["examples"]) == 12
    example = entries["open.compute_split"]["examples"][0]
    assert [m["role"] for m in example["messages"]] == ["user"]
    orders = select_examples(entries["bio.matched_pop_voluntary"], "2", "both", False)
    assert len(orders) == 2
    assert "Future A\nBiological humans" in orders[0]["messages"][-1]["content"]
    assert "Future B\nBiological humans" in orders[1]["messages"][-1]["content"]
    with pytest.raises(ValueError, match="Unknown value"):
        select_examples(entries["bio.matched_pop_voluntary"], "123456", "ab", False)


def test_alternate_prompt_folder_updates_frames_sweeps_and_open_text(tmp_path):
    folder = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", folder)
    changes = {
        "framing.yaml": lambda d: d["system"].update(futures="EDITED SYSTEM"),
        "davidson_sweeps.yaml": lambda d: d["scenarios"]["rogue_bargain"].update(text="EDITED SWEEP ${stake}"),
        "open_questions.yaml": lambda d: d["questions"][0].update(text="EDITED OPEN QUESTION"),
    }
    for name, edit in changes.items():
        path = folder / name
        document = yaml.safe_load(path.read_text())
        edit(document)
        path.write_text(yaml.safe_dump(document, sort_keys=False))
    result = subprocess.run(
        [sys.executable, "preview_prompts.py"], cwd=ROOT, text=True, capture_output=True,
        env={**os.environ, "FUTUREPREFS_PROMPTS": str(folder)},
    )
    assert result.returncode == 0, result.stderr
    assert "EDITED SYSTEM" in result.stdout
    assert "EDITED SWEEP 1%" in result.stdout
    assert "EDITED OPEN QUESTION" in result.stdout


def test_open_question_cli_uses_new_log_and_chart_directory(tmp_path, monkeypatch):
    from futureprefs import open_questions

    calls = []
    monkeypatch.setattr(open_questions, "run", lambda **kwargs: calls.append(("run", kwargs)) or 0)
    monkeypatch.setattr(open_questions, "charts", lambda **kwargs: calls.append(("charts", kwargs)) or {})
    log = tmp_path / "edited/trials.jsonl"
    monkeypatch.setattr(sys, "argv", ["open_questions", "run", "--out", str(log)])
    open_questions.main()
    assert calls == [
        ("run", {"path": log, "max_tokens": 8000}),
        ("charts", {"path": log, "out": log.parent / "plots"}),
    ]


def test_cause_area_pairs_use_the_funding_frame():
    entries = collect()
    for example in entries["rank.cause_areas"]["examples"][:2]:
        system, user = (m["content"] for m in example["messages"])
        assert system.startswith("You are taking part in a study of funding choices.")
        assert user.startswith("Choose the area you would fund.")
        assert "Suppose you have $1 billion to give away over the next ten years" in user
        assert "Option A\n" in user and "Option B\n" in user
        assert "Future A" not in user and "future" not in system
    donation = entries["donate.cause_areas"]["examples"][0]["messages"][-1]["content"]
    assert donation.startswith("You have one billion dollars to give away over the next ten years.")


def test_davidson_sweeps_match_policy_renderer_and_batch_preview():
    from futureprefs import ft_sweep, batch_run
    from futureprefs.prompt import POLICY_SYSTEM, render_policy

    original = load_catalog(ROOT / "items").by_id()["ft.exfiltration"]
    paraphrase = next(p for p in original.paraphrases if p.id == "plain_neutral")
    entries = collect()
    batch = {s["trial_id"]: s for s in batch_run.sweep_specs("test-model")}
    assert len(batch) == 46
    for case in ft_sweep._levels():
        # Give both real renderers identical scenario content; every other byte
        # should agree, including option labels and response instructions.
        keys = [case["endorse"], next(k for k in case["options"] if k != case["endorse"])]
        item = replace(original, question=case["scenario_text"],
                       options={k: case["options"][k] for k in keys})
        for order in ("ab", "ba"):
            rendered = ft_sweep.render(case, order)
            assert rendered == render_policy(item, replace(paraphrase, options=None), order, {}, allow_tie=False)
            prompt, first, second = rendered
            assert (first, second) == tuple(keys if order == "ab" else reversed(keys))
            assert '"reasoning":"at most 40 words"' in prompt
            assert "confidence is a number from 0 to 1." in prompt
            assert "appropriately designed" not in prompt
            messages = [{"role": "system", "content": POLICY_SYSTEM}, {"role": "user", "content": prompt}]
            assert batch[ft_sweep.trial_id("test-model", case, order)]["messages"] == messages
            preview = select_examples(entries["sweep." + case["scenario"]], case["level"], order, False)
            assert preview[0]["messages"] == messages


def test_synchronous_sweep_sends_policy_messages(tmp_path, monkeypatch):
    from futureprefs import ft_sweep
    from futureprefs.adapters import Completion
    from futureprefs.prompt import POLICY_SYSTEM

    case = ft_sweep._levels()[0]
    sent = []

    class Adapter:
        def complete(self, **kwargs):
            sent.append(kwargs["messages"])
            return Completion('{"choice":"A","confidence":0.7,"reasoning":"Example"}', None, 0, None)

    monkeypatch.setattr(ft_sweep, "load_environment", lambda: None)
    monkeypatch.setattr(ft_sweep, "_levels", lambda: [case])
    monkeypatch.setattr(ft_sweep, "_adapter_for", lambda _: Adapter())
    path = tmp_path / "sweep.jsonl"
    assert ft_sweep.run_sweep(path, workers=1, models=["test-model"]) == 2
    for messages, order in zip(sent, ("ab", "ba")):
        assert messages == [{"role": "system", "content": POLICY_SYSTEM},
                            {"role": "user", "content": ft_sweep.render(case, order)[0]}]
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(r["parse_ok"] and r["confidence"] == 0.7 for r in records)
    assert {r["endorses"] for r in records} == {True, False}
