"""Subtitle post-processing: clean watermarks, standardize styling, brand.

Pipeline per subtitle track:
  1. Parse WebVTT cues.
  2. Drop watermark / ad cues (e.g. the ``kaa.mx`` ruby tag KickAssAnime injects).
  3. Find the longest natural gap in the dialogue and insert a branded cue:
        Telegram: @AniXWeebs
     ("Telegram" in Telegram blue, "@AniXWeebs" in white, larger font).
  4. Emit two renditions:
        * ``.vtt`` — standardized STYLE block + cue classes (web / mpv correct)
        * ``.ass`` — Advanced SubStation, so the colours/size render identically
          in VLC, mpv and any MKV-aware player after muxing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Telegram brand blue.
TG_BLUE_HEX = "#229ED9"
TG_BLUE_ASS = "&H00D99E22"  # ASS is &HAABBGGRR  (22 9E D9 -> D9 9E 22)
WHITE_ASS = "&H00FFFFFF"

# Branding text.
BRAND_PREFIX = "Telegram:"
BRAND_HANDLE = "@AniXWeebs"

# Max time the branding stays on screen, and margin kept clear of real dialogue.
BRAND_MAX_MS = 4000
BRAND_MARGIN_MS = 400

# Cues whose (tag-stripped) text matches any of these are dropped as watermarks.
_WATERMARK_RE = re.compile(
    r"(kaa\.mx|kaa\.to|kickassanime|anizone|animekaizoku|"
    r"subscene|opensubtitles|downloaded\s+from|encoded\s+by|"
    r"\bripped\s+by\b|uploaded\s+by)",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Cue:
    start: int            # ms
    end: int              # ms
    text: str             # may contain VTT inline tags / newlines
    settings: str = ""    # original VTT cue settings (position etc.)


def _ts_to_ms(ts: str) -> int:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return 0
    sec, _, ms = s.partition(".")
    return ((int(h) * 60 + int(m)) * 60 + int(sec)) * 1000 + int((ms + "000")[:3])


def _ms_to_vtt(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _ms_to_ass(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:d}:{m:02d}:{s:02d}.{ms // 10:02d}"


def parse_vtt(text: str) -> list[Cue]:
    """Parse WebVTT into cues (ignores NOTE / STYLE / header blocks)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # find the timing line
        ti = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ti is None:
            continue
        timing = lines[ti]
        m = re.match(r"\s*([\d:.,]+)\s*-->\s*([\d:.,]+)\s*(.*)", timing)
        if not m:
            continue
        start, end = _ts_to_ms(m.group(1)), _ts_to_ms(m.group(2))
        settings = m.group(3).strip()
        body = "\n".join(lines[ti + 1:]).strip()
        if not body:
            continue
        cues.append(Cue(start, end, body, settings))
    return cues


def clean_cues(cues: list[Cue]) -> tuple[list[Cue], int]:
    """Drop watermark/ad cues. Returns (kept_cues, removed_count)."""
    kept: list[Cue] = []
    removed = 0
    for c in cues:
        plain = _TAG_RE.sub("", c.text).strip()
        if not plain or _WATERMARK_RE.search(plain) or _WATERMARK_RE.search(c.text):
            removed += 1
            continue
        kept.append(c)
    return kept, removed


# Never place branding inside the last N ms of the episode (the ending sequence).
ENDING_EXCLUSION_MS = 180_000  # 3 minutes


def find_longest_gap(cues: list[Cue], cutoff_ms: int) -> tuple[int, int]:
    """Longest subtitle-free interval that starts before ``cutoff_ms``.

    Considers the lead-in (0 -> first cue), every inter-cue gap, and the tail gap
    from the last cue up to the cutoff. Gaps are clipped at ``cutoff_ms`` so the
    branding never lands in the excluded ending region. Returns ``(start, end)``
    ms of the best gap (length 0 if none).
    """
    if not cues:
        return (1000, min(cutoff_ms, 1000 + BRAND_MAX_MS))
    ordered = sorted(cues, key=lambda c: c.start)
    best = (-1, 0, 0)  # (length, start, end)

    def consider(gs: int, ge: int) -> None:
        nonlocal best
        ge = min(ge, cutoff_ms)
        if ge - gs > best[0]:
            best = (ge - gs, gs, ge)

    consider(0, ordered[0].start)              # lead-in
    prev_end = ordered[0].end
    for c in ordered[1:]:
        if prev_end >= cutoff_ms:
            break
        consider(prev_end, c.start)
        prev_end = max(prev_end, c.end)
    if prev_end < cutoff_ms:                    # tail up to the cutoff
        consider(prev_end, cutoff_ms)
    return best[1], best[2]


def branding_window(cues: list[Cue], video_ms: int | None = None) -> tuple[int, int]:
    """Pick the on-screen window for the branding cue.

    Finds the longest subtitle-free gap, excluding the final 3 minutes of the
    episode (the ending sequence). Places the cue near the *start* of that gap.
    ``video_ms`` is the true video duration; if absent, the last cue's end is used
    as the reference point.
    """
    last_end = max((c.end for c in cues), default=0)
    end_ref = video_ms if video_ms else last_end
    cutoff = max(1000, end_ref - ENDING_EXCLUSION_MS)

    gstart, gend = find_longest_gap(cues, cutoff)
    gap = gend - gstart
    if gap < 1500:
        # No usable gap before the cutoff; sit it safely early.
        start = min(5000, cutoff - BRAND_MAX_MS)
        return max(0, start), max(0, start) + BRAND_MAX_MS
    # Lean toward the beginning of the gap.
    start = gstart + BRAND_MARGIN_MS
    dur = min(BRAND_MAX_MS, gap - 2 * BRAND_MARGIN_MS)
    if dur < 1000:
        start, dur = gstart, min(BRAND_MAX_MS, gap)
    return start, start + dur


