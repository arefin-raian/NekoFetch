"""Stats service — dynamic dataset statistics.

Actually visits the index channel to extract real published titles,
cross-references against the 148 canonical names, and maintains a
pinned stats message with structured breakdown.

Auto-refreshes on publish and at startup.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from nekofetch.core.constants import RULE_HEAVY
from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.infrastructure.database.postgres.models import StoragePack
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.localization.messages import M, t

log = get_logger(__name__)

_STATS_MSG_KEY = "nf:index:stats_msg_id"
_CANONICAL_PATH = Path("resources") / "canonical_names.json"

_CANONICAL_CACHE: dict[str, dict] | None = None
_CANONICAL_MTIME: float = 0.0


def _load_canonical_map() -> dict[str, dict]:
    """Load the canonical name map with mtime-based caching."""
    global _CANONICAL_CACHE, _CANONICAL_MTIME
    try:
        if not _CANONICAL_PATH.exists():
            return {}
        mtime = _CANONICAL_PATH.stat().st_mtime
        if _CANONICAL_CACHE is not None and mtime <= _CANONICAL_MTIME:
            return _CANONICAL_CACHE
        _CANONICAL_CACHE = json.loads(_CANONICAL_PATH.read_text(encoding="utf-8"))
        _CANONICAL_MTIME = mtime
        return _CANONICAL_CACHE
    except Exception as exc:
        log.warning("stats.canonical_map.load_failed", error=str(exc))
        return {}


class StatsService:
    def __init__(self, container: Container) -> None:
        self._c = container

    # ── channel scraping ──────────────────────────────────────────────────────

    async def _fetch_index_channel_titles(self) -> set[str]:
        """Visit the index channel and extract ALL published titles from letter posts.

        Each letter has a single message that looks like::

            ------- A -------
            ⦿ Attack on Titan
            ⦿ Another

        Message IDs are tracked in Redis (``nf:index:letter:{letter}``) by
        :class:`IndexChannelService`. All letter messages are fetched in a
        single ``get_messages()`` batch call (1 API call, not 27).

        Returns empty set if unreachable or no letter messages exist yet.
        """
        cfg = self._c.config.index_channel
        client = getattr(self._c, "admin_client", None)
        if not (cfg.enabled and cfg.channel_id != 0 and client is not None):
            return set()

        letters = [chr(i) for i in range(ord("A"), ord("Z") + 1)] + ["#"]

        # Collect all existing letter message IDs in one pass
        letter_ids: list[int] = []
        if self._c.redis:
            for letter in letters:
                mid = await self._c.redis.get(f"nf:index:letter:{letter}")
                if mid:
                    letter_ids.append(int(mid))
        if not letter_ids:
            log.info("stats.index_channel.no_letters_yet")
            return set()

        # Single API call for all letter messages
        titles: set[str] = set()
        try:
            msgs = await client.get_messages(cfg.channel_id, letter_ids)
            for msg in msgs:
                if not msg or not msg.text:
                    continue
                for line in msg.text.split("\n"):
                    line = line.strip()
                    if line.startswith("⦿"):
                        title = line.removeprefix("⦿").strip()
                        if title:
                            titles.add(title)
        except Exception as exc:
            log.warning("stats.fetch_index.failed", error=str(exc))

        log.info("stats.index_channel.titles", count=len(titles))
        return titles

    # ── data queries ──────────────────────────────────────────────────────────

    async def _all_series(self) -> dict[str, str]:
        """Return {anime_doc_id: anime_title} for all series in storage."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (
                await session.execute(
                    select(StoragePack.anime_doc_id, StoragePack.anime_title)
                )
            ).all()
        seen: dict[str, str] = {}
        for doc_id, title in rows:
            if doc_id not in seen:
                seen[doc_id] = title
        return seen

    # ── title matching ────────────────────────────────────────────────────────

    @staticmethod
    def _match_canonical_name(title: str, cm: dict[str, dict]) -> str | None:
        """Match a title against the canonical names map.

        Resolution order:
        1. Case-insensitive match on canonical_name values
        2. Case-insensitive match on map keys
        3. Normalized match (alphanumeric only)
        """
        tl = title.lower().strip()

        # 1. Match by canonical_name values
        for info in cm.values():
            cn = info.get("canonical_name", "")
            if cn.lower().strip() == tl:
                return cn

        # 2. Match by original keys (old PACK_TREE keys)
        for our_key, info in cm.items():
            if our_key.lower().strip() == tl:
                return info.get("canonical_name") or our_key

        # 3. Normalized match — strip all non-alphanumeric
        def norm(s: str) -> str:
            return "".join(c for c in s if c.isalnum()).lower()

        nt = norm(title)
        for info in cm.values():
            cn = info.get("canonical_name", "")
            if norm(cn) == nt:
                return cn
        for our_key, info in cm.items():
            if norm(our_key) == nt:
                return info.get("canonical_name") or our_key

        return None

    # ── compute ───────────────────────────────────────────────────────────────

    async def compute(self) -> dict:
        """Compute the full stats snapshot.

        Source of truth for "published" is the index channel — scrapes its
        letter posts and cross-references against StoragePack + canonical names.
        """
        all_series = await self._all_series()
        indexed_titles = await self._fetch_index_channel_titles()
        cm = _load_canonical_map()

        # Build normalized set of indexed titles (both raw + canonical forms)
        indexed_norm: set[str] = set()
        for t_ in indexed_titles:
            indexed_norm.add(t_.lower().strip())
            matched = self._match_canonical_name(t_, cm)
            if matched:
                indexed_norm.add(matched.lower().strip())

        # Determine which series are published (found in index channel)
        published_set: set[str] = set()
        for doc_id, db_title in all_series.items():
            check = db_title.lower().strip()
            if check in indexed_norm:
                published_set.add(doc_id)
                continue
            matched = self._match_canonical_name(db_title, cm)
            if matched and matched.lower().strip() in indexed_norm:
                published_set.add(doc_id)

        total = len(all_series)
        published_count = len(published_set)
        not_indexed_count = total - published_count

        # Build not_indexed list with official names
        not_indexed_titles: list[str] = []
        for doc_id, db_title in all_series.items():
            if doc_id in published_set:
                continue
            matched = self._match_canonical_name(db_title, cm)
            not_indexed_titles.append(matched or db_title)

        return {
            "total_series": total,
            "published_series": published_count,
            "not_indexed_series": not_indexed_count,
            "not_indexed_titles": sorted(set(not_indexed_titles)),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }

    # ── message display ───────────────────────────────────────────────────────

    @staticmethod
    def _format_message(stats: dict) -> str:
        """Build a clean, structured HTML stats message."""
        parts: list[str] = []

        parts.append(t(M.STATS_TITLE))
        parts.append(RULE_HEAVY)
        parts.append("")

        parts.append(t(M.STATS_OVERVIEW))
        parts.append(t(M.STATS_ROW, label=t(M.STATS_TOTAL), value=stats["total_series"]))
        parts.append(t(M.STATS_ROW, label=t(M.STATS_PUBLISHED), value=stats["published_series"]))
        parts.append(t(M.STATS_ROW, label=t(M.STATS_NOT_INDEXED), value=stats["not_indexed_series"]))
        parts.append("")

        titles = stats.get("not_indexed_titles", [])
        parts.append(t(M.STATS_PENDING_TITLE))
        if titles:
            for title in titles:
                safe = html.escape(title, quote=False)
                parts.append(t(M.STATS_ENTRY, title=safe))
        else:
            parts.append(t(M.STATS_NONE_PENDING))
        parts.append("")

        parts.append(RULE_HEAVY)
        parts.append(t(M.STATS_UPDATED, ts=stats["ts"]))

        return "\n".join(parts)

    # ── refresh (post/edit/pin) ───────────────────────────────────────────────

    async def refresh(self) -> int | None:
        """Compute current stats and refresh the pinned stats message.

        Visits the index channel to get real published titles, then posts/pins
        a stats message showing total vs published vs not-indexed with official
        English names.
        """
        cfg = self._c.config.index_channel
        client = getattr(self._c, "admin_client", None)
        if not (cfg.enabled and cfg.channel_id != 0 and client is not None):
            return None

        stats = await self.compute()
        text = self._format_message(stats)
        channel_id = cfg.channel_id

        # Guard: skip creating a new message if no series published yet
        if stats["total_series"] > 0 and stats["published_series"] == 0:
            log.info("stats.refresh.skipped_no_published_yet")
            raw = await self._c.redis.get(_STATS_MSG_KEY) if self._c.redis else None
            if raw:
                try:
                    await client.edit_message_text(channel_id, int(raw), text)
                except Exception:
                    pass
            return None

        raw = await self._c.redis.get(_STATS_MSG_KEY) if self._c.redis else None
        existing_id = int(raw) if raw else None

        try:
            if existing_id:
                await client.edit_message_text(channel_id, existing_id, text)
                log.info("stats.msg.updated", message_id=existing_id, total=stats["total_series"])
                return existing_id

            msg = await client.send_message(channel_id, text)
            await client.pin_chat_message(channel_id, msg.id, disable_notification=True)
            if self._c.redis:
                await self._c.redis.set(_STATS_MSG_KEY, msg.id)
            log.info("stats.msg.created", message_id=msg.id)
            return msg.id
        except Exception as exc:
            log.warning("stats.refresh.failed", error=str(exc))
            return None
