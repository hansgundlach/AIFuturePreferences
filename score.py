#!/usr/bin/env python3
"""Score a JSONL trial log into switch points, consistency, and domain summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from futureprefs.runner import project_root
from futureprefs.scoring import load_records, score_records, write_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Score revealed-choice logs.")
    parser.add_argument("--logs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    root = project_root()
    logs = Path(args.logs)
    out = Path(args.out)
    if not logs.is_absolute():
        logs = root / logs
    if not out.is_absolute():
        out = root / out
    records = load_records(logs)
    result = score_records(records, n_boot=args.bootstrap, seed=args.seed)
    write_scores(result, out)
    print(f"Scored {len(records)} trials into {out}")


if __name__ == "__main__":
    main()
