"""AniList metadata — franchise discovery, enrichment & relation resolution.

The single entry point for Phase 1 of the request flow: a user query is first
resolved through AniList to find the franchise, detect adaptations, and collect
full metadata (synopsis, genres, score, cover art, relation graph) before any
source plugin is touched.

Source plugins must never perform discovery searches — only AniList (with TMDB
as fallback) has that responsibility.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from nekofetch.core.logging import get_logger
from nekofetch.sources.telegram.matching import title_matches

log = get_logger(__name__)

ANILIST_URL = "https://graphql.anilist.co"
ANILIST_SITE = "https://anilist.co/anime"

# Candidate search — AniList's SEARCH_MATCH can rank an obscure short above the
# real show (e.g. "Demon Slayer" → a TV_SHORT with a matching synonym), so we
# fetch several and pick by title-match then popularity ourselves.
_PAGE_QUERY = """
query ($search: String) {
  Page(perPage: 10) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      popularity
      format
      title { romaji english native }
      synonyms
    }
  }
}
"""

# Full media query — fetches everything needed for a rich confirmation card.
_FULL_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    format
    season
    seasonYear
    episodes
    duration
    status
    nextAiringEpisode { episode }
    averageScore
    popularity
    favourites
    description(asHtml: false)
    genres
    studios(isMain: true) { nodes { name } }
    coverImage { large extraLarge }
    bannerImage
    title { romaji english native }
    synonyms
    relations {
      edges {
        relationType
        node {
          id
          format
          status
          episodes
          nextAiringEpisode { episode }
          title { romaji english native }
          coverImage { large }
        }
      }
    }
  }
}
"""

# Formats to treat as "seasons" (watchable series entries) for breakdown counts.
_SERIES_FORMATS = {"TV", "TV_SHORT"}
# Real anime formats (excludes MANGA / NOVEL / ONE_SHOT source material).
_ANIME_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}
# Installments that don't exist yet (or never will) — never part of the franchise
# the user can actually get. We are not a manga distributor and don't list vapor.
_EXCLUDED_STATUS = {"NOT_YET_RELEASED", "CANCELLED"}


def _aired_episodes(media: dict) -> int | None:
    """Best episode count for an entry: the final total when AniList knows it,
    else the number already aired (``nextAiringEpisode - 1``) for a still-running
    show, else ``None``. Stops a currently-airing series rendering as "?"."""
    eps = media.get("episodes")
    if eps:
        return eps
    nxt = (media.get("nextAiringEpisode") or {}).get("episode")
    if nxt and nxt > 1:
        return nxt - 1
    return None
# Relation kinds that represent actual franchise *content* (watchable). Excludes
# ADAPTATION (the source manga/novel), CHARACTER (joke shorts), OTHER, SOURCE.
_CONTENT_RELATIONS = {
    "SEQUEL", "PREQUEL", "SIDE_STORY", "ALTERNATIVE", "SPIN_OFF",
    "PARENT", "SUMMARY",
}
# Relations that continue the same continuity (collapse into "seasons").
_CONTINUATION_RELATIONS = {"SEQUEL", "PREQUEL"}
# Relations to follow when walking the franchise graph. ALTERNATIVE is excluded
# on purpose: it links *different adaptations* (Hellsing TV vs Hellsing Ultimate,
# Fate adaptations), which are separate versions, not part of one franchise total.
_TRAVERSE_RELATIONS = {
    "SEQUEL", "PREQUEL", "SIDE_STORY", "PARENT", "SPIN_OFF", "SUMMARY",
}

