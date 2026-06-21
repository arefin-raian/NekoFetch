"""
███  THE ONLY FILE YOU NEED TO EDIT TO ADD METADATA SCRAPING  ███

Implement the four ``fetch_*`` methods below and set ``implemented = True``. That's it —
the transformer, renderer, EnrichmentService, caching, and the bots already consume the
output, so the rest of NekoFetch starts showing rich metadata automatically with no other
changes.

────────────────────────────────────────────────────────────────────────────────
WHICH FUNCTIONS NEED IMPLEMENTATION
────────────────────────────────────────────────────────────────────────────────
  fetch_profile_data(anime_ref)    -> RawProfile           REQUIRED
  fetch_character_data(anime_ref)  -> list[RawCharacter]   optional (return [] if N/A)
  fetch_statistics(anime_ref)      -> RawStatistics | None optional (return None if N/A)
  fetch_assets(anime_ref)          -> RawAssets | None      optional (return None if N/A)

  build_template_data(anime_ref)   -> AnimeTemplateData     ALREADY PROVIDED (base class);
                                                            it calls the four fetchers and
                                                            runs the transformer for you.

(Your requested names map to these: fetchProfileData->fetch_profile_data,
 fetchCharacterData->fetch_character_data, fetchStatistics->fetch_statistics,
 fetchAssets->fetch_assets, buildTemplateData->build_template_data.)

────────────────────────────────────────────────────────────────────────────────
INPUT EACH FUNCTION RECEIVES
────────────────────────────────────────────────────────────────────────────────
  anime_ref: str
      A provider-native reference NekoFetch passes through unchanged. You decide its
      meaning for your source — an id, a slug, or a full URL. It originates from the
      title the operator is enriching (e.g. a request's ``source_ref`` / Mongo doc id).

  A shared ``httpx.AsyncClient`` is available as ``self.http`` (created lazily, closed by
  ``close()``), so you don't manage connections yourself.

────────────────────────────────────────────────────────────────────────────────
OUTPUT STRUCTURE EACH FUNCTION MUST RETURN  (see models.py for full field docs)
────────────────────────────────────────────────────────────────────────────────
  RawProfile     title (REQUIRED), alt_titles[], synopsis, genres[], studio,
                 release_date, status, season_count, episode_count, source_url
  RawCharacter   name (REQUIRED), role, voice_actor, image_url
  RawStatistics  score, scored_by, rank, popularity, members, favorites, status,
                 episode_count   (all optional)
  RawAssets      poster_url, banner_url, cover_url, thumbnail_urls[], trailer_url

────────────────────────────────────────────────────────────────────────────────
FIELDS THE TEMPLATE RENDERER REQUIRES
────────────────────────────────────────────────────────────────────────────────
  Hard requirement:  RawProfile.title
  Header image:      RawAssets.banner_url (preferred) or poster_url (fallback)
  Everything else is included only when present — partial data renders fine.

────────────────────────────────────────────────────────────────────────────────
DATA FLOW
────────────────────────────────────────────────────────────────────────────────
  scraper.fetch_*  ->  transformer.build_template_data  ->  AnimeTemplateData
                   ->  renderer.render_anime_info        ->  RenderedAnimeInfo
                   ->  EnrichmentService (cache to Mongo) ->  admin/distribution bots

────────────────────────────────────────────────────────────────────────────────
AUTHORIZATION
────────────────────────────────────────────────────────────────────────────────
  Implement these against sources you are authorized to use (an official/licensed
  metadata API, your own database, content you own). You are responsible for complying
  with the terms and rights of whatever source you point this at.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import httpx

from nekofetch.core.logging import get_logger
from nekofetch.providers.metadata.base import MetadataProvider
from nekofetch.providers.metadata.models import (
    RawAssets,
    RawCharacter,
    RawProfile,
    RawStatistics,
)

log = get_logger(__name__)


class ScraperMetadataProvider(MetadataProvider):
    name = "scraper"

    # ── ENABLE SWITCH ──────────────────────────────────────────────────────────
    # Leave False until the fetch_* methods below are implemented. While False the
    # EnrichmentService skips this provider, so the app keeps running normally.
    # Flip to True when you're ready.
    implemented = False
    # ────────────────────────────────────────────────────────────────────────────

    def __init__(self, *, base_url: str | None = None, timeout: float = 15.0) -> None:
        # Optional config you may use in your implementation.
        self.base_url = base_url
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        """Lazily-created shared async HTTP client. Closed by ``close()``."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url or "",
                timeout=self._timeout,
                headers={"User-Agent": "NekoFetch/0.1 (+authorized-use)"},
                follow_redirects=True,
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ════════════════════════════════════════════════════════════════════════════
    # IMPLEMENT BELOW
    # ════════════════════════════════════════════════════════════════════════════

    async def fetch_profile_data(self, anime_ref: str) -> RawProfile:
        """REQUIRED. Return a RawProfile for ``anime_ref`` (must set ``title``).

        Example skeleton (delete and replace with your real logic):

            resp = await self.http.get(f"/anime/{anime_ref}")
            resp.raise_for_status()
            doc = resp.json()
            return RawProfile(
                title=doc["title"],
                alt_titles=doc.get("synonyms", []),
                synopsis=doc.get("synopsis"),
                genres=[g["name"] for g in doc.get("genres", [])],
                studio=(doc.get("studios") or [{}])[0].get("name"),
                release_date=doc.get("aired", {}).get("from"),
                status=doc.get("status"),
                season_count=doc.get("season_count"),
                episode_count=doc.get("episodes"),
                source_url=doc.get("url"),
            )
        """
        # TODO: implement profile fetching for your authorized source.
        raise NotImplementedError("fetch_profile_data is not implemented yet")

    async def fetch_character_data(self, anime_ref: str) -> list[RawCharacter]:
        """Optional. Return character/cast entries; return [] if not available.

        Example:

            resp = await self.http.get(f"/anime/{anime_ref}/characters")
            return [
                RawCharacter(
                    name=c["name"],
                    role=c.get("role"),
                    voice_actor=(c.get("voice_actors") or [{}])[0].get("name"),
                    image_url=c.get("image_url"),
                )
                for c in resp.json().get("data", [])
            ]
        """
        # TODO: implement character fetching, or leave returning [] if unsupported.
        raise NotImplementedError("fetch_character_data is not implemented yet")

    async def fetch_statistics(self, anime_ref: str) -> RawStatistics | None:
        """Optional. Return aggregate stats, or None if not available.

        Example:

            doc = (await self.http.get(f"/anime/{anime_ref}/statistics")).json()
            return RawStatistics(
                score=doc.get("score"),
                rank=doc.get("rank"),
                popularity=doc.get("popularity"),
                members=doc.get("members"),
                favorites=doc.get("favorites"),
            )
        """
        # TODO: implement statistics fetching, or return None if unsupported.
        raise NotImplementedError("fetch_statistics is not implemented yet")

    async def fetch_assets(self, anime_ref: str) -> RawAssets | None:
        """Optional. Return artwork URLs, or None if not available.

        Example:

            doc = (await self.http.get(f"/anime/{anime_ref}")).json()
            imgs = doc.get("images", {})
            return RawAssets(
                poster_url=imgs.get("poster"),
                banner_url=imgs.get("banner"),
                cover_url=imgs.get("cover"),
                thumbnail_urls=imgs.get("thumbnails", []),
                trailer_url=doc.get("trailer", {}).get("url"),
            )
        """
        # TODO: implement asset fetching, or return None if unsupported.
        raise NotImplementedError("fetch_assets is not implemented yet")
