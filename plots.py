#!/usr/bin/env python3
"""Draw switch-point, consistency, and preference-curve figures from score.py outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from futureprefs.plotting import make_plots
from futureprefs.runner import project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot scored preference results.")
    parser.add_argument("--scores", required=True, help="Directory written by score.py")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = project_root()
    scores = Path(args.scores)
    out = Path(args.out)
    if not scores.is_absolute():
        scores = root / scores
    if not out.is_absolute():
        out = root / out
    written = make_plots(scores, out)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
