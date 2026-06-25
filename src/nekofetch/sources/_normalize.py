"""Release normalization — make every downloaded file carry OUR metadata.

Applied after download for any source. It:
  * extracts every embedded **text** subtitle track (ASS/SRT/VTT/…),
  * detects each track's language (existing tag first, else content analysis),
  * processes each with the shared subtitle pipeline (watermark strip, our
    styling, Telegram branding in the longest gap excluding the last 3 min),
  * relabels subtitle AND audio tracks with our naming policy:
        known language  ->  "<Language> - @AniXWeebs"
        subtitle unknown ->  "@AniXWeebs"
        audio unknown    ->  "Anime Weebs #1 - @AniXWeebs"
  * remuxes video + (relabeled) audio + ONLY our processed subtitles, and sets
    the container title to our brand — dropping the source's original subtitles
    and caption/title entirely.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

from nekofetch.core.logging import get_logger
from nekofetch.sources._hls import find_ffmpeg, find_ffprobe
from nekofetch.sources._mux import iso639_2
from nekofetch.sources._subs import _TAG_RE, process_subtitle

log = get_logger(__name__)

BRAND_HANDLE = "@AniXWeebs"
AUDIO_UNKNOWN_TITLE = f"Anime Weebs #1 - {BRAND_HANDLE}"
CONTAINER_TITLE = f"Anime Weebs #1 - {BRAND_HANDLE}"

# Subtitle codecs we can convert to text/VTT (image-based subs are skipped).
_TEXT_SUB_CODECS = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text"}
_IMAGE_SUB_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "pgssub"}

# canonical 2-letter -> display name
_LANG_NAME = {
    "en": "English", "ja": "Japanese", "hi": "Hindi", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian", "ar": "Arabic", "ko": "Korean", "zh": "Chinese",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
    "tr": "Turkish", "pl": "Polish", "nl": "Dutch", "he": "Hebrew",
}
# 3-letter / locale tag -> canonical 2-letter
_TO_ISO2 = {
    "eng": "en", "jpn": "ja", "jp": "ja", "hin": "hi", "spa": "es", "fre": "fr",
    "fra": "fr", "ger": "de", "deu": "de", "ita": "it", "por": "pt", "rus": "ru",
    "ara": "ar", "kor": "ko", "zho": "zh", "chi": "zh", "tha": "th", "vie": "vi",
    "ind": "id", "msa": "ms", "tur": "tr", "pol": "pl", "nld": "nl", "dut": "nl",
    "heb": "he",
}
# canonical 2-letter -> ISO 639-2 (for Matroska language metadata)
_TO_ISO3 = {
    "en": "eng", "ja": "jpn", "hi": "hin", "es": "spa", "fr": "fra", "de": "deu",
    "it": "ita", "pt": "por", "ru": "rus", "ar": "ara", "ko": "kor", "zh": "zho",
    "th": "tha", "vi": "vie", "id": "ind", "ms": "msa", "tr": "tur", "pl": "pol",
    "nl": "nld", "he": "heb",
}


def _iso3(code: str | None) -> str:
    """Canonical 2-letter -> ISO 639-2, falling back to the muxer's map."""
    if not code:
        return "und"
    return _TO_ISO3.get(code) or iso639_2(code)


def _norm_lang(tag: str | None) -> str | None:
    """Normalize a stream language tag to canonical 2-letter, or None if unknown."""
    if not tag:
        return None
    t = tag.lower().split("-")[0].strip()
    if t in ("und", "unknown", "", "mis", "zxx"):
        return None
    if t in _LANG_NAME:
        return t
    return _TO_ISO2.get(t)


# Script ranges that pin a language outright.
_SCRIPTS = [
    ("ja", re.compile(r"[぀-ヿ]")),       # hiragana/katakana
    ("ko", re.compile(r"[가-힣]")),        # hangul
    ("hi", re.compile(r"[ऀ-ॿ]")),        # devanagari
    ("ar", re.compile(r"[؀-ۿ]")),        # arabic
    ("he", re.compile(r"[֐-׿]")),        # hebrew
    ("th", re.compile(r"[฀-๿]")),        # thai
    ("ru", re.compile(r"[Ѐ-ӿ]")),        # cyrillic
    ("zh", re.compile(r"[一-鿿]")),        # CJK ideographs (no kana)
]
# Latin-script disambiguation by common function words.
_STOP = {
    "en": {"the", "and", "you", "that", "this", "with", "what", "have", "your", "not"},
    "es": {"que", "los", "una", "por", "con", "para", "esto", "pero", "como", "más"},
    "fr": {"les", "une", "des", "est", "pas", "vous", "pour", "que", "dans", "qui"},
    "pt": {"que", "não", "uma", "com", "para", "isso", "você", "como", "mais", "está"},
    "de": {"und", "der", "die", "das", "ich", "nicht", "ist", "wir", "sie", "ein"},
    "it": {"che", "non", "una", "per", "sono", "questo", "come", "più", "con", "del"},
    "id": {"yang", "dan", "ini", "itu", "tidak", "untuk", "dengan", "saya", "kamu"},
}


