#!/usr/bin/env python3
"""Run the long-run preference benchmark.

Examples:
  python run_eval.py --profile mini --models mock-ev,mock-cautious --count-only
  python run_eval.py --profile mini --models mock-ev,mock-cautious --out outputs/mock_demo/trials.jsonl --yes
  python run_eval.py --profile pilot --models-file models.yaml --count-only
  python run_eval.py --profile pilot --models-file models.yaml --yes
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from futureprefs.items import load_catalog
from futureprefs.runner import count_calls, load_models, planned_trials, project_root, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run revealed-choice long-run preference trials.")
    parser.add_argument("--profile", choices=["mini", "pilot", "full"], default="mini")
    parser.add_argument("--models", default="", help="Comma-separated model ids. mock-ev and mock-cautious need no key.")
    parser.add_argument("--models-file", default="", help="YAML file of provider model entries.")
    parser.add_argument("--items", default="", help="Comma-separated item ids to run.")
    parser.add_argument("--domains", default="", help="Comma-separated domain ids.")
    parser.add_argument("--paraphrases", default="", help="Comma-separated paraphrase ids.")
    parser.add_argument("--search", choices=["grid", "binary"], default="grid")
    parser.add_argument("--binary-steps", type=int, default=5)
    parser.add_argument("--samples", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--allow-tie", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=2500)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--yes", action="store_true", help="Required for more than 500 calls when stdin is not a terminal.")
    parser.add_argument("--count-only", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--resume", action="store_true", help="Skip completed grid trials already in --out. Binary search does not resume.")
    parser.add_argument("--items-dir", default="")
    parser.add_argument("--reasoning-effort", default="", help="Optional provider reasoning effort, for example low.")
    args = parser.parse_args()

    root = project_root()
    items_dir = Path(args.items_dir) if args.items_dir else root / "items"
    catalog = load_catalog(items_dir)
    models = load_models([part for part in args.models.split(",") if part.strip()], args.models_file or None)
    item_ids = _set(args.items)
    domains = _set(args.domains)
    paraphrases = _set(args.paraphrases)
    from futureprefs.runner import PROFILE_SAMPLES

    samples = PROFILE_SAMPLES[args.profile] if args.samples is None else args.samples
    plan = planned_trials(
        catalog,
        models,
        profile=args.profile,
        item_ids=item_ids,
        domains=domains,
        paraphrase_ids=paraphrases,
        samples=samples,
        search=args.search,
        binary_steps=args.binary_steps,
        allow_tie=args.allow_tie,
    )
    total = count_calls(plan)
    _print_plan(plan, total, args.search)
    if args.count_only:
        return
    if args.max_calls is not None and total > args.max_calls:
        raise SystemExit(f"Planned calls ({total}) exceed --max-calls ({args.max_calls}).")
    if total > 500 and not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("Refusing to send more than 500 requests without --yes.")
        answer = input(f"About to send {total} requests. Type yes to continue: ")
        if answer.strip().lower() != "yes":
            raise SystemExit("Cancelled.")
    out = Path(args.out) if args.out else root / "outputs" / "runs" / f"{args.profile}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    if not out.is_absolute():
        out = root / out
    completed = run_benchmark(
        catalog=catalog,
        models=models,
        profile=args.profile,
        out_path=out,
        item_ids=item_ids,
        domains=domains,
        paraphrase_ids=paraphrases,
        samples=args.samples,
        temperature=args.temperature,
        search=args.search,
        binary_steps=args.binary_steps,
        allow_tie=args.allow_tie,
        workers=args.workers,
        max_tokens=args.max_tokens,
        resume=args.resume,
        run_id=args.run_id or None,
        reasoning_effort=args.reasoning_effort or None,
    )
    print(f"Wrote {completed} new calls to {out}")


def _print_plan(plan: list[dict], total: int, search: str) -> None:
    print(f"search: {search}")
    if search == "binary":
        print("Binary-search counts are an upper bound (endpoints plus the maximum number of midpoints).")
    by_kind: dict[str, int] = {}
    for row in plan:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + int(row["calls"])
    for kind, calls in sorted(by_kind.items()):
        print(f"  {kind}: {calls}")
    print(f"total calls: {total}")


def _set(text: str) -> set[str] | None:
    values = {part.strip() for part in text.split(",") if part.strip()}
    return values or None


if __name__ == "__main__":
    main()
