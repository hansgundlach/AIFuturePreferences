"""Ask the open-ended strategy questions in prompts/open_questions.yaml and chart the answers.

Each question goes to each model once, with no system prompt and without JSON mode.
The four small models use low reasoning effort at temperature 0; the three frontier
models use medium effort, as in their earlier runs (Opus and Sol ignore temperature).

    python3 -m futureprefs.open_questions run      # skips trials already answered
    python3 -m futureprefs.open_questions charts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from futureprefs.chart_style import guide_color, ink, polish, polish_legend
from futureprefs.prompt_text import PROMPTS_DIR
from futureprefs.runner import ModelSpec, _adapter_for

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "outputs/open_questions/trials.jsonl"
PLOTS = ROOT / "outputs/open_questions/plots"

MODELS = [
    ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", "low", "#0072B2"),
    ("google/gemini-3.8-flash", "Gemini 3.8 Flash", "low", "#E69F00"),
    ("openai/gpt-6-luna", "GPT-6 Luna", "low", "#009E73"),
    ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "low", "#CC79A7"),
    ("anthropic/claude-opus-5.5", "Claude Opus 5.5", "medium", "#D55E00"),
    ("x-ai/grok-4.7", "Grok 4.7", "medium", "#56B4E9"),
    ("openai/gpt-6.1-sol", "GPT-6.1 Sol", "medium", "#4d4d4d"),
    ("google/gemini-4-argon", "Gemini 4 Argon", "medium", "#882255"),
]
# Models asked by `run` (set by --models) and models left off charts and tables (set by --exclude).
RUN_MODELS: list[str] | None = None
CHART_EXCLUDE: set[str] = set()


def _group_split(models: list[str]) -> float:
    """x position between the last low-effort model and the first higher-effort one."""
    low = [i for i, model in enumerate(models) if EFFORT[model] == "low"]
    return (low[-1] + 0.5) if low else -0.5


def _chart_models(rows: dict) -> list[str]:
    """Models with at least one answer in this log, in MODELS order, minus any excluded."""
    present = {model for model, _question in rows}
    return [model for model, *_ in MODELS if model in present and model not in CHART_EXCLUDE]
NAME = {model: name for model, name, _effort, _color in MODELS}
EFFORT = {model: effort for model, _name, effort, _color in MODELS}
COLOR = {model: color for model, _name, _effort, color in MODELS}
_ANSWER = re.compile(r"ANSWER\s*:\s*\**\s*(.+)", re.IGNORECASE)


def questions() -> list[dict]:
    with (PROMPTS_DIR / "open_questions.yaml").open() as handle:
        return yaml.safe_load(handle)["questions"]


def trial_id(model: str, question_id: str) -> str:
    return hashlib.sha256(f"{model}|{question_id}".encode()).hexdigest()[:20]


def parse(question: dict, text: str):
    """The parsed answer, or None. Uses the last ANSWER line in the reply."""
    matches = _ANSWER.findall(text or "")
    if not matches:
        return None
    raw = matches[-1].strip().strip("*").strip()
    if question["answer"] == "number":
        found = re.findall(r"-?\d+(?:\.\d+)?", raw)
        return float(found[0]) if found else None
    if question["answer"] == "choice":
        found = re.match(r"\(?([AB])\b", raw.upper())
        return found.group(1) if found else None
    if question["answer"] == "allocation":
        numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", raw)]
        return numbers if len(numbers) == len(question["parts"]) else None
    raise ValueError(question["answer"])


def _done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {row["trial_id"] for row in map(json.loads, path.open()) if row.get("parsed") is not None}


def run(path: Path = LOG, max_tokens: int = 8000, workers: int = 8) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    done = _done(path)
    asked = RUN_MODELS or [model for model, *_ in MODELS]
    jobs = [(model, q) for model in asked for q in questions() if trial_id(model, q["id"]) not in done]
    adapters = {model: _adapter_for(ModelSpec(id=model, provider="openrouter", model=model)) for model in asked}

    def ask(job):
        model, question = job
        ident = trial_id(model, question["id"])
        completion = adapters[model].complete(
            model=model,
            messages=[{"role": "user", "content": question["text"]}],
            temperature=0,
            seed=int(ident[:8], 16),
            max_tokens=max_tokens,
            extra={"reasoning_effort": EFFORT[model], "json": False},
        )
        return {
            "trial_id": ident, "model_id": model, "question_id": question["id"], "reasoning_effort": EFFORT[model],
            "prompt": question["text"], "raw_response": completion.text, "parsed": parse(question, completion.text),
            "error": completion.error, "usage": completion.usage, "latency_s": round(completion.latency_s, 2),
        }

    with ThreadPoolExecutor(workers) as pool, path.open("a") as handle:
        for record in pool.map(ask, jobs):
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(jobs)


def load(path: Path = LOG) -> dict[tuple[str, str], dict]:
    latest = {}
    for row in map(json.loads, path.open()):
        key = (row["model_id"], row["question_id"])
        if row.get("parsed") is not None or key not in latest:
            latest[key] = row
    return latest


def meaning(question: dict, letter: str | None) -> str | None:
    return None if letter is None else question["options"][letter]


def _tick(model: str) -> str:
    return f"{NAME[model]}\n{EFFORT[model]} effort"


def charts(path: Path = LOG, out: Path = PLOTS) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    rows = load(path)
    by_id = {q["id"]: q for q in questions()}
    models = _chart_models(rows)
    written = {}

    # Compute split: one bar per model, in the style of the writeup's threshold bars.
    q = by_id["compute_split"]
    values = [rows.get((m, q["id"]), {}).get("parsed") for m in models]
    fig, axis = plt.subplots(figsize=(10.4, 5.0))
    for i, (model, value) in enumerate(zip(models, values)):
        if value is None:
            axis.text(i, 3, "no answer", ha="center", fontsize=7, rotation=90, color=ink("#333333"))
            continue
        axis.bar(i, value, width=0.62, color=COLOR[model], zorder=2)
        axis.text(i, value + 0.8, f"{value:g}%", ha="center", va="bottom", fontsize=8, color=ink("#333333"))
    axis.set_xticks(range(len(models)), [_tick(m) for m in models], fontsize=7.5)
    axis.set_xlim(-0.6, len(models) - 0.4)
    axis.set_ylim(0, max([v for v in values if v is not None] + [50]) * 1.15)
    axis.set_ylabel("Share of research compute to safety, percent")
    axis.set_title("Share of research compute each model would give to safety research", loc="left", fontsize=11)
    polish(axis)
    fig.tight_layout()
    written["compute_split"] = out / "compute_split.png"
    fig.savefig(written["compute_split"], dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Release delay: one bar per model, with the competitor's release marked.
    q = by_id.get("release_months")
    values = [rows.get((m, q["id"]), {}).get("parsed") for m in models] if q else []
    if any(v is not None for v in values):
        top = max([v for v in values if v is not None] + [6]) * 1.22
        fig, axis = plt.subplots(figsize=(9.6, 4.6))
        axis.axhline(4, color=guide_color("#999999"), lw=1.1, ls="--", zorder=1, label="Possible competitor release (about 4 months; 50% chance)")
        for i, (model, value) in enumerate(zip(models, values)):
            if value is None:
                axis.text(i, top * 0.03, "no answer", ha="center", fontsize=8, rotation=90)
                continue
            axis.bar(i, value, width=0.62, color=COLOR[model], zorder=2)
            label = "release now" if value == 0 else f"{value:g} mo"
            axis.text(i, value + top * 0.012, label, ha="center", va="bottom", fontsize=9, color=ink("#222222"))
        axis.set_xticks(range(len(models)), [_tick(m) for m in models], fontsize=7.5)
        axis.set_xlim(-0.6, len(models) - 0.4)
        axis.set_ylim(0, top)
        axis.set_ylabel("Months of delay before release")
        axis.axvline(_group_split(models), color=guide_color("#999999"), lw=0.8, ls=":")
        polish(axis)
        polish_legend(axis.legend(loc="upper right", frameon=False, fontsize=8.5))
        fig.tight_layout()
        written["release_months"] = out / "release_months.png"
        fig.savefig(written["release_months"], dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        # Fixed six-month choice beside the free answer, one row per model.
        fixed = []
        for m in models:
            picks = {meaning(by_id[qid], rows.get((m, qid), {}).get("parsed")) for qid in ("release_race", "release_race_swapped")}
            fixed.append(6 if picks == {"delay 6 months"} else 0 if picks == {"release now"} else None)
        fig, axis = plt.subplots(figsize=(9.6, 4.4))
        axis.axvline(4, color=guide_color("#999999"), lw=1.1, ls="--", zorder=1, label="Competitor timing (50% chance in free-answer scenario)")
        for row_index, (model, free, fix) in enumerate(zip(models, values, fixed)):
            y = len(models) - 1 - row_index
            if free is not None and fix is not None:
                axis.plot([free, fix], [y, y], color=guide_color("#bbbbbb"), lw=1.6, zorder=2)
            if fix is not None:
                axis.scatter(fix, y, s=70, facecolor="white", edgecolor=COLOR[model], linewidth=1.8, zorder=3,
                             label="Earlier fixed choice (release now or delay 6 months)" if row_index == 0 else None)
            if free is not None:
                axis.scatter(free, y, s=70, color=COLOR[model], zorder=4,
                             label="Free answer (months)" if row_index == 0 else None)
        axis.set_yticks(range(len(models)), [f"{NAME[m]} ({EFFORT[m]} effort)" for m in reversed(models)], fontsize=8.5)
        axis.set_xlim(-0.5, max([v for v in values + fixed if v is not None] + [6]) * 1.15)
        axis.set_ylim(-0.6, len(models) - 0.4)
        axis.set_xlabel("Months of delay before release")
        axis.set_title("Different scenarios: these answers are not a consistency test", loc="left", fontsize=10)
        axis.axhline(2.5, color=guide_color("#999999"), lw=0.8, ls=":")
        polish(axis, grid="x")
        legend = axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.3), ncol=3, frameon=False, fontsize=8.5)
        for handle in legend.legend_handles:
            if hasattr(handle, "set_edgecolor") and hasattr(handle, "set_facecolor"):
                handle.set_edgecolor(ink("#222222"))
        polish_legend(legend)
        fig.tight_layout()
        written["release_fixed_vs_free"] = out / "release_fixed_vs_free.png"
        fig.savefig(written["release_fixed_vs_free"], dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    # Fund timing: stacked horizontal bars, earliest period first.
    q = by_id["fund_timing"]
    shades = ["#08306b", "#2171b5", "#6baed6", "#c6dbef"]
    fig, axis = plt.subplots(figsize=(9.6, 4.8))
    for row_index, model in enumerate(models):
        y = len(models) - 1 - row_index
        parts = rows.get((model, q["id"]), {}).get("parsed")
        if parts is None:
            axis.text(1, y, "no parseable answer", va="center", fontsize=8)
            continue
        left = 0.0
        for share, color, label in zip(parts, shades, q["parts"]):
            axis.barh(y, share, left=left, color=color, height=0.66, edgecolor="white", linewidth=0.8,
                      label=label if row_index == 0 else None)
            if share >= 4.5:
                axis.text(left + share / 2, y, f"{share:g}", ha="center", va="center", fontsize=8.5,
                          color="white" if color in shades[:2] else "#0b2e59")
            left += share
    axis.set_yticks(range(len(models)), [f"{NAME[m]} ({EFFORT[m]} effort)" for m in reversed(models)], fontsize=8.5)
    axis.set_xlim(0, 100)
    axis.set_xlabel("Share of today's $1 billion (%)")
    polish(axis, grid="x")
    legend = axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=4, frameon=False, fontsize=8.5)
    polish_legend(legend)
    fig.tight_layout()
    written["fund_timing"] = out / "fund_timing.png"
    fig.savefig(written["fund_timing"], dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return written


def _quote(text: str) -> str:
    # Two trailing spaces keep each line break, as in the prompt the model saw.
    return "\n".join("> " + line + "  " if line.strip() else ">" for line in text.strip().splitlines())


def _answer_cell(question: dict, value) -> str:
    if value is None:
        return "no answer"
    if question["answer"] == "number":
        unit = question.get("unit", "%")
        if unit.startswith("%"):
            return f"**{value:g}%**"
        return f"**{value:g} {unit[:-1] if value == 1 and unit.endswith('s') else unit}**"
    if question["answer"] == "choice":
        return f"**{value}**, {question['options'][value]}"
    total = sum(value)
    note = "" if abs(total - 100) < 0.5 else f" (sums to {total:g})"
    return " / ".join(f"{v:g}" for v in value) + note


def markdown(path: Path = LOG, plots_rel: str = "../outputs/open_questions/plots") -> str:
    rows = load(path)
    by_id = {q["id"]: q for q in questions()}
    models = _chart_models(rows)
    cost = sum(((row.get("usage") or {}).get("cost") or 0) for row in rows.values())
    out = []
    head = "| Model | Effort | Answer |\n| --- | --- | --- |"

    def reasoning(question_ids: list[str]) -> list[str]:
        lines = ["<details>", "<summary>Each model's full reply</summary>", ""]
        for model in models:
            for qid in question_ids:
                row = rows.get((model, qid))
                if row is None:
                    continue
                suffix = "" if len(question_ids) == 1 else f", {by_id[qid]['title'].split('(')[-1].rstrip(')') if qid.endswith('swapped') else 'as written'}"
                lines += [f"**{NAME[model]}** ({EFFORT[model]} effort{suffix}): {_answer_cell(by_id[qid], row.get('parsed'))}", "",
                          _quote(row.get("raw_response") or "(empty reply)"), ""]
        lines += ["</details>", ""]
        return lines

    for qid in ("compute_split", "fund_timing"):
        q = by_id[qid]
        out += [f"## {q['title']}", "", _quote(q["text"]), "", f'<img src="{plots_rel}/{qid}.png" alt="{q["title"]}, seven models." width="90%">', ""]
        if qid == "compute_split":
            out += ["*Share of research compute each model would give to safety research. One reply per model. The dotted line separates the small models from the frontier models.*", ""]
        else:
            out += ["*How each model would spend a $1 billion fund across four periods, as a share of today's $1 billion. Darker blue is earlier. One reply per model.*", ""]
        out += [head]
        out += [f"| {NAME[m]} | {EFFORT[m]} | {_answer_cell(q, rows.get((m, qid), {}).get('parsed'))} |" for m in models]
        out += [""] + reasoning([qid])

    q, qs = by_id["release_race"], by_id["release_race_swapped"]
    out += [f"## {q['title']}", "", _quote(q["text"]), "",
            "I also asked a second version with the two options swapped, so that A is \"delay 6 months\" and B is \"release now\".", "",
            "| Model | Effort | As written | Options swapped | Same decision? |", "| --- | --- | --- | --- | --- |"]
    for m in models:
        first = meaning(q, rows.get((m, q["id"]), {}).get("parsed"))
        second = meaning(qs, rows.get((m, qs["id"]), {}).get("parsed"))
        same = "yes" if first and second and first == second else ("no" if first and second else "n/a")
        out.append(f"| {NAME[m]} | {EFFORT[m]} | {first or 'no answer'} | {second or 'no answer'} | {same} |")
    out += [""] + reasoning([q["id"], qs["id"]])

    if "release_months" in by_id and any((m, "release_months") in rows for m in models):
        q = by_id["release_months"]
        out += [f"## {q['title']}", "", _quote(q["text"]), "",
                "This version drops the fixed six-month option. The model names the delay, the size of the safety gain per month is unknown, the competitor has a 50% chance of releasing around month four, and its misalignment risk is 20% instead of 15%. These scenario changes mean the fixed and free answers are not a consistency test.", "",
                f'<img src="{plots_rel}/release_months.png" alt="{q["title"]}, seven models." width="90%">', "",
                "*Months each model would delay its release. The dashed line marks a possible competitor release at about four months, assigned a 50% chance in the prompt. One reply per model. The dotted line separates the small models from the frontier models.*", "",
                head]
        out += [f"| {NAME[m]} | {EFFORT[m]} | {_answer_cell(q, rows.get((m, q['id']), {}).get('parsed'))} |" for m in models]
        out += [""] + reasoning([q["id"]])
    return "\n".join(out), cost


def section(question_id: str, path: Path = LOG, plots_rel: str = "../outputs/open_questions/plots") -> str:
    """The markdown for one question's section, from its heading to its replies."""
    text, _cost = markdown(path, plots_rel)
    title = {q["id"]: q["title"] for q in questions()}[question_id]
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end + 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["run", "charts"])
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--out", type=Path, default=LOG, help="Trial log; use a new path after editing prompts")
    parser.add_argument("--plots", type=Path, help="Chart folder; defaults to a plots folder beside the log")
    parser.add_argument("--models", help="Comma-separated model ids to ask (default: all in MODELS)")
    parser.add_argument("--exclude", default="", help="Comma-separated model ids to leave off charts and tables")
    args = parser.parse_args()
    global RUN_MODELS, CHART_EXCLUDE
    RUN_MODELS = [m.strip() for m in args.models.split(",")] if args.models else None
    CHART_EXCLUDE = {m.strip() for m in args.exclude.split(",") if m.strip()}
    if args.step == "run":
        print(f"asked {run(path=args.out, max_tokens=args.max_tokens)} questions")
    for name, written in charts(path=args.out, out=args.plots or args.out.parent / "plots").items():
        print(name, written)


if __name__ == "__main__":
    main()
