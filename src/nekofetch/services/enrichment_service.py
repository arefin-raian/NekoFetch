"""Enrichment service — the app's entry point for rich anime metadata.

Bots and UI call this; they never touch the provider directly. It:

  1. returns cached AnimeTemplateData from Mongo when available,
  2. otherwise asks the active MetadataProvider to build it (your scraper),
  3. persists the result, and
  4. renders a ready-to-send Telegram card via the renderer.

Crucially, when the provider is not implemented yet (``implemented = False`` in
scraper.py), every method returns None and callers fall back to basic metadata — so the
rest of the app already depends on this service and "just works" the moment you implement
the fetchers. No other file needs to change.
"""

from __future__ import annotations

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.providers.metadata.models import AnimeTemplateData, RenderedAnimeInfo
from nekofetch.providers.metadata.renderer import render_anime_info

log = get_logger(__name__)

_CACHE_FIELD = "template_data"


class EnrichmentService:
    def __init__(self, container: Container) -> None:
        self._c = container

    @property
    def _provider(self):
        return self._c.metadata_provider

    async def get_template_data(
        self,
        anime_ref: str,
        *,
        anime_doc_id: str | None = None,
        force_refresh: bool = False,
    ) -> AnimeTemplateData | None:
        """Return canonical template data for a title, or None if unavailable.

        Reads the Mongo cache first (unless ``force_refresh``), then the provider.
        """
        coll = self._c.collections.anime if self._c.collections is not None else None

        if coll is not None and not force_refresh:
            doc = await coll.find_one({"anime_ref": anime_ref})
            if doc and doc.get(_CACHE_FIELD):
                return AnimeTemplateData.model_validate(doc[_CACHE_FIELD])

        data = await self._provider.build_template_data(anime_ref)
        if data is None:
            return None  # provider not implemented / no data -> caller falls back
        if anime_doc_id:
            data.anime_doc_id = anime_doc_id

        if coll is not None:
            await coll.update_one(
                {"anime_ref": anime_ref},
                {"$set": {"anime_ref": anime_ref, _CACHE_FIELD: data.model_dump()}},
                upsert=True,
            )
        log.info("enrichment.built", anime_ref=anime_ref, provider=data.source)
        return data

    async def render_card(
        self, anime_ref: str, *, anime_doc_id: str | None = None, force_refresh: bool = False
    ) -> RenderedAnimeInfo | None:
        """Convenience: fetch + render a Telegram-ready info card, or None to fall back."""
        data = await self.get_template_data(
            anime_ref, anime_doc_id=anime_doc_id, force_refresh=force_refresh
        )
        if data is None:
            return None
        footer = (
            self._c.config.branding.footer_text
            if self._c.config.branding.enabled
            else None
        )
        return render_anime_info(data, footer=footer)
