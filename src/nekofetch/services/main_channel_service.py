"""Main channel service.

Posts each published anime to the public main channel: poster + a templated caption
(episodes / quality / language / genre / overview) with two buttons — **Index** (links to
the index-channel letter post) and **Download** (deep-links to the title's distribution
bot). Posts are tracked in ``ChannelPost`` so they can be edited in place.

Facts are assembled from the stored packs (qualities, languages, episode count) and, when
available, the metadata enrichment layer (genres, overview, poster, studio tag).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType
from nekofetch.infrastructure.database.postgres.models import (
    ChannelPost,
    DistributionBot,
    StoragePack,
)
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.ui import templates

log = get_logger(__name__)

_RES_ORDER = {"360p": 360, "480p": 480, "540p": 540, "720p": 720, "1080p": 1080}
# Audio track language as the user thinks of it: Dub = English, Sub = Japanese (Eng subs).
_AUDIO_LANG = {
    AudioType.DUBBED: ["English"],
    AudioType.SUBBED: ["Japanese"],
    AudioType.DUAL_AUDIO: ["English", "Japanese"],
    AudioType.MULTI: ["English", "Japanese", "Hindi"],
}


@dataclass(slots=True)
class PublicationFacts:
    anime_doc_id: str
    title: str
    tag: str = "Anime"
    episodes: str = "—"
    qualities: str = "—"
    languages: str = "—"
    genres: str = "—"
    overview: str = "—"
    poster_url: str | None = None
    backdrop_url: str | None = None   # TMDB English 16:9 backdrop for the post photo
    bot_username: str | None = None
    _audios: set = field(default_factory=set)


class MainChannelService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self.cfg = container.config.main_channel

    def _active(self) -> bool:
        client = getattr(self._c, "admin_client", None)
        return bool(self.cfg.enabled and self.cfg.channel_id != 0 and client is not None)

    async def gather_facts(self, anime_doc_id: str) -> PublicationFacts:
        async with session_scope(self._c.pg_sessionmaker) as session:
            packs = (
                await session.execute(
                    select(StoragePack).where(StoragePack.anime_doc_id == anime_doc_id)
                )
            ).scalars().all()
            bot = (
                await session.execute(
                    select(DistributionBot).where(
                        DistributionBot.anime_doc_id == anime_doc_id,
                        DistributionBot.enabled.is_(True),
                    )
                )
            ).scalars().first()

        facts = PublicationFacts(anime_doc_id=anime_doc_id, title=anime_doc_id)
        if packs:
            facts.title = packs[0].anime_title
            resolutions = sorted({p.resolution for p in packs},
                                  key=lambda r: _RES_ORDER.get(r, 9999))
            facts.qualities = ", ".join(resolutions) or "—"
            langs: list[str] = []
            for p in packs:
                for lang in _AUDIO_LANG.get(p.audio, []):
                    if lang not in langs:
                        langs.append(lang)
            facts.languages = " & ".join(langs) or "—"
            ep_max = max((p.episode_to or p.file_count or 0) for p in packs)
            facts.episodes = str(ep_max) if ep_max else "—"
        if bot and bot.username:
            facts.bot_username = bot.username

        # Enrich with metadata when the provider is implemented (else graceful blanks).
        from nekofetch.services.enrichment_service import EnrichmentService

        data = await EnrichmentService(self._c).get_template_data(anime_doc_id)
        if data is not None:
            facts.genres = ", ".join(data.genres) or facts.genres
            facts.overview = (data.synopsis or facts.overview)
            if data.studio:
                facts.tag = data.studio.replace(" ", "")
            facts.poster_url = data.header_image or facts.poster_url
            if data.episode_count and facts.episodes == "—":
                facts.episodes = str(data.episode_count)

        # Fetch TMDB metadata for the post photo + overview (best-effort).
        # TMDB descriptions cover the entire franchise, not a single season.
        try:
            tmdb = getattr(self._c, "tmdb", None)
            if tmdb is not None:
                result = await tmdb.search(facts.title)
                if result is not None:
                    if not facts.backdrop_url and result.backdrop_url:
                        facts.backdrop_url = result.backdrop_url
                    # TMDB overview covers the whole franchise — better for main channel
                    if result.overview and result.overview != "—":
                        facts.overview = result.overview
        except Exception as exc:  # noqa: BLE001
            log.debug("mainchannel.tmdb.failed", title=facts.title, error=str(exc))

        return facts

    def _caption(self, f: PublicationFacts) -> str:
        return templates.render(
            self.cfg.caption_template,
            title=f.title, tag=f.tag, episodes=f.episodes, qualities=f.qualities,
            languages=f.languages, genres=f.genres, overview=f.overview,
        )

    async def _buttons(self, f: PublicationFacts) -> InlineKeyboardMarkup | None:
        from nekofetch.services.index_channel_service import IndexChannelService

        row: list[InlineKeyboardButton] = []
        index_url = await IndexChannelService(self._c).entry_link(f.title)
        if index_url:
            row.append(InlineKeyboardButton(self.cfg.index_button_text, url=index_url))
        if f.bot_username:
            dl = f"https://t.me/{f.bot_username}?start=anime_{f.anime_doc_id}"
            row.append(InlineKeyboardButton(self.cfg.download_button_text, url=dl))
        return InlineKeyboardMarkup([row]) if row else None

    async def publish(self, anime_doc_id: str) -> int | None:
        """Post (or edit) the main-channel entry for a title. Returns the message id."""
        if not self._active():
            return None
        facts = await self.gather_facts(anime_doc_id)
        caption = self._caption(facts)
        markup = await self._buttons(facts)
        client = self._c.admin_client

        async with session_scope(self._c.pg_sessionmaker) as session:
            post = (
                await session.execute(
                    select(ChannelPost).where(ChannelPost.anime_doc_id == anime_doc_id)
                )
            ).scalar_one_or_none()
            existing_id = post.main_message_id if post else None

        # Use the TMDB English backdrop as the post photo; fall back to poster.
        photo_url = facts.backdrop_url or facts.poster_url

        try:
            if existing_id:
                await client.edit_message_caption(
                    self.cfg.channel_id, existing_id, caption=caption, reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
                message_id = existing_id
            elif photo_url:
                sent = await client.send_photo(
                    self.cfg.channel_id, photo_url, caption=caption, reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
                message_id = sent.id
            else:
                sent = await client.send_message(
                    self.cfg.channel_id, caption, reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
                message_id = sent.id
        except Exception as exc:  # noqa: BLE001
            log.warning("mainchannel.publish.failed", anime=anime_doc_id, error=str(exc))
            return None

        await self._record(anime_doc_id, message_id, facts.title)
        log.info("mainchannel.published", anime=anime_doc_id, message_id=message_id)
        return message_id

    async def _record(self, anime_doc_id: str, message_id: int, title: str) -> None:
        from nekofetch.services.index_channel_service import IndexChannelService

        letter = IndexChannelService.letter_of(title)
        async with session_scope(self._c.pg_sessionmaker) as session:
            post = (
                await session.execute(
                    select(ChannelPost).where(ChannelPost.anime_doc_id == anime_doc_id)
                )
            ).scalar_one_or_none()
            if post is None:
                post = ChannelPost(anime_doc_id=anime_doc_id)
                session.add(post)
            post.main_channel_id = self.cfg.channel_id
            post.main_message_id = message_id
            post.index_letter = letter
