"""Pluggable, AUTHORIZED-ONLY content-acquisition layer.

NekoFetch ingests content through ``AnimeSource`` implementations. Only sources the
operator is authorized to use are shipped (local ingestion of owned files; licensed
HTTP/official APIs you control). No pirate-site scraper is provided or supported.

The interface intentionally mirrors the clean ``search -> details -> episodes ->
videos`` shape common to media-source abstractions, but is provider-agnostic.
"""

from nekofetch.sources.base import (
    AnimeDetails,
    AnimeSource,
    AnimeStub,
    Episode,
    VideoVariant,
)
from nekofetch.sources.registry import SourceRegistry

__all__ = [
    "AnimeSource",
    "AnimeStub",
    "AnimeDetails",
    "Episode",
    "VideoVariant",
    "SourceRegistry",
]
