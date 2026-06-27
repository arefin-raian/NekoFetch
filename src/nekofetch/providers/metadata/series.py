"""Series resolution — collapse seasons, split genuinely distinct versions.

A user query maps to either ONE series (its seasons are part of it — Attack on
Titan) or to several DISTINCT versions the user must choose between (Hellsing vs
Hellsing Ultimate, Fullmetal Alchemist vs Brotherhood, Naruto vs Naruto
Shippuuden). We decide using AniList relations:

  * ALTERNATIVE (a separate adaptation)            → distinct version
  * SEQUEL/PREQUEL whose title is just "<base> Season N / Part N / Final Season"
                                                    → same series (collapse)
  * SEQUEL/PREQUEL with a *named* continuation
        ("Shippuuden", "Brotherhood")               → distinct version
  * SIDE_STORY / SPIN_OFF / SUMMARY / movies-as-side-story
                                                    → extras, not user-facing versions
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nekofetch.core.logging import get_logger
from nekofetch.sources.telegram.anilist import AnilistClient, FranchiseRelation
from nekofetch.sources.telegram.matching import normalize_words

log = get_logger(__name__)

# Tokens that mark "another season of the same show" rather than a new series.
_SEASON_MARKERS = {
    "season", "seasons", "part", "cour", "final", "nd", "rd", "th", "st",
    "2nd", "3rd", "4th", "5th", "ii", "iii", "iv", "v", "vi",
}
# Tokens that mark a story ARC within the same series (collapse even when the arc
# has a proper name): the Japanese arc suffix "-hen", literal "arc", and the
# R2/R3 sequel-season style. A pure named continuation (e.g. "Shippuuden") has
# none of these → stays a distinct entry.
_ARC_INDICATORS = {"hen", "arc"}
_FULL_FORMATS = {"TV", "TV_SHORT", "ONA"}          # a "watchable series" version
_DISTINCT_RELATIONS = {"ALTERNATIVE"}              # always a separate version
_CONTINUATION_RELATIONS = {"SEQUEL", "PREQUEL"}


@dataclass
class SeriesEntry:
    title: str
    anilist_id: int | None
    format: str | None
    relation: str                 # "SELF" or the AniList relationType
    aliases: list[str] = field(default_factory=list)


@dataclass
class SeriesResolution:
    query: str
    entries: list[SeriesEntry] = field(default_factory=list)

    @property
    def multiple(self) -> bool:
        return len(self.entries) > 1

    @property
    def single(self) -> SeriesEntry | None:
        return self.entries[0] if self.entries else None


def _token_is_marker(tok: str) -> bool:
    return (tok.isdigit() or tok in _SEASON_MARKERS
            or bool(re.fullmatch(r"[ivx]+", tok)) or bool(re.fullmatch(r"r\d", tok)))


def _is_season_continuation(base_titles: list[str], rel_titles: list[str]) -> bool:
    """True if ``rel`` is just another SEASON or ARC of the base (→ collapse)."""
    base_words: set[str] = set()
    for t in base_titles:
        base_words |= normalize_words(t)
    # Collapse if ANY title form looks like a continuation: empty leftover, all
    # season markers, or an arc indicator. The marker may appear in only one form
    # (e.g. romaji "Mugen Ressha-hen" / english "… Mugen Train Arc"), so we check
    # every title rather than just the shortest diff.
    for rt in rel_titles:
        extra = normalize_words(rt) - base_words
        if (not extra
                or all(_token_is_marker(t) for t in extra)
                or bool(extra & _ARC_INDICATORS)):
            return True
    return False


def _is_distinct_version(base_titles: list[str], rel: FranchiseRelation) -> bool:
    fmt = rel.format
    rtype = rel.relation
    titles = rel.titles
    if not titles or fmt not in _FULL_FORMATS | {"OVA"}:
        return False
    if rtype in _DISTINCT_RELATIONS:
        # A separate adaptation that is itself a full series (Fullmetal Alchemist
        # vs Brotherhood) is always a distinct version. An ALTERNATIVE *OVA* is
        # only a real "version" when it's substantial (Hellsing Ultimate, 10 eps)
        # — single-episode pilots / recaps / PVs are also tagged ALTERNATIVE and
        # must not show up as choices (One Piece "Romance Dawn", "MONSTERS").
        if fmt in {"TV", "TV_SHORT"}:
            return True
        if fmt in {"OVA", "ONA"}:
            return bool(rel.episodes and rel.episodes >= 2)
    # A named continuation worth choosing is a real broadcast series (Naruto →
    # Shippuuden). One-off ONA/short prequels (One Piece "MONSTERS") are extras.
    if rtype in _CONTINUATION_RELATIONS and fmt in {"TV", "TV_SHORT"}:
        return not _is_season_continuation(base_titles, titles)
    return False


class SeriesResolver:
    def __init__(self, anilist: AnilistClient | None = None) -> None:
        self.anilist = anilist or AnilistClient()

    async def close(self) -> None:
        await self.anilist.close()

    async def resolve(self, query: str) -> SeriesResolution:
        """Resolve a query into one series (seasons collapsed) or several versions."""
        media = await self.anilist.search(query)
        if not media:
            return SeriesResolution(query=query, entries=[])

        base = SeriesEntry(
            title=media.titles[0] if media.titles else query,
            anilist_id=media.id, format=media.format, relation="SELF",
            aliases=media.all_titles(),
        )
        entries = [base]
        seen = {base.title.lower()}
        for rel in media.relations:
            if _is_distinct_version(media.titles, rel):
                title = rel.titles[0]
                if title.lower() in seen:
                    continue
                seen.add(title.lower())
                entries.append(SeriesEntry(
                    title=title, anilist_id=rel.anilist_id, format=rel.format,
                    relation=rel.relation, aliases=rel.titles,
                ))
        return SeriesResolution(query=query, entries=entries)
