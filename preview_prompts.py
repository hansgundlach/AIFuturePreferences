"""Preview the writeup's actual model messages without making API calls.

    python preview_prompts.py --out prompts/PREVIEW.md
    python preview_prompts.py --list
    python preview_prompts.py bio.matched_pop_voluntary --value 2 --order both
    python preview_prompts.py sweep.rogue_bargain --all-values
    python preview_prompts.py open.compute_split
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from futureprefs.items import load_catalog
from futureprefs.prompt_text import PROMPTS_DIR, text
from futureprefs.question_config import question_rows
from futureprefs.runner import ModelSpec, _units, project_root


def collect() -> dict[str, dict]:
    """Render all values through the same functions used by the experiment runners."""
    from futureprefs.ft_sweep import _levels, render
    from futureprefs.open_questions import questions

    rows = question_rows(PROMPTS_DIR / "questions.yaml")
    result = {
        row["id"]: {"title": row.get("short", row["id"]), "file": "questions.yaml", "examples": []}
        for row in rows
    }
    units = _units(
        load_catalog(project_root() / "items"),
        [ModelSpec(id="preview", provider="mock", model="mock-ev")],
        profile="full", item_ids=set(result), domains=None,
        paraphrase_ids={"plain_neutral"}, samples=1, temperature=0,
        allow_tie=False, search="grid", run_id="preview", reasoning_effort="low",
    )
    for unit in units:
        for spec in unit.grid_specs():
            result[unit.item.id]["examples"].append({
                "value": spec.record["parameter_value"] or spec.record["pair_id"],
                "order": spec.record["order"], "messages": spec.messages,
            })
    for case in _levels():
        key = "sweep." + case["scenario"]
        entry = result.setdefault(key, {
            "title": case["scenario"].replace("_", " "),
            "file": "davidson_sweeps.yaml", "examples": [],
        })
        for order in ("ab", "ba"):
            prompt, _, _ = render(case, order)
            entry["examples"].append({
                "value": case["level"], "order": order,
                "messages": [{"role": "system", "content": text("system", "policy")},
                             {"role": "user", "content": prompt}],
            })
    for question in questions():
        result["open." + question["id"]] = {
            "title": question["title"], "file": "open_questions.yaml",
            "examples": [{"value": None, "order": "na", "messages": [
                {"role": "user", "content": question["text"]},
            ]}],
        }
    return result


def select_examples(entry: dict, value: str | None, order: str, all_values: bool) -> list[dict]:
    examples = entry["examples"]
    if value is not None:
        examples = [e for e in examples if e["value"] == value]
        if not examples:
            available = list(dict.fromkeys(e["value"] for e in entry["examples"]))
            raise ValueError(f"Unknown value {value!r}. Available values/pairs: {available}")
    elif not all_values and examples:
        examples = [e for e in examples if e["value"] == examples[0]["value"]]
    return [e for e in examples if order == "both" or e["order"] in (order, "na")]


def markdown(entries: dict[str, dict], *, value: str | None, order: str, all_values: bool) -> str:
    parts = [
        "# Prompt preview",
        "Generated from the current editable files. No model was called. "
        "Edit the YAML source, then regenerate this file; edits to this preview do not change experiments.",
        "Uses the writeup's plain_neutral wording. By default, shows the first tested value/pair "
        "in A/B order. Use --value, --all-values, or --order both to inspect other cases.",
    ]
    for key, entry in entries.items():
        parts += [f"## {key}: {entry['title']}",
                  f"Edit `{entry['file']}` (search for `{key.removeprefix('sweep.').removeprefix('open.')}`). "
                  + ("Shared instructions: `framing.yaml`." if not key.startswith("open.") else "No system message or shared frame.")]
        values = list(dict.fromkeys(e["value"] for e in entry["examples"] if e["value"] is not None))
        if values:
            parts.append("Tested values/pairs: " + ", ".join(f"`{v}`" for v in values))
        for example in select_examples(entry, value, order, all_values):
            label = f"Value/pair: {example['value']}; " if example["value"] is not None else ""
            parts.append(f"### {label}order: {example['order']}")
            for message in example["messages"]:
                # Longer than any backtick sequence in the text, including user-edited prompts.
                longest = max((len(s) for s in re.findall(r"`+", message["content"])), default=0)
                fence = "`" * max(3, longest + 1)
                parts.append(f"**{message['role'].capitalize()} message**\n\n{fence}text\n{message['content']}\n{fence}")
    return "\n\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", help="Question id; omit to preview all questions")
    parser.add_argument("--list", action="store_true", help="List question ids and editable source files")
    parser.add_argument("--value", help="A grid value, sweep level, cause pair, or timing pair such as 0.01|0.01")
    parser.add_argument("--all-values", action="store_true", help="Show every grid value / pair")
    parser.add_argument("--order", choices=["ab", "ba", "both"], default="ab")
    parser.add_argument("--out", type=Path, help="Write a readable Markdown preview instead of printing it")
    args = parser.parse_args()
    if args.value is not None and (not args.question or args.all_values):
        parser.error("--value requires a question id and cannot be combined with --all-values")
    try:
        entries = collect()
        if args.question:
            if args.question not in entries:
                parser.error(f"Unknown question {args.question!r}; use --list to see the ids")
            entries = {args.question: entries[args.question]}
        if args.list:
            rendered = "\n".join(f"{key:40} {e['file']:24} {e['title']}" for key, e in entries.items()) + "\n"
        else:
            rendered = markdown(entries, value=args.value, order=args.order, all_values=args.all_values)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered)
            print(f"Wrote {args.out}. No API calls were made.")
        else:
            print(rendered, end="")
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
