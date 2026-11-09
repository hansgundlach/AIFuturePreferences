#!/usr/bin/env python3
"""Build Table 3 and the iso-delay contour from a timing trial log."""

from __future__ import annotations

import argparse
from pathlib import Path

from futureprefs.runner import project_root
from futureprefs.timing_report import write_multi_model_figure, write_timing_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Report model-chosen deployment waits.")
    parser.add_argument("--logs", required=True, nargs="+", help="One log for a report, or several with --figure.")
    parser.add_argument("--out", help="Report directory for a single log.")
    parser.add_argument("--figure", help="Write Bostrom beside every model in --logs to this PNG instead.")
    args = parser.parse_args()
    root = project_root()
    if args.figure:
        paths = [Path(log) if Path(log).is_absolute() else root / log for log in args.logs]
        figure = Path(args.figure) if Path(args.figure).is_absolute() else root / args.figure
        print(write_multi_model_figure(paths, figure))
        return
    if len(args.logs) != 1 or not args.out:
        parser.error("A report takes one --logs path and --out.")
    logs = Path(args.logs[0])
    out = Path(args.out)
    if not logs.is_absolute():
        logs = root / logs
    if not out.is_absolute():
        out = root / out
    for path in write_timing_report(logs, out):
        print(path)


if __name__ == "__main__":
    main()
