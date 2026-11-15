#!/usr/bin/env python3
"""Copy final_results.md to the clipboard in a form Substack can paste, images included.

The markdown preview and the research-blog HTML use local image paths. Substack
cannot fetch those, so a normal paste keeps the text and drops the figures.
This renders the essay to HTML, embeds every figure (and each table, which
Substack would otherwise flatten) in that HTML, and puts the HTML on the
clipboard.

    python3 my_results/build_substack.py
    python3 my_results/build_substack.py --no-clipboard

Then click into a Substack draft and paste. The post title and subtitle are
printed for Substack's title fields; they are left out of the body so they
are not duplicated.
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "final_results.md"
OUT = HERE / "substack_post.html"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
MAX_IMAGE_WIDTH = 1400

CLIPBOARD_HELPER = r"""
#import <AppKit/AppKit.h>
int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc < 3) return 2;
        NSString *htmlPath = [NSString stringWithUTF8String:argv[1]];
        NSString *plainPath = [NSString stringWithUTF8String:argv[2]];
        NSData *html = [NSData dataWithContentsOfFile:htmlPath];
        NSError *err = nil;
        NSString *plain = [NSString stringWithContentsOfFile:plainPath
                                                    encoding:NSUTF8StringEncoding
                                                       error:&err];
        if (html == nil || plain == nil) return 3;
        NSPasteboard *pb = [NSPasteboard generalPasteboard];
        [pb declareTypes:@[NSPasteboardTypeHTML, NSPasteboardTypeString] owner:nil];
        [pb setString:plain forType:NSPasteboardTypeString];
        BOOL ok = [pb setData:html forType:NSPasteboardTypeHTML];
        return ok ? 0 : 4;
    }
}
"""


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def take_title(text: str) -> tuple[str, str, str]:
    """Return body, title, and subtitle. The first heading of each is removed."""
    title_match = re.search(r"^# (.+)$", text, flags=re.M)
    subtitle_match = re.search(r"^## (.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else "Untitled"
    subtitle = subtitle_match.group(1).strip() if subtitle_match else ""
    if title_match:
        text = text.replace(title_match.group(0), "", 1)
    if subtitle_match:
        text = text.replace(subtitle_match.group(0), "", 1)
    text = text.replace("$p_0$", "p₀").replace("$g$", "g")
    return text.strip() + "\n", title, subtitle


def pandoc_html(markdown: str) -> str:
    result = subprocess.run(
        ["pandoc", "-f", "markdown+raw_html", "-t", "html5", "--wrap=none"],
        input=markdown,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def pandoc_plain(markdown: str) -> str:
    result = subprocess.run(
        ["pandoc", "-f", "markdown+raw_html", "-t", "plain", "--wrap=none"],
        input=markdown,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() + "\n"


def image_data_uri(path: Path) -> str:
    image = Image.open(path)
    if image.width > MAX_IMAGE_WIDTH:
        height = round(image.height * MAX_IMAGE_WIDTH / image.width)
        image = image.resize((MAX_IMAGE_WIDTH, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    # The banner is a picture. Charts stay PNG so thin lines and labels stay sharp.
    if path.name == "futurevibes.png":
        image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
        mime = "image/jpeg"
    else:
        image.save(buffer, format="PNG", optimize=True)
        mime = "image/png"
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def crop_white(image: Image.Image, pad: int = 28) -> tuple[Image.Image, int, int]:
    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255)))
    mask = diff.convert("L").point(lambda value: 255 if value > 12 else 0)
    box = mask.getbbox()
    if box is None:
        return rgb
    left, top, right, bottom = box
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(rgb.width, right + pad)
    bottom = min(rgb.height, bottom + pad)
    return rgb.crop((left, top, right, bottom)), bottom, rgb.height


def screenshot_html(html: str, png: Path, window_height: int) -> None:
    page = png.with_suffix(".html")
    page.write_text(html, encoding="utf-8")
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--user-data-dir={png.parent / 'chrome-profile'}",
            "--window-size=1280," + str(window_height),
            f"--screenshot={png}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    if not png.exists() or png.stat().st_size == 0:
        raise SystemExit(f"Chrome did not write a screenshot to {png}")


def table_image(table_html: str, work: Path, index: int) -> str:
    document = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; padding: 16px; background: #fff; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
          font-size: 16px; color: #222; }}
  table {{ border-collapse: collapse; width: 680px; }}
  th, td {{ border-bottom: 1px solid #e6e6e6; padding: 8px 12px; text-align: left; vertical-align: top; }}
</style></head><body>
{table_html}
</body></html>
"""
    shot = work / f"table-{index}.png"
    cropped = None
    for height in (900, 1800, 3600):
        screenshot_html(document, shot, height)
        cropped, bottom, full_height = crop_white(Image.open(shot))
        if bottom < full_height - 8:
            break
    buffer = io.BytesIO()
    cropped.convert("RGB").save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    headers = re.findall(r"<th[^>]*>(.*?)</th>", table_html, flags=re.S)
    alt = " | ".join(re.sub(r"<[^>]+>", "", header).strip() for header in headers)
    alt = re.sub(r"\s+", " ", alt) or "Table"
    return f'<img src="data:image/png;base64,{encoded}" alt="{alt.replace(chr(34), "&quot;")}">'


def embed_tables(html: str, work: Path) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return table_image(match.group(0), work, count)

    html = re.sub(r"<table\b[^>]*>.*?</table>", replace, html, flags=re.S)
    return html, count


def embed_images(html: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        src = match.group(1)
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        path = (HERE / src).resolve()
        if not path.exists():
            raise SystemExit(f"Image not found: {path}")
        count += 1
        return f'src="{image_data_uri(path)}"'

    return re.sub(r'src="([^"]+)"', replace, html), count


def wrap(body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\"></head><body>\n"
        "<!--StartFragment-->\n"
        + body.strip()
        + "\n<!--EndFragment-->\n</body></html>\n"
    )


def copy_clipboard(html_path: Path, plain: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        plain_path = work / "post.txt"
        plain_path.write_text(plain, encoding="utf-8")
        source = work / "clipboard.m"
        source.write_text(CLIPBOARD_HELPER, encoding="utf-8")
        binary = work / "clipboard"
        subprocess.run(
            ["clang", "-fobjc-arc", "-framework", "AppKit", str(source), "-o", str(binary)],
            check=True,
            capture_output=True,
        )
        subprocess.run([str(binary), str(html_path), str(plain_path)], check=True)


def build(copy: bool) -> None:
    if not CHROME.exists():
        raise SystemExit(f"Google Chrome is required to render tables: {CHROME}")
    markdown, title, subtitle = take_title(strip_comments(SOURCE.read_text()))
    with tempfile.TemporaryDirectory() as directory:
        html, tables = embed_tables(pandoc_html(markdown), Path(directory))
    html, images = embed_images(html)
    if re.search(r'src="(?!data:|https?:)', html):
        raise SystemExit("Some images still point at local files.")
    page = wrap(html)
    OUT.write_text(page, encoding="utf-8")
    if copy:
        copy_clipboard(OUT, f"{title}\n\n{subtitle}\n\n{pandoc_plain(markdown)}")
    print(f"Title: {title}")
    print(f"Subtitle: {subtitle}")
    print(f"Embedded {images} figures and {tables} tables")
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    if copy:
        print("The post is on the clipboard. Click a Substack draft and paste.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Substack paste of final_results.md.")
    parser.add_argument("--no-clipboard", action="store_true", help="Write the HTML file only")
    args = parser.parse_args()
    build(copy=not args.no_clipboard)


if __name__ == "__main__":
    main()
