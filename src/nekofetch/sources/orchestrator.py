"""Multi-source fallback download orchestration.

Reliability rule for the whole downloader: try the preferred source first, but if
it yields no result, times out, or the download itself fails, automatically fall
back — first to the next candidate release/server *within* the source, then to
the next source entirely. The task only fails when **every** source is exhausted.

Works uniformly over the ``AnimeSource`` interface, so it covers the streaming
sources (KickAssAnime, AniKoto) and the torrent source (Nyaa) alike.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from nekofetch.core.logging import get_logger
from nekofetch.sources.base import AnimeSource, VideoVariant

log = get_logger(__name__)


async def _try_variants(
    source: AnimeSource, variants: list[VideoVariant], dest: Path,
) -> dict | None:
    """Try each variant of an episode until one downloads (server fallback)."""
    for variant in variants:
        try:
            return await source.download(variant, dest)
        except Exception as exc:  # noqa: BLE001 - try the next variant
            log.debug("orch.variant.failed", source=source.name, error=str(exc))
    return None


async def _try_source(
    source: AnimeSource,
    query: str,
    dest: Path,
    *,
    episode: int,
    max_candidates: int,
) -> dict | None:
    """Search one source and try its top candidates until a download succeeds."""
    try:
        results = await source.search(query)
    except Exception as exc:  # noqa: BLE001
        log.warning("orch.search.failed", source=source.name, error=str(exc))
        return None
    if not results:
        log.info("orch.no_results", source=source.name, query=query)
        return None

    for rank, stub in enumerate(results[:max_candidates]):
        try:
            episodes = await source.get_episodes(stub.source_ref)
        except Exception as exc:  # noqa: BLE001
            log.debug("orch.episodes.failed", source=source.name, error=str(exc))
            continue
        if not episodes:
            continue
        ep = next((e for e in episodes if e.number == episode), None) or episodes[0]
        try:
            variants = await source.get_variants(ep.source_ref)
        except Exception as exc:  # noqa: BLE001
            log.debug("orch.variants.failed", source=source.name, error=str(exc))
            continue
        if not variants:
            continue
        result = await _try_variants(source, variants, dest)
        if result:
            result.setdefault("source", source.name)
            result.setdefault("release", stub.title)
            result.setdefault("candidate_rank", rank)
            log.info("orch.ok", source=source.name, rank=rank, release=stub.title[:60])
            return result
        log.info("orch.candidate.exhausted", source=source.name, rank=rank)
    return None


async def download_with_fallback(
    sources: Sequence[AnimeSource],
    query: str,
    dest: Path,
    *,
    episode: int = 1,
    max_candidates: int = 3,
    per_source_timeout: float = 1800.0,
) -> dict:
    """Download ``episode`` of ``query`` from the first source that succeeds.

    ``sources`` are tried in order (preferred first). For each: candidate releases
    and per-episode variants/servers are tried before moving on. A source that
    exceeds ``per_source_timeout`` is abandoned and the next is tried. Raises
    ``RuntimeError`` only if every source is exhausted.
    """
    attempts: list[str] = []
    for source in sources:
        log.info("orch.try_source", source=source.name, query=query)
        try:
            result = await asyncio.wait_for(
                _try_source(source, query, dest,
                            episode=episode, max_candidates=max_candidates),
                timeout=per_source_timeout,
            )
        except TimeoutError:
            attempts.append(f"{source.name}: timed out")
            log.warning("orch.source.timeout", source=source.name)
            continue
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{source.name}: {exc}")
            continue
        if result:
            result["attempts"] = attempts + [f"{source.name}: ok"]
            return result
        attempts.append(f"{source.name}: no usable release")

    raise RuntimeError(
        f"all {len(sources)} sources exhausted for {query!r}: {attempts}"
    )
