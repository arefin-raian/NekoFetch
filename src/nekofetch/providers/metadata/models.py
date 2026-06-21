"""Stable data contracts for the metadata enrichment layer.

These models are the **contract** between your scraping code and the rest of NekoFetch.
Keep them stable: the transformer, renderer, EnrichmentService, and the bots all depend
on these shapes. If you only implement the ``fetch_*`` methods in ``scraper.py`` and
return these models, everything downstream works without further changes.

Two tiers of models:

1. ``Raw*`` — what your ``fetch_*`` functions return (loose, provider-shaped).
2. ``AnimeTemplateData`` — the canonical, render-ready structure the template needs
   (produced from the Raw models by ``transformer.build_template_data``).

Field requiredness is documented per field. The renderer only hard-requires ``title``;
everything else degrades gracefully when absent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — RAW models (returned by your fetch_* implementations in scraper.py)
# ─────────────────────────────────────────────────────────────────────────────


class RawProfile(BaseModel):
    """Core profile/about information for a title.

    Returned by ``fetch_profile_data(anime_ref)``.

    Required: ``title``. Everything else is optional but recommended.
    """

    title: str                                   # REQUIRED — display title
    alt_titles: list[str] = Field(default_factory=list)   # english/native/synonyms
    synopsis: str | None = None
    genres: list[str] = Field(default_factory=list)
    studio: str | None = None
    release_date: str | None = None              # ISO date or human string
    status: str | None = None                    # e.g. "Finished", "Airing"
    season_count: int | None = None
    episode_count: int | None = None
    source_url: str | None = None                # provenance, for auditing


class RawCharacter(BaseModel):
    """A single character / cast entry. Returned (in a list) by ``fetch_character_data``."""

    name: str                                    # REQUIRED
    role: str | None = None                      # "Main", "Supporting", ...
    voice_actor: str | None = None
    image_url: str | None = None


class RawStatistics(BaseModel):
    """Aggregate stats. Returned by ``fetch_statistics(anime_ref)``. All optional."""

    score: float | None = None                   # e.g. 8.7
    scored_by: int | None = None
    rank: int | None = None
    popularity: int | None = None
    members: int | None = None
    favorites: int | None = None
    status: str | None = None                    # may mirror RawProfile.status
    episode_count: int | None = None             # may mirror RawProfile.episode_count


class RawAssets(BaseModel):
    """Artwork URLs. Returned by ``fetch_assets(anime_ref)``. All optional.

    These are URLs; NekoFetch's media layer downloads/caches them locally when needed.
    """

    poster_url: str | None = None                # portrait key art
    banner_url: str | None = None                # wide hero image
    cover_url: str | None = None
    thumbnail_urls: list[str] = Field(default_factory=list)
    trailer_url: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — CANONICAL render-ready model (consumed by renderer.py + bots/UI)
# ─────────────────────────────────────────────────────────────────────────────


class CharacterEntry(BaseModel):
    """Normalized character for templates."""

    name: str
    role: str | None = None
    voice_actor: str | None = None
    image_url: str | None = None


class StatisticsBlock(BaseModel):
    """Normalized statistics for templates."""

    score: float | None = None
    rank: int | None = None
    popularity: int | None = None
    members: int | None = None
    favorites: int | None = None
    status: str | None = None


class AnimeTemplateData(BaseModel):
    """The single structure the template renderer consumes.

    Produced by ``transformer.build_template_data`` from the Raw models. This is the
    stable "view model" — if you ever add a new provider, only its ``fetch_*`` need to
    return Raw models; this shape (and the renderer) stay put.

    Renderer field usage:
      - REQUIRED: ``title``
      - HEADER IMAGE: ``banner_url`` preferred, else ``poster_url``
      - BODY (each included only if present): ``synopsis``, ``genres``, ``studio``,
        ``release_date``, ``season_count``, ``episode_count``, ``statistics``,
        ``characters`` (top N), ``alt_titles``
      - FOOTER: branding (injected by the renderer, not stored here)
    """

    # Identity
    anime_ref: str                               # the reference passed into the provider
    anime_doc_id: str | None = None              # NekoFetch Mongo id once persisted

    # Profile (REQUIRED: title)
    title: str
    alt_titles: list[str] = Field(default_factory=list)
    synopsis: str | None = None
    genres: list[str] = Field(default_factory=list)
    studio: str | None = None
    release_date: str | None = None
    status: str | None = None
    season_count: int | None = None
    episode_count: int | None = None

    # Related
    characters: list[CharacterEntry] = Field(default_factory=list)
    statistics: StatisticsBlock | None = None

    # Assets
    poster_url: str | None = None
    banner_url: str | None = None
    cover_url: str | None = None
    thumbnail_urls: list[str] = Field(default_factory=list)
    trailer_url: str | None = None

    # Provenance / freshness
    source: str | None = None                    # provider name that produced this
    source_url: str | None = None

    @property
    def header_image(self) -> str | None:
        """Image the renderer uses at the top: banner first, poster fallback."""
        return self.banner_url or self.poster_url


class RenderedAnimeInfo(BaseModel):
    """Final renderer output handed to the Telegram layer.

    ``caption`` is ready to send; ``image_url`` is the photo to attach (may be None).
    """

    caption: str
    image_url: str | None = None
    has_characters: bool = False
    has_statistics: bool = False
