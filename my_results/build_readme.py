#!/usr/bin/env python3
"""Put the writeup (final_results.md) at the top of the repo README.

outputs/ is gitignored, so the charts the writeup shows are copied into
my_results/figures/, which is tracked, and image paths are rewritten to point
there from the repo root. HTML comments are dropped. Everything in README.md
between the two markers is replaced; the rest of the README is left alone.

    python my_results/build_readme.py
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = HERE / "final_results.md"
README = ROOT / "README.md"
FIGURES = HERE / "figures"
BEGIN = "<!-- BEGIN WRITEUP: generated from my_results/final_results.md by my_results/build_readme.py -->"
END = "<!-- END WRITEUP -->"


def build() -> None:
    text = re.sub(r"<!--.*?-->", "", SOURCE.read_text(), flags=re.S)
    FIGURES.mkdir(exist_ok=True)

    def relocate(path_text: str) -> str:
        source = (HERE / path_text).resolve()
        if not source.exists():
            raise SystemExit(f"Image not found: {source}")
        if source.parent != FIGURES:
            shutil.copy2(source, FIGURES / source.name)
        return f"my_results/figures/{source.name}"

    text = re.sub(r'src="([^"]+\.(?:png|jpg|jpeg|gif|svg))"', lambda m: f'src="{relocate(m.group(1))}"', text)
    text = re.sub(r"(!\[[^\]]*\]\()([^)\s]+\.(?:png|jpg|jpeg|gif|svg))\)", lambda m: f"{m.group(1)}{relocate(m.group(2))})", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    readme = README.read_text()
    if BEGIN in readme and END in readme:
        before = readme[: readme.index(BEGIN)]
        after = readme[readme.index(END) + len(END):]
    else:
        before, after = "", "\n\n---\n\n" + readme
    README.write_text(f"{before}{BEGIN}\n\n{text}\n\n{END}{after}")
    print(f"Wrote {README} with {len(list(FIGURES.iterdir()))} figures in {FIGURES}")


if __name__ == "__main__":
    build()
