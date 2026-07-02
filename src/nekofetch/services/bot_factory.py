"""Automatic distribution-bot creation via @BotFather (using the userbot session).

A bot's token AND its profile photo can only be obtained/set through @BotFather, so
this drives a real BotFather conversation with the user account from the userbot pool:

    /newbot → <name> → <username> → token
    /setuserpic → @username → <photo>
    /setdescription / /setabouttext → @username → <text>

The created token is then handed to :class:`BotManagementService` which validates,
encrypts, stores, and brings the bot online — so a factory-made bot is identical to
a manually-registered one from there on.

⚠️ The BotFather conversation is wording-sensitive and rate-limited; this is written
defensively (token regex, username-taken retries, bounded waits) but should be
exercised live once — it cannot be unit-tested against the real BotFather.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType
from nekofetch.services.bot_naming import format_bot_name, format_bot_username

log = get_logger(__name__)

_BOTFATHER = "BotFather"
_TOKEN_RE = re.compile(r"(\d{6,}:[A-Za-z0-9_-]{30,})")
# subbed → Japanese audio, dubbed → English audio (dual = both).
_AUDIO_LANGS = {
    AudioType.SUBBED.value: "japanese",
    AudioType.DUBBED.value: "english",
    AudioType.DUAL_AUDIO.value: "english",
}


class BotFactory:
    def __init__(self, container: Container) -> None:
        self._c = container
        self._pool = None

    def _userbot(self):
        if self._pool is None:
            from nekofetch.sources.telegram.userbot import UserbotPool

            self._pool = UserbotPool.from_env(
                self._c.env.telegram_api_id, self._c.env.telegram_api_hash,
                str(self._c.env.session_path),
            )
        return self._pool

    # ── public entry ─────────────────────────────────────────────────────────────
    async def create_for_anime(self, anime_doc_id: str) -> "BotInfo":
        """Create + configure a distribution bot for a published title, then register
        it. Returns the BotInfo from BotManagementService."""
        if not self._c.config.features.distribution_bots:
            raise NekoFetchError("distribution_bots feature is disabled")

        meta = await self._gather(anime_doc_id)
        name = format_bot_name(meta["english"], meta["romaji"],
                               audios=meta["audios"], languages=meta["languages"])
        username = format_bot_username(meta["english"] or meta["romaji"] or "anime", anime_doc_id)
        from nekofetch.localization.messages import M, t
        description = t(M.BOT_DESC_PLACEHOLDER, title=meta["english"] or meta["romaji"] or "")
        avatar = await self._fetch_avatar(meta["english"] or meta["romaji"] or "")

        log.info("botfactory.create", anime=anime_doc_id, name=name, username=username)
        token = await self._userbot().execute(
            lambda c: self._botfather_create(c, name, username, avatar, description)
        )
        if avatar:
            try:
                avatar.unlink()
            except OSError:
                pass

        from nekofetch.services.bot_management_service import BotManagementService, BotInfo

        return await BotManagementService(self._c).register(
            token, name=name, anime_doc_id=anime_doc_id,
        )

    # ── metadata ─────────────────────────────────────────────────────────────────
    async def _gather(self, anime_doc_id: str) -> dict:
        from sqlalchemy import select

        from nekofetch.infrastructure.database.postgres.models import MediaFile, Request
        from nekofetch.infrastructure.database.postgres.session import session_scope

        english = romaji = ""
        audios: set = set()
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = (await session.execute(
                select(Request).where(Request.anime_doc_id == anime_doc_id)
                .order_by(Request.id.desc())
            )).scalars().first()
            if req is not None:
                fr = req.franchise_data or {}
                english = fr.get("english") or req.anime_title or ""
                romaji = fr.get("romaji") or ""
            files = (await session.execute(
                select(MediaFile).where(MediaFile.anime_doc_id == anime_doc_id)
            )).scalars().all()
            audios = {f.audio.value for f in files if f.audio is not None}
        languages = {_AUDIO_LANGS.get(a) for a in audios}
        if AudioType.DUAL_AUDIO.value in audios:
            languages.update({"english", "japanese"})
        if AudioType.MULTI.value in audios:
            languages.update({"english", "japanese", "hindi"})
        languages.discard(None)
        return {"english": english, "romaji": romaji, "audios": audios, "languages": languages}

    async def _fetch_avatar(self, title: str) -> Path | None:
        """Download a DIFFERENT TMDB poster (rank 1) for the bot's profile photo."""
        if not title:
            return None
        try:
            url = await self._c.tmdb.poster_for(title, size="w500", rank=1)
        except Exception:  # noqa: BLE001
            url = None
        if not url:
            return None
        dest = Path(self._c.env.storage_path) / "work" / "_avatars" / f"{abs(hash(title))}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cli:
                r = await cli.get(url)
                r.raise_for_status()
                dest.write_bytes(r.content)
            return dest
        except Exception as exc:  # noqa: BLE001
            log.warning("botfactory.avatar.failed", error=str(exc))
            return None

    # ── BotFather conversation ───────────────────────────────────────────────────
    async def _botfather_create(self, client, name: str, username: str,
                                avatar: Path | None, description: str) -> str:
        await self._say(client, "/newbot")
        await self._say(client, name)
        reply = await self._say(client, username)

        attempts = 0
        while reply and re.search(r"taken|invalid|sorry|too short|letters", reply, re.I):
            attempts += 1
            if attempts > 8:
                raise NekoFetchError(f"BotFather rejected all usernames: {reply[:120]}")
            username = self._bump(username, attempts)
            reply = await self._say(client, username)

        m = _TOKEN_RE.search(reply or "")
        if not m:
            raise NekoFetchError(f"BotFather did not return a token: {(reply or '')[:160]}")
        token = m.group(1)

        # Profile photo (must go through BotFather).
        if avatar and avatar.exists():
            try:
                await self._say(client, "/setuserpic")
                await self._say(client, f"@{username}")
                await client.send_photo(_BOTFATHER, str(avatar))
                await asyncio.sleep(2.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("botfactory.setuserpic.failed", error=str(exc))

        # Placeholder description + about (the owner edits these later via en.json).
        if description:
            for cmd, text in (("/setdescription", description),
                              ("/setabouttext", description[:120])):
                try:
                    await self._say(client, cmd)
                    await self._say(client, f"@{username}")
                    await self._say(client, text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("botfactory.setinfo.failed", cmd=cmd, error=str(exc))

        log.info("botfactory.created", username=username)
        return token

    @staticmethod
    def _bump(username: str, n: int) -> str:
        stem = username[:-3] if username.endswith("bot") else username
        stem = stem.rstrip("_0123456789")[: 32 - len(f"{n}bot")]
        return f"{stem}{n}bot"

    async def _say(self, client, text: str, *, wait: float = 2.5) -> str:
        """Send a line to BotFather and return its next reply text (best-effort)."""
        await client.send_message(_BOTFATHER, text)
        await asyncio.sleep(wait)
        async for msg in client.get_chat_history(_BOTFATHER, limit=1):
            return msg.text or msg.caption or ""
        return ""