# Lightweight query to walk the relation graph: for a batch of ids, return each
# node's format/episodes plus its immediate edges (so BFS can expand outward).
_GRAPH_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) {
      id
      format
      status
      episodes
      nextAiringEpisode { episode }
      relations {
        edges {
          relationType
          node { id type format status episodes }
        }
      }
    }
  }
}
"""


@dataclass
class FranchiseTotals:
    """Aggregated counts across the *entire* connected franchise graph.

    A node is a **season** ONLY if it is a TV/TV_SHORT entry sitting in the root's
    SEQUEL/PREQUEL *continuity chain*. A TV series reached by any other relation
    (SPIN_OFF, SIDE_STORY, …) is a **spin-off**, never a season. Movies, OVAs,
    ONAs and specials are classified purely by format.
    """
    seasons: int = 0
    movies: int = 0
    ovas: int = 0
    onas: int = 0
    specials: int = 0
    spin_offs: int = 0     # TV/TV_SHORT NOT in the main continuity chain
    episodes: int = 0      # summed across season (TV/TV_SHORT) entries
    nodes: int = 0         # total installments discovered


@dataclass
class FranchiseRelation:
    """A single relation edge in the franchise graph."""
    relation: str                 # e.g. "SEQUEL", "PREQUEL", "SIDE_STORY"
    format: str | None
    status: str | None
    episodes: int | None
    titles: list[str] = field(default_factory=list)
    anilist_id: int | None = None
    cover_url: str | None = None


@dataclass
class AnilistMedia:
    """Full media data from AniList — used for the search→confirm flow.

    ``all_titles()`` and ``related_by_kind()`` from the previous model
    remain available; new fields support the rich confirmation card.
    """
    id: int
    format: str | None
    season: str | None
    year: int | None
    episodes: int | None
    duration: int | None          # minutes per episode
    status: str | None            # FINISHED, RELEASING, NOT_YET_RELEASED, CANCELLED
    score: float | None           # averageScore / 10
    popularity: int | None
    genres: list[str] = field(default_factory=list)
    synopsis: str | None = None
    studio: str | None = None
    cover_url: str | None = None  # large cover image
    banner_url: str | None = None
    english: str | None = None    # preferred display title
    romaji: str | None = None     # transliterated original
    titles: list[str] = field(default_factory=list)        # english/romaji/native
    synonyms: list[str] = field(default_factory=list)
    relations: list[FranchiseRelation] = field(default_factory=list)
    anilist_url: str | None = None

    # ── derived breakdown ──
    franchise_episodes: int | None = None   # total across all series entries
    franchise_seasons: int = 0              # number of TV/TV_SHORT entries
    franchise_movies: int = 0               # number of MOVIE entries
    franchise_ovas: int = 0                 # number of OVA entries
    franchise_onas: int = 0                 # number of ONA entries
    franchise_specials: int = 0             # number of SPECIAL entries

    def all_titles(self) -> list[str]:
        """Every title we can match against, including related entries' titles."""
        out: list[str] = list(self.titles) + list(self.synonyms)
        for rel in self.relations:
            out += rel.titles
        seen: set[str] = set()
        uniq = []
        for t in out:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                uniq.append(t)
        return uniq

    def related_by_kind(self, kinds: tuple[str, ...]) -> list[FranchiseRelation]:
        return [r for r in self.relations if r.relation in kinds]

    def series_relations(self) -> list[FranchiseRelation]:
        """Relations that are themselves series (sequels/prequels to watch)."""
        return [r for r in self.relations
                if r.format in _SERIES_FORMATS
                and r.relation in ("SEQUEL", "PREQUEL", "ALTERNATIVE", "SIDE_STORY")]

    def non_series_relations(self) -> list[FranchiseRelation]:
        """Movies, OVAs, specials, spin-offs."""
        return [r for r in self.relations if r.format not in _SERIES_FORMATS]


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

    async def _post(self, query: str, variables: dict) -> dict | None:
        """POST a GraphQL query with one retry on rate-limit / transient error.

        AniList enforces ~90 req/min and answers with 429 (+ ``Retry-After``) or
        an occasional 5xx. We honour the header once rather than failing outright.
        Returns the parsed ``data`` object, or ``None`` on a hard failure.
        """
        for attempt in (1, 2):
            try:
                resp = await self.http.post(
                    ANILIST_URL, json={"query": query, "variables": variables}
                )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                    retry_after = float(resp.headers.get("Retry-After") or 2)
                    log.warning("anilist.retry", status=resp.status_code,
                                retry_after=retry_after)
                    await asyncio.sleep(min(retry_after, 10.0))
                    continue
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("anilist.request.failed", error=str(exc))
                if attempt == 1:
                    await asyncio.sleep(1.0)
                    continue
                return None
            if payload.get("errors"):
                log.warning("anilist.graphql.errors", errors=payload["errors"])
            return payload.get("data")
        return None

    async def _best_id(self, query: str) -> int | None:
        """Pick the best candidate id.

        Ranking, strongest first: an exact (case-insensitive) title equality with
        the query, then fuzzy title-match strength, then popularity. The exact tier
        is essential — searching "Hellsing" must return the TV series even though
        the OVA ("Hellsing Ultimate") is far more popular.
        """
        data = await self._post(_PAGE_QUERY, {"search": query})
        media = (data or {}).get("Page", {}).get("media", [])
        if not media:
            return None

        norm_query = query.strip().lower()

        def primary_titles(m: dict) -> list[str]:
            t = m.get("title", {})
            return [x for x in (t.get("romaji"), t.get("english"), t.get("native")) if x]

        def all_titles(m: dict) -> list[str]:
            return primary_titles(m) + list(m.get("synonyms") or [])

        def rank(m: dict) -> tuple[int, float, int]:
            # Exact equality is checked on PRIMARY titles only: an obscure show
            # ("Onigiri") may carry the query as a fan-synonym ("Demon Slayer"),
            # which must not outrank the popular real match.
            exact = any(t.strip().lower() == norm_query for t in primary_titles(m))
            titles = all_titles(m)
            fuzzy = max((1.0 if title_matches(query, t, threshold=0.85) else 0.0)
                        for t in titles) if titles else 0.0
            return (1 if exact else 0, fuzzy, m.get("popularity") or 0)

        # Keep fuzzy matches when any exist, else fall back to the whole page.
        def matches(m: dict) -> bool:
            return any(title_matches(query, t, threshold=0.85) for t in all_titles(m))

        ranked = [m for m in media if matches(m)] or media
        ranked.sort(key=rank, reverse=True)
        return ranked[0].get("id")

    async def search(self, query: str) -> AnilistMedia | None:
        """Resolve ``query`` to a full AnilistMedia with relation breakdown.

        This is the sole discovery entry point — source plugins must not
        perform name searches.
        """
        media_id = await self._best_id(query)
        if media_id is None:
            return None
        return await self._fetch_full(media_id)

    async def _fetch_full(self, media_id: int) -> AnilistMedia | None:
        """Fetch full media data + relation breakdown for the given AniList id."""
        data = await self._post(_FULL_QUERY, {"id": media_id})
        media = (data or {}).get("Media")
        if not media:
            return None
        return self._parse_media(media)

    async def franchise_totals(self, root_id: int, *, max_nodes: int = 120) -> FranchiseTotals:
        """Walk the *whole* connected franchise graph from ``root_id`` and tally
        every installment by format.

        AniList only returns a node's immediate relations, so the breakdown on a
        single entry misses later seasons/cours/movies. We BFS outward, following
        only same-franchise edges (SEQUEL / PREQUEL / SIDE_STORY / PARENT /
        SPIN_OFF / SUMMARY — never ALTERNATIVE, which is a different adaptation),
        expanding a whole level per request via ``id_in`` batching so it stays fast.
        """
        visited: set[int] = {root_id}
        frontier: list[int] = [root_id]
        # id -> (format, episodes) for every node we actually resolve
        nodes: dict[int, tuple[str | None, int | None]] = {}
        # Continuity adjacency from SEQUEL/PREQUEL edges only — this is what
        # defines "seasons". Spin-offs/side-stories are deliberately NOT in here.
        cont_adj: dict[int, set[int]] = {}

        while frontier and len(visited) <= max_nodes:
            batch = frontier[:50]
            frontier = frontier[50:]
            data = await self._post(_GRAPH_QUERY, {"ids": batch})
            medias = (data or {}).get("Page", {}).get("media", [])
            if not medias:
                continue
            for m in medias:
                mid = m.get("id")
                if mid is None:
                    continue
                # Skip not-yet-released / cancelled installments entirely (but never
                # the root the user actually asked about). ``continue`` also skips
                # their edges, so we don't expand vapor branches into the totals.
                if mid != root_id and m.get("status") in _EXCLUDED_STATUS:
                    continue
                nodes[mid] = (m.get("format"), _aired_episodes(m))
                for edge in m.get("relations", {}).get("edges", []):
                    rtype = edge.get("relationType")
                    if rtype not in _TRAVERSE_RELATIONS:
                        continue
                    node = edge.get("node") or {}
                    nid = node.get("id")
                    if not (node.get("type") == "ANIME"
                            and node.get("format") in _ANIME_FORMATS
                            and node.get("status") not in _EXCLUDED_STATUS
                            and nid is not None):
                        continue
                    if rtype in _CONTINUATION_RELATIONS:  # SEQUEL / PREQUEL
                        cont_adj.setdefault(mid, set()).add(nid)
                        cont_adj.setdefault(nid, set()).add(mid)
                    if nid not in visited:
                        visited.add(nid)
                        frontier.append(nid)

        # Seasons = TV/TV_SHORT nodes reachable from the root through continuity
        # edges ONLY. Walk that component; spin-offs hang off non-continuity edges
        # and therefore never enter it.
        season_ids: set[int] = set()
        stack, seen = [root_id], {root_id}
        while stack:
            cur = stack.pop()
            if nodes.get(cur, (None, None))[0] in _SERIES_FORMATS:
                season_ids.add(cur)
            for nb in cont_adj.get(cur, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)

        totals = FranchiseTotals(nodes=len(nodes))
        for nid, (fmt, eps) in nodes.items():
            if fmt in _SERIES_FORMATS:
                if nid in season_ids:
                    totals.seasons += 1
                    totals.episodes += eps or 0
                else:                       # a TV series off the main line = spin-off
                    totals.spin_offs += 1
            elif fmt == "MOVIE":
                totals.movies += 1
            elif fmt == "OVA":
                totals.ovas += 1
            elif fmt == "ONA":
                totals.onas += 1
            elif fmt == "SPECIAL":
                totals.specials += 1
        # When the root isn't a TV season (it's an ONA/OVA/Special with its own
        # episode count), THAT count is the title's episode count — otherwise an
        # ONA-only entry like a 6-episode ONA would report 0 episodes. Spin-off and
        # side-story episode counts are still deliberately excluded.
        if root_id not in season_ids:
            root_fmt, root_eps = nodes.get(root_id, (None, None))
            if root_fmt and root_fmt != "MOVIE":
                totals.episodes += root_eps or 0
        return totals

    def _parse_media(self, media: dict) -> AnilistMedia:
        """Parse the raw GraphQL response into AnilistMedia with relation breakdown.

        Titles are ordered **English-first** (then romaji, then native) so the
        first element is the best display title — AniList stores e.g. the Hellsing
        OVA's romaji as "HELLSING OVA" but its English as "Hellsing Ultimate".
        """
        def titles_of(t: dict) -> list[str]:
            return [t.get("english"), t.get("romaji"), t.get("native")]

        title_dict = media.get("title", {})
        english = title_dict.get("english")
        romaji = title_dict.get("romaji")
        titles = [t for t in titles_of(title_dict) if t]

        relations = []
        for edge in media.get("relations", {}).get("edges", []):
            node = edge.get("node", {})
            fmt = node.get("format")
            status = node.get("status")
            # Only real, released anime installments belong in the franchise — no
            # manga/novel source material, no not-yet-released or cancelled entries.
            if fmt not in _ANIME_FORMATS or status in _EXCLUDED_STATUS:
                continue
            relations.append(FranchiseRelation(
                relation=edge.get("relationType", ""),
                format=fmt,
                status=status,
                episodes=_aired_episodes(node),
                titles=[t for t in titles_of(node.get("title", {})) if t],
                anilist_id=node.get("id"),
                cover_url=node.get("coverImage", {}).get("large"),
            ))

        # Derive franchise-level breakdown from *content* relations only — drop the
        # source manga (ADAPTATION), joke shorts (CHARACTER) and OTHER noise.
        content = [r for r in relations
                   if r.relation in _CONTENT_RELATIONS and r.format in _ANIME_FORMATS]
        # Seasons = the main entry + genuine continuations (SEQUEL/PREQUEL TV).
        # ALTERNATIVE is a separate adaptation/version, not a season of this one.
        season_entries = [r for r in content
                          if r.format in _SERIES_FORMATS
                          and r.relation in _CONTINUATION_RELATIONS]
        franchise_seasons = 1 + len(season_entries)
        franchise_movies = sum(1 for r in content if r.format == "MOVIE")
        franchise_ovas = sum(1 for r in content if r.format == "OVA")
        franchise_onas = sum(1 for r in content if r.format == "ONA")
        franchise_specials = sum(1 for r in content if r.format == "SPECIAL")

        # Total episodes across the main entry + its season continuations.
        total_ep = _aired_episodes(media) or 0
        for s in season_entries:
            if s.episodes is not None:
                total_ep += s.episodes

        studios = media.get("studios", {}).get("nodes", [])
        studio_name = studios[0]["name"] if studios else None

        cover = media.get("coverImage", {})
        cover_url = cover.get("extraLarge") or cover.get("large")

        score = media.get("averageScore")
        if score is not None:
            score = round(score / 10, 1)

        anilist_url = f"{ANILIST_SITE}/{media['id']}"

        return AnilistMedia(
            id=media["id"],
            format=media.get("format"),
            season=media.get("season"),
            year=media.get("seasonYear"),
            episodes=_aired_episodes(media),
            duration=media.get("duration"),
            status=media.get("status"),
            score=score,
            popularity=media.get("popularity"),
            genres=[g for g in media.get("genres", []) if g],
            synopsis=media.get("description"),
            studio=studio_name,
            cover_url=cover_url,
            banner_url=media.get("bannerImage"),
            english=english,
            romaji=romaji,
            titles=titles,
            synonyms=[s for s in media.get("synonyms", []) if s],
            relations=relations,
            anilist_url=anilist_url,
            franchise_episodes=total_ep or None,
            franchise_seasons=franchise_seasons,
            franchise_movies=franchise_movies,
            franchise_ovas=franchise_ovas,
            franchise_onas=franchise_onas,
            franchise_specials=franchise_specials,
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
