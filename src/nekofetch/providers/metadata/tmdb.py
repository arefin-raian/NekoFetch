"""TMDB client — backdrops + display metadata for the search-confirm UI.

Given an anime title we fetch the best TMDB match (TV first, then movie), its
display info, and an English promotional backdrop (16:9) for the confirmation
card. Auth uses the v4 read access token (Bearer); falls back to the v3 api_key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from nekofetch.core.logging import get_logger

log = get_logger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"


@dataclass
class TmdbResult:
    id: int
    media_type: str           # "tv" | "movie"
    title: str
    year: str | None
    genres: list[str] = field(default_factory=list)
    rating: float | None = None
    overview: str = ""
    seasons: int | None = None
    episodes: int | None = None
    backdrop_url: str | None = None     # English 16:9 backdrop (original size)
    poster_url: str | None = None

    def backdrop(self, size: str = "w1280") -> str | None:
        if not self._backdrop_path:
            return self.backdrop_url
        return f"{IMG_BASE}/{size}{self._backdrop_path}"

    _backdrop_path: str | None = None


class TmdbClient:
    def __init__(self, token: str | None = None, api_key: str | None = None) -> None:
        self.token = token or os.getenv("TMDB_API_READ_ACCESS_TOKEN", "")
        self.api_key = api_key or os.getenv("TMDB_API_KEY", "")
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            headers = {"accept": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._http = httpx.AsyncClient(timeout=20.0, headers=headers)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _params(self, **extra) -> dict:
        p = dict(extra)
        if not self.token and self.api_key:  # v3 key fallback
            p["api_key"] = self.api_key
        return p

    async def _get(self, path: str, **params) -> dict:
        r = await self.http.get(f"{TMDB_API}{path}", params=self._params(**params))
        r.raise_for_status()
        return r.json()

    async def search(self, title: str) -> TmdbResult | None:
        """Best match for ``title`` — prefers TV, then movie, by popularity."""
        candidates: list[dict] = []
        try:
            for media in ("tv", "movie"):
                data = await self._get(f"/search/{media}", query=title,
                                       include_adult="false", language="en-US")
                for item in data.get("results", [])[:5]:
                    item["_media"] = media
                    candidates.append(item)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("tmdb.search.failed", title=title, error=str(exc))
            return None
        if not candidates:
            return None
        # prefer TV, then higher popularity
        candidates.sort(key=lambda c: (c["_media"] == "tv", c.get("popularity", 0)),
                        reverse=True)
        top = candidates[0]
        return await self.details(top["id"], top["_media"])

    async def details(self, tmdb_id: int, media_type: str) -> TmdbResult | None:
        try:
            d = await self._get(f"/{media_type}/{tmdb_id}", language="en-US")
            backdrop_path = await self._english_backdrop(tmdb_id, media_type) \
                or d.get("backdrop_path")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("tmdb.details.failed", id=tmdb_id, error=str(exc))
            return None

        is_tv = media_type == "tv"
        title = d.get("name") if is_tv else d.get("title")
        date = d.get("first_air_date") if is_tv else d.get("release_date")
        res = TmdbResult(
            id=tmdb_id, media_type=media_type, title=title or "",
            year=(date or "")[:4] or None,
            genres=[g["name"] for g in d.get("genres", [])],
            rating=round(d["vote_average"], 1) if d.get("vote_average") else None,
            overview=d.get("overview", "") or "",
            seasons=d.get("number_of_seasons") if is_tv else None,
            episodes=d.get("number_of_episodes") if is_tv else None,
            poster_url=f"{IMG_BASE}/w500{d['poster_path']}" if d.get("poster_path") else None,
        )
        res._backdrop_path = backdrop_path
        res.backdrop_url = res.backdrop("original")
        return res

    async def _english_backdrop(self, tmdb_id: int, media_type: str) -> str | None:
        """Pick the best **English-tagged** backdrop, the way TMDB's
        ``/images/backdrops?image_language=en`` page shows them.

        These are the franchise backdrops that carry English title art / branding,
        which we want on the confirmation card. Strict preference order:

          1. images explicitly tagged ``iso_639_1 == "en"`` (highest quality first),
          2. language-neutral images (``null``) as a graceful fallback,
          3. anything else only as a last resort.

        Within each tier we rank by rating, then vote count, then resolution, so a
        zero-vote English backdrop still beats a popular neutral one.
        """
        try:
            imgs = await self._get(f"/{media_type}/{tmdb_id}/images",
                                   include_image_language="en,null")
        except (httpx.HTTPError, ValueError):
            return None
        backdrops = imgs.get("backdrops", [])
        if not backdrops:
            return None

        def quality(b: dict) -> tuple:
            return (b.get("vote_average") or 0,
                    b.get("vote_count") or 0,
                    b.get("width") or 0)

        english = sorted((b for b in backdrops if b.get("iso_639_1") == "en"),
                         key=quality, reverse=True)
        if english:
            return english[0].get("file_path")
        neutral = sorted((b for b in backdrops if not b.get("iso_639_1")),
                         key=quality, reverse=True)
        if neutral:
            return neutral[0].get("file_path")
        return sorted(backdrops, key=quality, reverse=True)[0].get("file_path")