def detect_language(text: str) -> str | None:
    """Best-effort language code from subtitle text (script + function words)."""
    sample = _TAG_RE.sub("", text)
    sample = re.sub(r"\d\d:\d\d:\d\d[.,]\d+|-->|WEBVTT|\bDialogue:\b", " ", sample)
    if len(sample.strip()) < 20:
        return None
    for code, rx in _SCRIPTS:
        if len(rx.findall(sample)) >= 3:
            return code
    words = re.findall(r"[a-zàâäéèêëïîôùûüçñ']+", sample.lower())
    if not words:
        return None
    wordset = set(words)
    scores = {lang: len(wordset & stops) for lang, stops in _STOP.items()}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    # Latin script, no strong signal -> assume English (most common for anime subs)
    return "en" if len(words) > 30 else None


def track_title(lang: str | None, *, is_audio: bool) -> str:
    if lang and lang in _LANG_NAME:
        return f"{_LANG_NAME[lang]} - {BRAND_HANDLE}"
    return AUDIO_UNKNOWN_TITLE if is_audio else BRAND_HANDLE


def _ffprobe_streams(path: Path) -> list[dict]:
    ffprobe = find_ffprobe()
    r = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(r.stdout).get("streams", [])
    except json.JSONDecodeError:
        return []


def _duration_ms(path: Path) -> int | None:
    ffprobe = find_ffprobe()
    r = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return int(float(r.stdout.strip()) * 1000)
    except (ValueError, AttributeError):
        return None


async def normalize_release(src: Path, dest: Path) -> dict:
    """Normalize ``src`` into ``dest`` (.mkv) with our metadata + processed subs."""
    ffmpeg, ffprobe = find_ffmpeg(), find_ffprobe()
    if not (ffmpeg and ffprobe):
        raise RuntimeError("ffmpeg/ffprobe required for normalization")

    streams = _ffprobe_streams(src)
    video_ms = _duration_ms(src)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    work = dest.parent
    work.mkdir(parents=True, exist_ok=True)
    tmp: list[Path] = []
    seen_sigs: set[str] = set()   # dedup identical subtitle tracks
    report: dict = {"audio": [], "subtitles": [], "skipped": []}

    # ---- extract + process each text subtitle ----
    processed: list[tuple[Path, str, str | None]] = []  # (ass, title, lang)
    for n, s in enumerate(subs):
        codec = s.get("codec_name", "")
        if codec in _IMAGE_SUB_CODECS or codec not in _TEXT_SUB_CODECS:
            report["skipped"].append({"index": s["index"], "codec": codec,
                                      "reason": "non-text subtitle"})
            continue
        vtt = work / f".norm.{dest.stem}.{n}.vtt"
        proc = subprocess.run(  # noqa: ASYNC221 - quick per-track extract
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
             "-map", f"0:{s['index']}", "-c:s", "webvtt", str(vtt)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not vtt.exists() or vtt.stat().st_size == 0:
            report["skipped"].append({"index": s["index"], "codec": codec,
                                      "reason": "extract failed"})
            continue
        tmp.append(vtt)
        tag_lang = _norm_lang(s.get("tags", {}).get("language"))
        lang = tag_lang or detect_language(vtt.read_text(encoding="utf-8", errors="replace"))
        meta = process_subtitle(vtt, video_ms)
        ass = Path(meta["ass"])
        tmp.append(ass)
        sig = meta.get("signature")
        if sig and sig in seen_sigs:
            report["skipped"].append({"index": s["index"], "reason": "duplicate track"})
            continue
        if sig:
            seen_sigs.add(sig)
        title = track_title(lang, is_audio=False)
        processed.append((ass, title, lang))
        report["subtitles"].append({"lang": lang, "title": title,
                                     "from_tag": bool(tag_lang)})

    # ---- audio relabel plan ----
    audio_plan: list[tuple[str, str | None]] = []
    for s in audio:
        lang = _norm_lang(s.get("tags", {}).get("language"))
        title = track_title(lang, is_audio=True)
        audio_plan.append((title, lang))
        report["audio"].append({"lang": lang, "title": title})

    # ---- remux: video + relabeled audio + ONLY our subs ----
    out = dest.with_suffix(".mkv")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src)]
    for ass, _t, _l in processed:
        cmd += ["-i", str(ass)]
    cmd += ["-map", "0:v"]
    cmd += ["-map", "0:a"]
    for i in range(len(processed)):
        cmd += ["-map", f"{i + 1}:0"]
    cmd += ["-c:v", "copy", "-c:a", "copy", "-c:s", "copy",
            "-map_metadata", "-1", "-metadata", f"title={CONTAINER_TITLE}"]
    for i, (title, lang) in enumerate(audio_plan):
        cmd += [f"-metadata:s:a:{i}", f"title={title}"]
        if lang:
            cmd += [f"-metadata:s:a:{i}", f"language={_iso3(lang)}"]
    for i, (_ass, title, lang) in enumerate(processed):
        cmd += [f"-metadata:s:s:{i}", f"title={title}"]
        cmd += [f"-metadata:s:s:{i}", f"language={_iso3(lang) if lang else 'und'}"]
        cmd += [f"-disposition:s:{i}", "default" if i == 0 else "0"]
    cmd += [str(out)]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    for p in tmp:
        p.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"normalize remux failed: {err.decode(errors='replace')[-300:]}")

    report.update(path=str(out), bytes=out.stat().st_size,
                  subtitle_tracks=len(processed), audio_tracks=len(audio_plan))
    return report
