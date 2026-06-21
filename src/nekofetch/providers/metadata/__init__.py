"""Metadata enrichment provider.

This package turns an anime reference into rich, render-ready metadata
(profile + characters + statistics + assets) for "display this beautifully inside
Telegram". The data acquisition (the scraping/fetching) is intentionally NOT implemented
here — it lives in a single editable file, ``scraper.py``.

Layers (data flows top to bottom):

    scraper.py     fetch_* placeholders  -> Raw* models      [*** edit this file ***]
        │
    transformer.py raw models            -> AnimeTemplateData [stable, complete]
        │
    renderer.py    AnimeTemplateData      -> RenderedAnimeInfo [stable, complete]
        │
    EnrichmentService (services/)        -> cache + serve to bots/UI

Public surface:
"""

from nekofetch.providers.metadata.base import MetadataProvider
from nekofetch.providers.metadata.models import (
    AnimeTemplateData,
    CharacterEntry,
    RawAssets,
    RawCharacter,
    RawProfile,
    RawStatistics,
    RenderedAnimeInfo,
    StatisticsBlock,
)

__all__ = [
    "MetadataProvider",
    "RawProfile",
    "RawCharacter",
    "RawStatistics",
    "RawAssets",
    "AnimeTemplateData",
    "CharacterEntry",
    "StatisticsBlock",
    "RenderedAnimeInfo",
]
