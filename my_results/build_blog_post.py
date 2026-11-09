#!/usr/bin/env python3
"""Turn final_results.md into the research-blog post on hansgundlach.github.io.

Writes only inside <site>/research/what-futures-do-ai-models-prefer/:
the post's index.html and a figures/ folder with the images it shows.
HTML comments in the markdown are dropped, image paths are rewritten to
figures/, and math is rendered as MathML, so the page needs no scripts.

    python my_results/build_blog_post.py
    python my_results/build_blog_post.py --site /path/to/hansgundlach.github.io
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "final_results.md"
DEFAULT_SITE = Path("/Users/hansgundlach/Documents/PersonalProjects/hansgundlach.github.io")
SLUG = "what-futures-do-ai-models-prefer"
DATE = "November 4, 2026"
DESCRIPTION = (
    "An exploratory evaluation of which long-run futures AI models prefer: digital succession, "
    "human autonomy, cause prioritization, and pausing AI."
)

PAGE = """<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | Hans Gundlach</title>
  <meta name="description" content="{description}">
  <link rel="stylesheet" href="../research.css">
</head>

<body>
  <nav class="crumbs"><a href="../../index.html">Hans Gundlach</a> / <a href="../index.html">Research blog</a></nav>

  <header class="post-header">
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    <p class="byline">Hans Gundlach &nbsp;·&nbsp; {date}</p>
  </header>

  <article class="post">
{body}
  </article>

  <footer class="post-footer">
    <a href="../index.html">&larr; All posts</a>
  </footer>
</body>

</html>
"""


def build(site: Path) -> Path:
    text = SOURCE.read_text()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    title_match = re.search(r"^# (.+)$", text, flags=re.M)
    subtitle_match = re.search(r"^## (.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else "Untitled"
    subtitle = subtitle_match.group(1).strip() if subtitle_match else ""
    # The title and subtitle go in the page header, not the body.
    if title_match:
        text = text.replace(title_match.group(0), "", 1)
    if subtitle_match:
        text = text.replace(subtitle_match.group(0), "", 1)

    out_dir = site / "research" / SLUG
    figures = out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    def copy_image(path_text: str) -> str:
        source = (HERE / path_text).resolve()
        if not source.exists():
            raise SystemExit(f"Image not found: {source}")
        shutil.copy2(source, figures / source.name)
        return f"figures/{source.name}"

    text = re.sub(r'src="([^"]+\.(?:png|jpg|jpeg|gif|svg))"', lambda m: f'src="{copy_image(m.group(1))}"', text)
    text = re.sub(r"(!\[[^\]]*\]\()([^)\s]+\.(?:png|jpg|jpeg|gif|svg))\)", lambda m: f"{m.group(1)}{copy_image(m.group(2))})", text)

    body = subprocess.run(
        ["pandoc", "-f", "markdown+tex_math_dollars", "-t", "html5", "--mathml", "--wrap=none"],
        input=text,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Open outside links in a new tab, as the main site does.
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    body = "\n".join("    " + line if line else line for line in body.splitlines())

    page = PAGE.format(
        title=html.escape(title),
        subtitle=html.escape(subtitle),
        date=DATE,
        description=html.escape(DESCRIPTION),
        body=body,
    )
    out = out_dir / "index.html"
    out.write_text(page)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the research-blog post from final_results.md.")
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    args = parser.parse_args()
    print(build(args.site))


if __name__ == "__main__":
    main()
