"""Website source report — compare AniKoto vs KickAssAnime before downloading.

When staff route a request to a website source, we don't blindly pick one. We
fetch each site's coverage (episode totals + sub/dub availability), lay it next to
what AniList expects, and surface the inconsistencies — so the decision of which
source to prefer (and whether we need both) is made on evidence, not a guess.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.sources.base import SourceCoverage

log = get_logger(__name__)

# Continuity-relation order ≈ release order for the main line.
_REL_ORDER = {"PREQUEL": 0, "SELF": 1, "PARENT": 1, "SEQUEL": 2,
              "SIDE_STORY": 3, "SPIN_OFF": 4, "SUMMARY": 5, "ALTERNATIVE": 6}


@dataclass(slots=True)
class WebsiteReport:
    title: str
    anilist_episodes: int | None
    anilist_seasons: int | None
    tree: list[dict] = field(default_factory=list)        # ordered installments
    coverages: list[SourceCoverage] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)
    recommended: str | None = None                        # source name


def _ordered_tree(franchise: dict) -> list[dict]:
    """Installments in (approx) release order: prequels → self → sequels → extras."""
    rows: list[dict] = [{
        "relation": "SELF", "title": franchise.get("title", "—"),
        "format": franchise.get("format"), "episodes": franchise.get("franchise_episodes"),
    }]
    for r in franchise.get("relations", []):
        rows.append({
            "relation": r.get("relation"),
            "title": (r.get("titles") or ["—"])[0],
            "format": r.get("format"),
            "episodes": r.get("episodes"),
        })
    rows.sort(key=lambda r: _REL_ORDER.get(r.get("relation") or "", 9))
    return rows


def _analyze(expected: int | None, covs: list[SourceCoverage]) -> tuple[list[str], str | None]:
    """Turn raw coverage into plain-English findings + a recommendation."""
    lines: list[str] = []
    live = [c for c in covs if c.available]
    if not live:
        return ["Neither source returned a usable match."], None

    for c in covs:
        name = c.source.title()
        if not c.available:
            lines.append(f"❌ {name}: no usable match ({c.note or 'unavailable'}).")
            continue
        approx = " (approx.)" if c.approximate else ""
        if expected and c.total_episodes < expected:
            lines.append(f"⚠️ {name}: {c.total_episodes} eps — {expected - c.total_episodes} "
                         f"short of AniList's {expected}.")
        elif expected and c.total_episodes > expected:
            lines.append(f"ℹ️ {name}: {c.total_episodes} eps — more than AniList's {expected} "
                         "(likely specials/recaps).")
        elif expected:
            lines.append(f"✅ {name}: {c.total_episodes} eps — matches AniList.")
        else:
            lines.append(f"• {name}: {c.total_episodes} eps.")
        # Sub/dub variance — the dangerous case (e.g. 220 sub / 3 dub).
        if c.sub_episodes and c.dub_episodes and c.dub_episodes < c.sub_episodes * 0.6:
            lines.append(f"⚠️ {name}: dub covers only {c.dub_episodes} of {c.sub_episodes} "
                         f"subbed eps{approx} — dub is incomplete.")

    # Recommendation: the available source closest to (but not under) AniList, with
    # the most total episodes, breaking ties on dub completeness.
    def score(c: SourceCoverage) -> tuple:
        complete = c.dub_episodes >= c.sub_episodes if c.sub_episodes else True
        return (c.total_episodes, complete, -int(c.approximate))

    best = max(live, key=score)
    recommended = best.source
    other = next((c for c in live if c.source != best.source), None)
    if other and abs(best.total_episodes - other.total_episodes) <= 1 \
            and best.dub_episodes != other.dub_episodes:
        lines.append(f"💡 Totals are close, but audio coverage differs — consider "
                     f"{best.source.title()} primary with {other.source.title()} as fallback.")
    else:
        lines.append(f"💡 Recommended primary: <b>{recommended.title()}</b> "
                     f"({best.total_episodes} eps).")
    return lines, recommended


async def build_website_report(container: Container, *, title: str,
                               franchise: dict) -> WebsiteReport:
    """Fetch coverage from both website sources concurrently and analyse it."""
    expected = franchise.get("franchise_episodes")
    seasons = franchise.get("franchise_seasons")
    report = WebsiteReport(title=title, anilist_episodes=expected, anilist_seasons=seasons,
                           tree=_ordered_tree(franchise))
    # Match on BOTH English and Romaji so the site result is provably the same show.
    titles = [t for t in (franchise.get("english") or title, franchise.get("romaji")) if t]

    async def _cov(name: str) -> SourceCoverage:
        try:
            src = container.sources.get(name)
        except Exception:
            return SourceCoverage(source=name, matched_title=title, source_ref="",
                                  available=False, note="source not active")
        try:
            cov = await src.coverage(*titles)
            return cov or SourceCoverage(source=name, matched_title=title, source_ref="",
                                         available=False, note="no report")
        except Exception as exc:  # noqa: BLE001
            log.warning("website_report.coverage.failed", source=name, error=str(exc))
            return SourceCoverage(source=name, matched_title=title, source_ref="",
                                  available=False, note="error")

    report.coverages = list(await asyncio.gather(_cov("anikoto"), _cov("kickassanime")))
    report.analysis, report.recommended = _analyze(expected, report.coverages)
    return report
