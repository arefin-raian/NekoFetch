"""Distribution-bot display-name formatting.

A per-title bot's name encodes, at a glance, what it carries:

    "<English> / <Romaji> [<audio tag>]"

The audio tag is derived from which audio tracks actually exist for the title:

    * sub + dub present          → "Dual Sub Dub"   (or "Multi Dual Sub Dub" when
                                    there are 3+ languages, e.g. EN/JA/HI)
    * dub only                   → "Dub"
    * sub only                   → "Sub"

Telegram caps a bot name at 64 chars, so the title half is truncated to fit while
the tag is always preserved (the tag is the part users scan for).
"""

from __future__ import annotations

from nekofetch.domain.enums import AudioType

_BOT_NAME_LIMIT = 64


def audio_tag(audios: set, languages: set | None = None) -> str:
    """The bracketed audio/language tag for a set of available audio tracks."""
    vals = {a.value if isinstance(a, AudioType) else str(a) for a in audios}
    has_dual = AudioType.DUAL_AUDIO.value in vals
    has_sub = AudioType.SUBBED.value in vals or has_dual
    has_dub = AudioType.DUBBED.value in vals or has_dual
    langs = {l.strip().lower() for l in (languages or set()) if l and l.strip()}
    multi = len(langs) >= 3  # e.g. English + Japanese + Hindi

    if has_sub and has_dub:
        return "Multi Dual Sub Dub" if multi else "Dual Sub Dub"
    if has_dub:
        return "Dub"
    if has_sub:
        return "Sub"
    return ""


def format_bot_name(
    english: str | None, romaji: str | None, *,
    audios: set, languages: set | None = None, limit: int = _BOT_NAME_LIMIT,
) -> str:
    """Build the bot's display name: '<English> / <Romaji> [<tag>]', fit to ``limit``."""
    english = (english or "").strip()
    romaji = (romaji or "").strip()
    if english and romaji and english.lower() != romaji.lower():
        title = f"{english} / {romaji}"
    else:
        title = english or romaji or "Anime"

    tag = audio_tag(audios, languages)
    suffix = f" [{tag}]" if tag else ""

    # Preserve the tag; truncate the title half to fit the 64-char Telegram limit.
    room = limit - len(suffix)
    if len(title) > room:
        title = title[: max(0, room - 1)].rstrip(" /") + "…"
    return f"{title}{suffix}"


def format_bot_username(base: str, anime_doc_id: str, *, suffix: str = "ani_weebs") -> str:
    """A valid, reasonably-unique bot username candidate (5–32 chars, ends in 'bot').

    Telegram requires usernames to be unique, so BotFather may still reject this and
    the factory must retry with a numeric bump — this only produces the FIRST guess.
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", (base or "anime").lower()).strip("_")
    # leave room for the "_<suffix>bot" tail within 32 chars
    tail = f"_{suffix}_bot"
    slug = slug[: max(1, 32 - len(tail))].strip("_") or "anime"
    name = f"{slug}{tail}"
    return name[:32]
