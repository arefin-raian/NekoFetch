"""Bot content generation — watch guide, season cards, info cards, footer.

After a distribution bot is created, we generate a set of pre-formatted posts that
mirror the reference channel layouts. These are stored in BotContentPost and
delivered in order when a user starts the bot.

Data sources:
  * AniList — titles, relations, episode/season counts, synopsis, score, genres
  * TMDB   — poster images, backdrops
  * Storage packs — actual resolutions/audio available

All text templates live in en.json and are configurable via the Settings panel.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType, ContentKind
from nekofetch.infrastructure.database.postgres.models import (
    BotContentPost,
    DistributionBot,
    StoragePack,
)
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.localization.messages import M, t
from nekofetch.ui import templates

log = get_logger(__name__)

_RES_ORDER = {"360p": 360, "480p": 480, "540p": 540, "720p": 720, "1080p": 1080}
_AUDIO_LANG = {
    AudioType.DUBBED: ["English"],
    AudioType.SUBBED: ["Japanese"],
    AudioType.DUAL_AUDIO: ["English", "Japanese"],
}
_BTN_QUALITIES = ("480p", "720p", "1080p")


class BotContentService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def generate_posts(self, bot_id: int, anime_doc_id: str) -> list[BotContentPost]:
        """Generate ALL content posts for a distribution bot and persist them.

        Produces, in order:
          1. Watch guide (pinned) — season listing with episode counts per season
          2. Info/overview card  — poster + full metadata (from AniList + TMDB)
          3. Season cards        — one per season, with quality buttons
          4. Footer              — cross-promotion branding card
        """
        # Remove any previously generated posts for this bot.
        async with session_scope(self._c.pg_sessionmaker) as session:
            old = await session.execute(
                select(BotContentPost).where(BotContentPost.bot_id == bot_id)
            )
            for p in old.scalars().all():
                await session.delete(p)

        # Gather the data we need.
        packs = await self._load_packs(anime_doc_id)
        bot = await self._load_bot(bot_id)
        meta = await self._gather_metadata(anime_doc_id)

        posts: list[BotContentPost] = []
        order = 0

        # Order mirrors the reference channels (top → bottom):
        #   1. Info/overview card  2. Season cards  3. Watch guide (pinned)  4. Footer

        # 1. Info/overview card.
        info_caption, info_image = await self._build_info_card(meta)
        if info_caption:
            posts.append(BotContentPost(
                bot_id=bot_id, post_type="info_card", order=order,
                caption=info_caption, image_url=str(info_image) if info_image else None,
            ))
            order += 1

        # 2. Season cards — one per season found in storage packs.
        seasons = sorted({p.season for p in packs if p.season is not None})
        for season in seasons:
            season_packs = [p for p in packs if p.season == season]
            caption, image = self._build_season_card(meta, season, season_packs)
            buttons = self._build_season_buttons(season_packs)
            posts.append(BotContentPost(
                bot_id=bot_id, post_type="season_card", season=season,
                order=order, caption=caption,
                image_url=str(image) if image else None,
                button_data=buttons,
            ))
            order += 1

        # 3. Watch guide (pinned) — near the end, just before the footer.
        guide = self._build_watch_guide(meta, packs)
        if guide:
            posts.append(BotContentPost(
                bot_id=bot_id, post_type="watch_guide", order=order,
                caption=guide, is_pinned=True,
            ))
            order += 1

        # 4. Footer.
        posts.append(BotContentPost(
            bot_id=bot_id, post_type="footer", order=order,
            caption=t(M.BOT_FOOTER),
        ))

        # Persist all posts.
        async with session_scope(self._c.pg_sessionmaker) as session:
            for p in posts:
                session.add(p)
            await session.flush()
            for p in posts:
                session.expunge(p)

        log.info("bot.content.generated", bot_id=bot_id, posts=len(posts))
        return posts

    # ── data loaders ──────────────────────────────────────────────────────────────

    async def _load_packs(self, anime_doc_id: str) -> list[StoragePack]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (await session.execute(
                select(StoragePack).where(
                    StoragePack.anime_doc_id == anime_doc_id,
                    StoragePack.enabled.is_(True),
                )
            )).scalars().all()
            return list(rows)

    async def _load_bot(self, bot_id: int) -> DistributionBot | None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            return await session.get(DistributionBot, bot_id)

    async def _gather_metadata(self, anime_doc_id: str) -> dict:
        """Collect metadata for the title, primarily via @acutebot with
        AniList/TMDB as fallback. Returns a flat dict."""
        from nekofetch.providers.acute_bot import fetch_from_acutebot

        meta: dict = {
            "title": anime_doc_id,
            "romaji": None,
            "english": None,
            "format": None,
            "status": None,
            "score": None,
            "genres": [],
            "synopsis": None,
            "episode_count": None,
            "season_count": None,
            "first_aired": None,
            "last_aired": None,
            "runtime": None,
            "poster_url": None,
            "banner_url": None,
            "_source": None,
        }

        # ── Primary: @acutebot via the userbot pool ──
        try:
            from nekofetch.sources.telegram.userbot import UserbotPool

            # Cache the pool on the container so we reuse the same Pyrogram
            # Client connections across calls instead of leaking new ones.
            pool: UserbotPool | None = getattr(self._c, "_userbot_pool", None)  # type: ignore[attr-defined]
            if pool is None:
                pool = UserbotPool.from_env(
                    self._c.env.telegram_api_id,
                    self._c.env.telegram_api_hash,
                    str(self._c.env.session_path),
                )
                self._c._userbot_pool = pool  # type: ignore[attr-defined]
            # Persistent directory where AcuteBot photos are saved.
            photo_dir = str(self._c.env.storage_path / "acutebot_cards")
            acute = await fetch_from_acutebot(anime_doc_id, pool, photo_dir=photo_dir)
            if acute is not None:
                meta.update(acute)
                meta["_source"] = "acutebot"
                log.info("bot.content.metadata.acutebot", anime=anime_doc_id, photo=acute.get("poster_url"))
                return meta
        except Exception as exc:
            log.debug("bot.content.acutebot.failed", anime=anime_doc_id, error=str(exc))

        # ── Fallback 1: AniList ──
        try:
            search = await self._c.anilist.search(anime_doc_id)
            if search is not None:
                meta["title"] = search.english or search.romaji or search.titles[0] if search.titles else anime_doc_id
                meta["romaji"] = search.romaji
                meta["english"] = search.english
                meta["format"] = search.format
                meta["status"] = search.status
                meta["score"] = str(search.score) if search.score else None
                meta["genres"] = search.genres or []
                meta["synopsis"] = search.synopsis
                meta["episode_count"] = search.franchise_episodes
                meta["season_count"] = search.franchise_seasons
                meta["_source"] = "anilist"
        except Exception as exc:
            log.warning("bot.content.anilist.failed", anime=anime_doc_id, error=str(exc))

        # ── Fallback 2: TMDB for poster + backdrop ──
        if not meta.get("poster_url"):
            try:
                url = await self._c.tmdb.poster_for(meta["title"])
                if url:
                    meta["poster_url"] = url
                result = await self._c.tmdb.search(meta["title"])
                if result is not None:
                    if result.backdrop_url:
                        meta["banner_url"] = result.backdrop_url
                    # Use TMDB overview as synopsis if we don't have one yet
                    if not meta.get("synopsis") and result.overview:
                        meta["synopsis"] = result.overview
            except Exception as exc:
                log.warning("bot.content.tmdb.failed", anime=anime_doc_id, error=str(exc))

        return meta

    # ── content builders ─────────────────────────────────────────────────────────

    def _build_watch_guide(self, meta: dict, packs: list[StoragePack]) -> str | None:
        """Build the watch guide using the season structure from storage packs."""
        seasons = sorted({p.season for p in packs if p.season is not None})
        if not seasons:
            return None

        season_lines = []
        for s in seasons:
            season_packs = [p for p in packs if p.season == s]
            ep_max = max((p.episode_to or p.file_count or 0) for p in season_packs)
            # Collect all qualities available across packs for this season.
            quals = sorted(
                {r for r in {p.resolution for p in season_packs} if r},
                key=lambda r: _RES_ORDER.get(r, 9999),
            )
            qual_str = "  ".join(quals) if quals else "480p  720p  1080p"
            season_label = self._season_label(s, meta)
            season_lines.append(t(
                M.BOT_WATCH_GUIDE_SEASON,
                season_label=season_label,
                episodes=ep_max or "—",
                qualities=qual_str,
            ))

        return t(M.BOT_WATCH_GUIDE, seasons="\n\n".join(season_lines))

    def _season_label(self, season: int, meta: dict) -> str:
        """Human-readable season label. """
        return f"Season {season:02d}"

    async def _build_info_card(self, meta: dict) -> tuple[str | None, str | None]:
        """Build the overview/info card from available metadata."""
        if not meta.get("title"):
            return None, None

        # Use the TMDB or AniList poster as the card image.
        image = meta.get("banner_url") or meta.get("poster_url")

        caption = t(
            M.BOT_INFO_CARD,
            title=meta.get("title", "—"),
            romaji=meta.get("romaji") or "",
            genres=", ".join(meta.get("genres", []) or []) or "—",
            format=meta.get("format") or "—",
            rating=meta.get("score") or "—",
            status=meta.get("status") or "—",
            # Use AcuteBot's parsed fields directly (release_date never existed here).
            first_aired=meta.get("first_aired") or "—",
            last_aired=meta.get("last_aired") or "—",
            runtime=meta.get("runtime") or "—",
            episodes=str(meta.get("episode_count") or "—"),
            synopsis=(meta.get("synopsis") or "")[:400] or "—",
        )
        return caption, image

    def _build_season_card(self, meta: dict, season: int, packs: list[StoragePack]) -> tuple[str, str | None]:
        """Build a season entry card matching the reference format."""
        ep_max = max((p.episode_to or p.file_count or 0) for p in packs)
        # Determine language from audio types, formatted like the reference channels:
        # dual/both → "Dual [English & Japanese]", single → just the language.
        audios = {p.audio for p in packs}
        langs: list[str] = []
        for a in audios:
            langs.extend(_AUDIO_LANG.get(a, []))
        langs = list(dict.fromkeys(langs))
        is_dual = AudioType.DUAL_AUDIO in audios or (
            AudioType.SUBBED in audios and AudioType.DUBBED in audios
        )
        if is_dual and langs:
            lang_str = f"Dual [{' & '.join(langs)}]"
        else:
            lang_str = " & ".join(langs) or "—"
        # Collect qualities.
        quals = sorted(
            {p.resolution for p in packs},
            key=lambda r: _RES_ORDER.get(r, 9999),
        )
        qual_str = ", ".join(quals) if quals else "Multi Quality"
        genres = ", ".join(meta.get("genres", []) or []) or "—"
        synopsis = (meta.get("synopsis") or "")[:300] or "—"
        score = meta.get("score") or "—"
        title = meta.get("title", "—")

        # Detect if this is a movie pack (single file, season=None-like).
        is_movie = any(
            p.season is None or (p.episode_from == p.episode_to and (p.episode_to or 0) <= 1)
            for p in packs
        )

        if is_movie:
            caption = t(
                M.BOT_MOVIE_CARD,
                title=title,
                duration=f"1h {ep_max or 0}m",
                language=lang_str,
                synopsis=synopsis,
            )
        else:
            caption = t(
                M.BOT_SEASON_CARD,
                title=title, season=season,
                episodes=ep_max or "—",
                S="S" if (ep_max or 0) != 1 else "",   # EPISODE vs EPISODES
                rating=score,
                language=lang_str,
                genres=genres,
                synopsis=synopsis,
            )

        # Use the same poster for all season cards.
        image = meta.get("poster_url")
        return caption, image

    def _build_season_buttons(self, packs: list[StoragePack]) -> dict | None:
        """Build the button layout for a season's quality options.

        For dual-audio packs: single row of quality buttons.
        For separate audio sources: language sections with quality buttons underneath.

        Currently generates placeholder buttons — real download URLs will come from
        file-store bots later.
        """
        quals = sorted(
            {p.resolution for p in packs},
            key=lambda r: _RES_ORDER.get(r, 9999),
        )

        # Take at most the 3 reference qualities (480p, 720p, 1080p).
        available = [q for q in _BTN_QUALITIES if q in quals]
        if not available:
            available = quals[:3]

        audios = {p.audio for p in packs}
        has_dual = AudioType.DUAL_AUDIO in audios
        has_separate = AudioType.SUBBED in audios and AudioType.DUBBED in audios

        if has_separate and not has_dual:
            # Separate audio: language → quality.
            return {
                "type": "separate_audio",
                "sections": [
                    {
                        "language": "english",
                        "label": t(M.BOT_LANG_ENGLISH),
                        "qualities": available,
                    },
                    {
                        "language": "japanese",
                        "label": t(M.BOT_LANG_JAPANESE),
                        "qualities": available,
                    },
                ],
            }

        # Dual-audio or single: flat quality row.
        return {
            "type": "flat",
            "qualities": available,
        }

    async def download_card_image(self, url: str, dest: Path) -> Path | None:
        """Download a card image to local storage for sending as a photo."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cli:
                r = await cli.get(url)
                r.raise_for_status()
                dest.write_bytes(r.content)
            return dest
        except Exception as exc:
            log.warning("bot.content.image_download.failed", url=url, error=str(exc))
            return None
