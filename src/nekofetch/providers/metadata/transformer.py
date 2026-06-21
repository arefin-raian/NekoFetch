"""Transformer: Raw* models -> AnimeTemplateData.

Stable and complete — you should not need to edit this. It normalizes whatever your
fetchers return into the single canonical structure the renderer consumes, applying
sensible fallbacks (e.g. statistics may carry status/episode_count that the profile
omitted).
"""

from __future__ import annotations

from nekofetch.providers.metadata.models import (
    AnimeTemplateData,
    CharacterEntry,
    RawAssets,
    RawCharacter,
    RawProfile,
    RawStatistics,
    StatisticsBlock,
)


def build_template_data(
    anime_ref: str,
    *,
    profile: RawProfile,
    characters: list[RawCharacter] | None = None,
    statistics: RawStatistics | None = None,
    assets: RawAssets | None = None,
    source: str | None = None,
) -> AnimeTemplateData:
    characters = characters or []
    stats_block = _to_stats_block(statistics) if statistics else None

    return AnimeTemplateData(
        anime_ref=anime_ref,
        title=profile.title,
        alt_titles=profile.alt_titles,
        synopsis=profile.synopsis,
        genres=profile.genres,
        studio=profile.studio,
        release_date=profile.release_date,
        status=profile.status or (statistics.status if statistics else None),
        season_count=profile.season_count,
        episode_count=(
            profile.episode_count
            or (statistics.episode_count if statistics else None)
        ),
        characters=[_to_character(c) for c in characters],
        statistics=stats_block,
        poster_url=assets.poster_url if assets else None,
        banner_url=assets.banner_url if assets else None,
        cover_url=assets.cover_url if assets else None,
        thumbnail_urls=assets.thumbnail_urls if assets else [],
        trailer_url=assets.trailer_url if assets else None,
        source=source,
        source_url=profile.source_url,
    )


def _to_character(c: RawCharacter) -> CharacterEntry:
    return CharacterEntry(
        name=c.name, role=c.role, voice_actor=c.voice_actor, image_url=c.image_url
    )


def _to_stats_block(s: RawStatistics) -> StatisticsBlock:
    return StatisticsBlock(
        score=s.score,
        rank=s.rank,
        popularity=s.popularity,
        members=s.members,
        favorites=s.favorites,
        status=s.status,
    )
