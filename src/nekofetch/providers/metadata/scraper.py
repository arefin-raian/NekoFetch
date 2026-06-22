"""
███  KICKASSANIME METADATA PROVIDER  ███

Fetches anime metadata (profile + artwork) from the KickAssAnime public API.
``anime_ref`` is the slug (e.g. ``"one-piece"``).

API endpoints used:
  GET /api/show/{slug}  ->  AnimeInfoDto  (title, synopsis, genres, status, poster, …)

The poster URL from the API is promoted to ``poster_url`` in ``RawAssets``, so the
card header image renders correctly.
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

KAA_API = "https://kaa.lt"


class ScraperMetadataProvider(MetadataProvider):
    name = "scraper"

    implemented = True

    def __init__(self, *, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or KAA_API).rstrip("/")
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers={"User-Agent": "NekoFetch/0.1"},
                follow_redirects=True,
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def fetch_profile_data(self, anime_ref: str) -> RawProfile:
        slug = anime_ref.strip("/")
        resp = await self.http.get(f"/api/show/{slug}")
        resp.raise_for_status()
        doc = resp.json()

        status_map = {
            "finished_airing": "Finished",
            "currently_airing": "Airing",
        }

        return RawProfile(
            title=doc.get("title_en") or doc["title"],
            alt_titles=list(dict.fromkeys(t for t in (doc.get("title_en"), doc.get("title")) if t)),
            synopsis=doc.get("synopsis"),
            genres=doc.get("genres", []),
            release_date=str(doc["year"]) if doc.get("year") else None,
            status=status_map.get(doc.get("status", "")),
            season_count=1 if doc.get("season") else None,
            source_url=f"{self.base_url}/{slug}",
        )

    async def fetch_character_data(self, anime_ref: str) -> list[RawCharacter]:
        return []

    async def fetch_statistics(self, anime_ref: str) -> RawStatistics | None:
        return None

    async def fetch_assets(self, anime_ref: str) -> RawAssets | None:
        slug = anime_ref.strip("/")
        resp = await self.http.get(f"/api/show/{slug}")
        resp.raise_for_status()
        doc = resp.json()

        poster = doc.get("poster", {})
        poster_slug = poster.get("hq") if isinstance(poster, dict) else None

        return RawAssets(
            poster_url=f"{self.base_url}/image/poster/{poster_slug}.webp" if poster_slug else None,
        )
