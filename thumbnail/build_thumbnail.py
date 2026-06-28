"""
build_thumbnail.py
==================
Generate `template.html` from `temp_utf8.svg`.

Why this approach
-----------------
The source SVG (Suzume movie-poster thumbnail) mixes raster layers (18 PNG/JPG)
with intricate vector decoration (408 paths, masks, clip-paths, gradients).
Critically, some raster images are referenced *inside* <mask> definitions
(e.g. img_09 lives inside <mask id="7cb5445c43">), and the raster/vector
back-to-front Z-order is tightly interleaved. Splitting the file into
HTML-only <img> tags + a path-only SVG overlay would break the mask
references and the Z-order. So we keep the canvas as one inline SVG inside a
minimal HTML wrapper, just substituting the giant base64 data URIs with local
file refs (drastically shrinking the file and making every image individually
editable / replaceable).

Output: `template.html` (~ a few KB instead of the original 3.9 MB).
"""

from __future__ import annotations

import os
import re

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SVG_PATH = os.path.join(PROJECT_DIR, "temp_utf8.svg")
OUTPUT_PATH = os.path.join(PROJECT_DIR, "template.html")


# ---------------------------------------------------------------------------
# SVG cleaning
# ---------------------------------------------------------------------------
def clean_svg(svg: str) -> str:
    """Replace every inline `data:` URI (image/png and image/jpeg) with a
    relative reference to `images/img_NN.{png,jpg}`, numbered in the source
    order in which they appear in the document."""

    counter = {"n": 0}

    def _sub(match: re.Match[str]) -> str:
        mime = match.group("mime").lower()
        ext = "jpg" if "jpeg" in mime or "jpg" in mime else "png"
        idx = counter["n"]
        counter["n"] += 1
        # `href` (SVG 2) is supported by all modern browsers; we still emit
        # `xlink:href` too for legacy compressors that strip it.
        return (
            f'href="images/img_{idx:02d}.{ext}" '
            f'xlink:href="images/img_{idx:02d}.{ext}"'
        )

    # Match either `xlink:href="data:..."` or `href="data:..."`. The body of
    # the data URI can contain '/' '+' and '=' which we handle via the group.
    pattern = re.compile(
        r'(?:xlink:href|href)="data:image/(?P<mime>[^;]+);base64,[A-Za-z0-9+/=\s]+"'
    )
    cleaned = pattern.sub(_sub, svg)
    return cleaned, counter["n"]


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------
# We strip the outer <svg ...> width/height attributes so the SVG becomes
# fluid to its container; viewBox stays so it scales to the 1440x810 box.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1440, initial-scale=1.0">
    <title>Suzume — Movie Card Template</title>
    <style>
        /* ---------------------------------------------------------------
           Page chrome (purely cosmetic; safe to delete).
           The 1440x810 .stage mirrors the original SVG viewBox so the
           inline SVG inside scales perfectly without distortion.
           --------------------------------------------------------------- */
        :root { --w: 1440px; --h: 810px; }

        html, body {
            margin: 0;
            padding: 0;
            background: #0c0c10;
            font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
            color: #ddd;
        }
        body {
            display: flex;
            justify-content: center;
            align-items: flex-start;
            min-height: 100vh;
            padding: 24px;
            box-sizing: border-box;
        }

        .stage {
            width: var(--w);
            height: var(--h);
            position: relative;
            overflow: hidden;
            background: #000;
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.55);
            border-radius: 4px;
        }
        .stage svg {
            width: 100%;
            height: 100%;
            display: block;
        }

        /* Hint: hovering the canvas reveals layer names for designers. */
        .stage svg [data-layer] {
            outline: 1px dashed rgba(0, 255, 0, 0.35);
            outline-offset: -1px;
        }
        .stage svg [data-layer]:hover {
            outline: 1px dashed rgba(0, 255, 0, 0.9);
        }
    </style>
</head>
<body>
    <div class="stage" role="img" aria-label="Suzume movie thumbnail">
{svg}
    </div>
</body>
</html>
"""


def tag_image_layers(svg: str) -> str:
    """Tag each <image> with a data-layer="img_NN" attribute so designers can
    id them in DevTools. Pure enhancement; not strictly required."""
    counter = {"n": 0}

    def _sub(match: re.Match[str]) -> str:
        idx = counter["n"]
        counter["n"] += 1
        tag_open = match.group(0)
        return tag_open.replace("<image ", f'<image data-layer="img_{idx:02d}" ')

    pattern = re.compile(r"<image\s+[^/>]*?/>|<image\s+[^>]*></image>")
    return pattern.sub(_sub, svg)


def main() -> None:
    with open(SVG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        svg = f.read()

    cleaned, replaced = clean_svg(svg)
    cleaned = tag_image_layers(cleaned)

    # Strip the broad 'width="1920"' / 'height="1080"' the SVG carries so the
    # container can size us; viewBox is preserved.
    cleaned = re.sub(r'\s(width|height)="[^"]*"', "", cleaned, count=2)

    out = _HTML_TEMPLATE.format(svg=cleaned)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)

    in_kb = os.path.getsize(SVG_PATH) / 1024
    out_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"Replaced {replaced} inline image data URIs.")
    print(f"Input  temp_utf8.svg : {in_kb:8.1f} KB")
    print(f"Output template.html: {out_kb:8.1f} KB  ({100 - out_kb/in_kb*100:.1f}% smaller)")


if __name__ == "__main__":
    main()
