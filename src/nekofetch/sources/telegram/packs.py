"""Pack-structure discovery for Telegram anime channels.

Channels organize releases very differently — per-episode files, season "packs"
(zips/multi-files), separate resolution albums, movies and specials mixed in.
This builds a generalized catalog from a channel's media messages by parsing each
file's name/caption (reusing the release-name heuristics) and grouping by
season → episode → resolution, with movies and specials kept aside.

The heuristics are intentionally general and pattern-based rather than per-channel;
anything genuinely ambiguous is surfaced under ``unresolved`` so it can be
escalated to the channel maintainers instead of being silently mis-filed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nekofetch.sources._torrent import VIDEO_EXT, parse_release_meta

# Archive/season-pack indicators.
_PACK_RE = re.compile(
    r"\b(batch|complete|season\s*pack|s\d+\s*pack|\d+\s*-\s*\d+)\b", re.IGNORECASE
)
_ARCHIVE_EXT = (".zip", ".rar", ".7z")


@dataclass
class TgMedia:
    msg_id: int
    file_name: str
    caption: str = ""
    size: int = 0
    # filled by discovery:
    kind: str = "episode"           # episode | movie | special | ova | extra | pack
    season: int = 1
    episode: int | None = None
    resolution: str | None = None


@dataclass
class EpisodeEntry:
    season: int
    episode: int
    seq: int
    files: dict[str, TgMedia] = field(default_factory=dict)   # resolution -> media
    title: str = ""

    @property
    def resolutions(self) -> list[str]:
        return sorted(
            self.files,
            key=lambda r: int(r.rstrip("p")) if r.rstrip("p").isdigit() else 0,
        )


@dataclass
class Catalog:
    seasons: dict[int, list[EpisodeEntry]] = field(default_factory=dict)
    movies: list[TgMedia] = field(default_factory=list)
    specials: list[TgMedia] = field(default_factory=list)
    packs: list[TgMedia] = field(default_factory=list)
    unresolved: list[TgMedia] = field(default_factory=list)

    def episode_count(self) -> int:
        return sum(len(eps) for eps in self.seasons.values())


def _best_text(m: TgMedia) -> str:
    """Caption often holds richer naming than the (sometimes generic) filename."""
    name = m.file_name or ""
    cap = m.caption or ""
    # prefer whichever yields an episode/season signal
    pm = parse_release_meta(name)
    if pm["episode"] is None and cap:
        cm = parse_release_meta(cap + ".mkv")
        if cm["episode"] is not None:
            return cap + ".mkv"
    return name


def classify(m: TgMedia) -> TgMedia:
    """Fill kind/season/episode/resolution for one media item."""
    lower = (m.file_name + " " + m.caption).lower()
    if m.file_name.lower().endswith(_ARCHIVE_EXT) or _PACK_RE.search(lower):
        meta = parse_release_meta(_best_text(m))
        m.kind = "pack"
        m.season = meta["season"]
        m.resolution = meta["resolution"]
        return m
    if not m.file_name.lower().endswith(VIDEO_EXT) and not m.caption:
        m.kind = "extra"
        return m
    meta = parse_release_meta(_best_text(m))
    m.kind = meta["kind"]
    m.season = meta["season"]
    m.episode = meta["episode"]
    m.resolution = meta["resolution"] or _resolution_from(lower)
    return m


def _resolution_from(text: str) -> str | None:
    m = re.search(r"(480|540|720|1080|2160)p?", text)
    return f"{m.group(1)}p" if m else None


def discover(media: list[TgMedia]) -> Catalog:
    """Build a structured catalog from a channel's media messages."""
    cat = Catalog()
    episodes: dict[tuple[int, int], EpisodeEntry] = {}

    for m in media:
        classify(m)
        if m.kind == "pack":
            cat.packs.append(m)
        elif m.kind == "movie":
            cat.movies.append(m)
        elif m.kind in ("special", "ova"):
            cat.specials.append(m)
        elif m.kind == "episode" and m.episode is not None:
            key = (m.season, m.episode)
            entry = episodes.get(key)
            if entry is None:
                entry = EpisodeEntry(season=m.season, episode=m.episode, seq=0,
                                     title=m.file_name)
                episodes[key] = entry
            entry.files[m.resolution or "unknown"] = m
        else:
            cat.unresolved.append(m)

    # order per season and assign EP sequence
    for season in sorted({k[0] for k in episodes}):
        eps = [episodes[k] for k in sorted(episodes) if k[0] == season]
        for seq, e in enumerate(eps, start=1):
            e.seq = seq
        cat.seasons[season] = eps
    return cat


def summarize(cat: Catalog) -> dict:
    """Compact, serialisable summary of a discovered catalog."""
    return {
        "seasons": {
            s: {
                "episodes": len(eps),
                "resolutions": sorted({r for e in eps for r in e.files}),
                "range": [eps[0].episode, eps[-1].episode] if eps else [],
            }
            for s, eps in cat.seasons.items()
        },
        "movies": len(cat.movies),
        "specials": len(cat.specials),
        "packs": len(cat.packs),
        "unresolved": len(cat.unresolved),
    }
