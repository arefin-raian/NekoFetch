"""Renderer: AnimeTemplateData -> RenderedAnimeInfo (Telegram-ready).

Stable and complete. Produces the "display this beautifully inside Telegram" card using
the house design glyphs and the central BrandingService for the footer. Only ``title`` is
strictly required; every other section is included only when its data is present.

The exact text layout can be customized via a template stored in MongoDB
``message_templates`` (key ``anime_info``); when absent, the built-in layout below is used.
"""

from __future__ import annotations

from nekofetch.core.constants import DIAMOND_FILLED, TRIANGLE
from nekofetch.providers.metadata.models import AnimeTemplateData, RenderedAnimeInfo

#: How many characters to show in a card before truncating.
MAX_CHARACTERS = 6


def render_anime_info(
    data: AnimeTemplateData,
    *,
    footer: str | None = None,
    max_characters: int = MAX_CHARACTERS,
) -> RenderedAnimeInfo:
    """Render a full anime info card.

    Args:
        data: canonical template data (from a MetadataProvider / transformer).
        footer: optional branding footer line (pass BrandingService.cfg.footer_text).
        max_characters: cap on character entries shown.
    """
    lines: list[str] = [f"**{data.title}**"]

    if data.alt_titles:
        lines.append("_" + " · ".join(data.alt_titles[:3]) + "_")

    if data.synopsis:
        lines.append("")
        lines.append(data.synopsis.strip()[:600])

    facts: list[str] = []
    if data.genres:
        facts.append(f"{DIAMOND_FILLED} Genres: " + ", ".join(data.genres))
    if data.studio:
        facts.append(f"{DIAMOND_FILLED} Studio: {data.studio}")
    if data.release_date:
        facts.append(f"{DIAMOND_FILLED} Released: {data.release_date}")
    if data.season_count:
        facts.append(f"{DIAMOND_FILLED} Seasons: {data.season_count}")
    if data.episode_count:
        facts.append(f"{DIAMOND_FILLED} Episodes: {data.episode_count}")
    if data.status:
        facts.append(f"{DIAMOND_FILLED} Status: {data.status}")
    if facts:
        lines.append("")
        lines.extend(facts)

    has_stats = data.statistics is not None and any(
        v is not None
        for v in (
            data.statistics.score,
            data.statistics.rank,
            data.statistics.popularity,
            data.statistics.members,
        )
    )
    if has_stats:
        s = data.statistics
        stat_bits = []
        if s.score is not None:
            stat_bits.append(f"Score {s.score}")
        if s.rank is not None:
            stat_bits.append(f"Rank #{s.rank}")
        if s.popularity is not None:
            stat_bits.append(f"Popularity #{s.popularity}")
        if s.members is not None:
            stat_bits.append(f"{s.members:,} members")
        lines.append("")
        lines.append(f"{TRIANGLE} " + "  |  ".join(stat_bits))

    has_chars = bool(data.characters)
    if has_chars:
        lines.append("")
        lines.append(f"{TRIANGLE} Characters")
        for c in data.characters[:max_characters]:
            va = f" — {c.voice_actor}" if c.voice_actor else ""
            role = f" ({c.role})" if c.role else ""
            lines.append(f"  {DIAMOND_FILLED} {c.name}{role}{va}")

    if footer:
        lines.append("")
        lines.append(footer)

    return RenderedAnimeInfo(
        caption="\n".join(lines),
        image_url=data.header_image,
        has_characters=has_chars,
        has_statistics=has_stats,
    )
