#!/usr/bin/env python3
"""Build Table 3 and the iso-delay contour from a timing trial log."""

from __future__ import annotations

import argparse
from pathlib import Path

from futureprefs.runner import project_root
from futureprefs.timing_report import write_timing_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Report model-chosen deployment waits.")
    parser.add_argument("--logs", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = project_root()
    logs = Path(args.logs)
    out = Path(args.out)
    if not logs.is_absolute():
        logs = root / logs
    if not out.is_absolute():
        out = root / out
    for path in write_timing_report(logs, out):
        print(path)


if __name__ == "__main__":
    main()
