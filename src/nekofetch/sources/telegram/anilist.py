"""AniList metadata — alternative titles, synonyms, and related entries.

Used to widen Telegram title matching: a single user query ("Attack on Titan")
expands into every romaji/english/native title plus synonyms and related
seasons/movies/specials, so we can find the release however the channel named it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from nekofetch.core.logging import get_logger

log = get_logger(__name__)

ANILIST_URL = "https://graphql.anilist.co"

_SEARCH_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    format
    season
    seasonYear
    episodes
    title { romaji english native }
    synonyms
    relations {
      edges {
        relationType
        node {
          id
          format
          title { romaji english native }
        }
      }
    }
  }
}
"""


@dataclass
class AnilistMedia:
    id: int
    format: str | None
    season: str | None
    year: int | None
    episodes: int | None
    titles: list[str] = field(default_factory=list)        # romaji/english/native
    synonyms: list[str] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)    # {relation, format, titles}

    def all_titles(self) -> list[str]:
        """Every title we can match against, including related entries' titles."""
        out: list[str] = list(self.titles) + list(self.synonyms)
        for rel in self.relations:
            out += rel.get("titles", [])
        # de-dup preserving order
        seen: set[str] = set()
        uniq = []
        for t in out:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                uniq.append(t)
        return uniq

    def related_by_kind(self, kinds: tuple[str, ...]) -> list[dict]:
        return [r for r in self.relations if r.get("relation") in kinds]


class AnilistClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=20.0, headers={"Accept": "application/json"}
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def search(self, query: str) -> AnilistMedia | None:
        try:
            resp = await self.http.post(
                ANILIST_URL, json={"query": _SEARCH_QUERY, "variables": {"search": query}}
            )
            resp.raise_for_status()
            media = resp.json().get("data", {}).get("Media")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("anilist.search.failed", query=query, error=str(exc))
            return None
        if not media:
            return None

        def titles_of(t: dict) -> list[str]:
            return [t.get("romaji"), t.get("english"), t.get("native")]

        relations = []
        for edge in media.get("relations", {}).get("edges", []):
            node = edge.get("node", {})
            relations.append({
                "relation": edge.get("relationType"),
                "format": node.get("format"),
                "titles": [t for t in titles_of(node.get("title", {})) if t],
            })

        return AnilistMedia(
            id=media["id"],
            format=media.get("format"),
            season=media.get("season"),
            year=media.get("seasonYear"),
            episodes=media.get("episodes"),
            titles=[t for t in titles_of(media.get("title", {})) if t],
            synonyms=[s for s in media.get("synonyms", []) if s],
            relations=relations,
        )

    async def title_variants(self, query: str) -> list[str]:
        """All titles to try on Telegram for ``query`` (self + relations)."""
        media = await self.search(query)
        if not media:
            return [query]
        variants = [query, *media.all_titles()]
        seen: set[str] = set()
        out = []
        for t in variants:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out
