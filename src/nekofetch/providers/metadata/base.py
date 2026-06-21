"""MetadataProvider interface.

A provider knows how to acquire metadata for a title and assemble it into the canonical
``AnimeTemplateData``. You implement the four ``fetch_*`` methods in a subclass
(``scraper.py``); the ``build_template_data`` orchestrator is already written and calls
your fetchers, then the transformer — you do not need to touch it.

Contract summary (see models.py for full field docs):

    fetch_profile_data(anime_ref)   -> RawProfile          (REQUIRED to implement)
    fetch_character_data(anime_ref) -> list[RawCharacter]  (optional; return [] if N/A)
    fetch_statistics(anime_ref)     -> RawStatistics | None (optional)
    fetch_assets(anime_ref)         -> RawAssets | None     (optional)

    build_template_data(anime_ref)  -> AnimeTemplateData | None   (provided)

``anime_ref`` is a provider-native reference string (an id, slug, or URL) that NekoFetch
passes through unchanged — you decide what it means for your source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from nekofetch.core.logging import get_logger
from nekofetch.providers.metadata.models import (
    AnimeTemplateData,
    RawAssets,
    RawCharacter,
    RawProfile,
    RawStatistics,
)
from nekofetch.providers.metadata.transformer import build_template_data

log = get_logger(__name__)


class MetadataProvider(ABC):
    #: Stable provider identifier (used in config and stored on produced data).
    name: str = "base"

    #: Flip to True in your implementation once the fetch_* methods are real.
    #: While False, EnrichmentService skips this provider entirely (graceful no-op),
    #: so the app keeps working with whatever metadata it already has.
    implemented: bool = False

    # ── methods YOU implement (in scraper.py) ──
    @abstractmethod
    async def fetch_profile_data(self, anime_ref: str) -> RawProfile:
        """Return core profile info. Must include a non-empty ``title``."""

    @abstractmethod
    async def fetch_character_data(self, anime_ref: str) -> list[RawCharacter]:
        """Return character/cast entries (possibly empty)."""

    @abstractmethod
    async def fetch_statistics(self, anime_ref: str) -> RawStatistics | None:
        """Return aggregate statistics, or None if unavailable."""

    @abstractmethod
    async def fetch_assets(self, anime_ref: str) -> RawAssets | None:
        """Return artwork URLs, or None if unavailable."""

    # ── orchestrator (PROVIDED — do not need to edit) ──
    async def build_template_data(self, anime_ref: str) -> AnimeTemplateData | None:
        """Call the fetchers and transform their output into render-ready data.

        Returns None when the profile can't be produced (e.g. not implemented yet),
        which signals callers to fall back to existing/basic metadata.
        """
        if not self.implemented:
            log.debug("metadata.provider.not_implemented", provider=self.name)
            return None
        try:
            profile = await self.fetch_profile_data(anime_ref)
        except NotImplementedError:
            log.debug("metadata.provider.profile_not_implemented", provider=self.name)
            return None
        if profile is None or not profile.title:
            return None

        # The non-critical fetchers degrade independently — a failure in one does not
        # block the rest of the card from rendering.
        characters = await self._safe(self.fetch_character_data, anime_ref, default=[])
        statistics = await self._safe(self.fetch_statistics, anime_ref, default=None)
        assets = await self._safe(self.fetch_assets, anime_ref, default=None)

        return build_template_data(
            anime_ref,
            profile=profile,
            characters=characters or [],
            statistics=statistics,
            assets=assets,
            source=self.name,
        )

    async def _safe(self, fn, *args, default):
        try:
            return await fn(*args)
        except NotImplementedError:
            return default
        except Exception as exc:  # noqa: BLE001
            log.warning("metadata.provider.fetch_failed", provider=self.name,
                        fn=getattr(fn, "__name__", "?"), error=str(exc))
            return default