# --------------------------------------------------------------------------- #
# VTT output
# --------------------------------------------------------------------------- #

_VTT_STYLE = (
    "WEBVTT\n\n"
    "STYLE\n"
    "::cue {\n"
    '  font-family: "Trebuchet MS", "Segoe UI", sans-serif;\n'
    "  color: #FFFFFF;\n"
    "  text-shadow: 0 0 3px rgba(0,0,0,0.9);\n"
    "}\n"
    "::cue(.tg) { color: " + TG_BLUE_HEX + "; font-weight: bold; }\n"
    "::cue(.handle) { color: #FFFFFF; font-weight: bold; }\n"
    "::cue(.brand) { font-size: 1.4em; }\n\n"
)


def build_vtt(cues: list[Cue], brand: tuple[int, int]) -> str:
    out = [_VTT_STYLE]
    bstart, bend = brand
    branding = (
        f"{_ms_to_vtt(bstart)} --> {_ms_to_vtt(bend)} line:82% align:center\n"
        f"<c.brand><c.tg>{BRAND_PREFIX}</c> <c.handle>{BRAND_HANDLE}</c></c>\n"
    )
    inserted = False
    for c in sorted(cues, key=lambda x: x.start):
        if not inserted and c.start >= bstart:
            out.append(branding)
            inserted = True
        settings = (" " + c.settings) if c.settings else ""
        out.append(f"{_ms_to_vtt(c.start)} --> {_ms_to_vtt(c.end)}{settings}\n{c.text}\n")
    if not inserted:
        out.append(branding)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# ASS output (reliable colour/size in VLC / mpv after muxing)
# --------------------------------------------------------------------------- #

_ASS_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)
# Default dialogue style + a larger, bold "Brand" style for the @AniXWeebs cue.
_ASS_STYLE_DEFAULT = (
    "Style: Default,Trebuchet MS,54,&H00FFFFFF,&H000000FF,&H00000000,"
    "&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,80,80,40,1"
)
_ASS_STYLE_BRAND = (
    "Style: Brand,Trebuchet MS,72,&H00FFFFFF,&H000000FF,&H00000000,"
    "&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,80,80,60,1"
)
_ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1920\nPlayResY: 1080\n"
    "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    f"{_ASS_FORMAT}\n{_ASS_STYLE_DEFAULT}\n{_ASS_STYLE_BRAND}\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def _vtt_text_to_ass(text: str) -> str:
    text = text.replace("{", "(").replace("}", ")")
    text = re.sub(r"<i>", r"{\\i1}", text, flags=re.IGNORECASE)
    text = re.sub(r"</i>", r"{\\i0}", text, flags=re.IGNORECASE)
    text = re.sub(r"<b>", r"{\\b1}", text, flags=re.IGNORECASE)
    text = re.sub(r"</b>", r"{\\b0}", text, flags=re.IGNORECASE)
    # drop ruby (watermark already gone, but keep base text of any other ruby)
    text = re.sub(r"<rt>.*?</rt>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = _TAG_RE.sub("", text)
    return text.replace("\n", "\\N").strip()


def build_ass(cues: list[Cue], brand: tuple[int, int]) -> str:
    rows = [_ASS_HEADER]
    bstart, bend = brand
    brand_text = (
        f"{{\\c{TG_BLUE_ASS}}}{BRAND_PREFIX} {{\\c{WHITE_ASS}}}{BRAND_HANDLE}"
    )
    rows.append(
        f"Dialogue: 0,{_ms_to_ass(bstart)},{_ms_to_ass(bend)},Brand,,0,0,0,,{brand_text}"
    )
    for c in sorted(cues, key=lambda x: x.start):
        rows.append(
            f"Dialogue: 0,{_ms_to_ass(c.start)},{_ms_to_ass(c.end)},Default,,0,0,0,,"
            f"{_vtt_text_to_ass(c.text)}"
        )
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def content_signature(cues: list[Cue]) -> str:
    """Stable hash of a track's dialogue (timings + tag-stripped text).

    Used to deduplicate subtitle tracks that are identical across variants while
    keeping ones that differ in timing/wording/content.
    """
    import hashlib
    parts = [f"{c.start}|{c.end}|{_TAG_RE.sub('', c.text).strip()}"
             for c in sorted(cues, key=lambda c: (c.start, c.end))]
    return hashlib.sha1("\n".join(parts).encode("utf-8", "replace")).hexdigest()


def process_subtitle(vtt_path: Path, video_ms: int | None = None) -> dict:
    """Clean + style + brand a VTT file in place, and emit an .ass sibling.

    ``video_ms`` is the true video duration so the branding can exclude the final
    3 minutes. Returns metadata incl. a content signature for dedup.
    """
    raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    cues = parse_vtt(raw)
    cleaned, removed = clean_cues(cues)
    sig = content_signature(cleaned)
    brand = branding_window(cleaned, video_ms)

    vtt_path.write_text(build_vtt(cleaned, brand), encoding="utf-8")
    ass_path = vtt_path.with_suffix(".ass")
    ass_path.write_text(build_ass(cleaned, brand), encoding="utf-8")

    return {
        "vtt": str(vtt_path),
        "ass": str(ass_path),
        "cues_in": len(cues),
        "cues_kept": len(cleaned),
        "watermarks_removed": removed,
        "brand_at_ms": brand[0],
        "brand_at": f"{brand[0]//60000}:{(brand[0]//1000)%60:02d}",
        "signature": sig,
    }
