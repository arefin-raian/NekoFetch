"""Distribution-bot management.

Validates a BotFather token, stores it encrypted, and registers a DistributionBot.
The live runtime add/remove is delegated to the BotManager (referenced via the
container) so a newly-registered bot starts serving without a restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyrogram import Client
from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import BotKind
from nekofetch.infrastructure.database.postgres.models import DistributionBot
from nekofetch.infrastructure.database.postgres.session import session_scope

log = get_logger(__name__)


@dataclass(slots=True)
class BotInfo:
    id: int
    name: str
    username: str | None
    enabled: bool


class BotManagementService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def _validate_token(self, token: str) -> tuple[int, str | None, str]:
        """Confirm the token works; return (bot_user_id, username, display_name)."""
        probe = Client(
            name="nf-probe",
            api_id=self._c.env.telegram_api_id,
            api_hash=self._c.env.telegram_api_hash,
            bot_token=token,
            in_memory=True,
            workdir=str(self._c.env.session_path),
        )
        try:
            await probe.start()
            me = await probe.get_me()
            return me.id, me.username, (me.first_name or me.username or "Distribution Bot")
        except Exception as exc:  # noqa: BLE001
            raise NekoFetchError(f"Invalid bot token: {exc}") from exc
        finally:
            try:
                await probe.stop()
            except Exception:  # noqa: BLE001
                pass

    async def register(
        self, token: str, *, name: str | None = None, anime_doc_id: str | None = None
    ) -> BotInfo:
        if not self._c.config.features.distribution_bots:
            raise NekoFetchError("distribution_bots feature is disabled")

        bot_user_id, username, display = await self._validate_token(token)
        async with session_scope(self._c.pg_sessionmaker) as session:
            existing = (
                await session.execute(
                    select(DistributionBot).where(DistributionBot.bot_user_id == bot_user_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise NekoFetchError("This bot is already registered.")

            record = DistributionBot(
                kind=BotKind.DISTRIBUTION,
                name=name or display,
                username=username,
                bot_user_id=bot_user_id,
                encrypted_token=self._c.cipher.encrypt(token),
                anime_doc_id=anime_doc_id,
                enabled=True,
            )
            session.add(record)
            await session.flush()
            info = BotInfo(record.id, record.name, record.username, record.enabled)

        # Bring it online immediately if the manager is attached.
        manager = getattr(self._c, "bot_manager", None)
        if manager is not None:
            await manager.add_distribution_bot(info.id)
        log.info("bot.registered", id=info.id, username=info.username)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "bot", "registered", id=info.id, name=info.name, username=info.username
        )
        return info

    async def list_bots(self) -> list[BotInfo]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (await session.execute(select(DistributionBot))).scalars().all()
            return [BotInfo(r.id, r.name, r.username, r.enabled) for r in rows]

    async def set_enabled(self, bot_id: int, enabled: bool) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            rec = await session.get(DistributionBot, bot_id)
            if rec:
                rec.enabled = enabled

    async def bind_title(self, bot_id: int, anime_doc_id: str | None) -> None:
        """Bind a distribution bot to a single title (or clear with None).

        A bound bot opens directly on that title's page instead of the catalog. Binding also
        auto-brands the bot and refreshes its main-channel post so Download deep-links work.
        """
        async with session_scope(self._c.pg_sessionmaker) as session:
            rec = await session.get(DistributionBot, bot_id)
            if rec:
                rec.anime_doc_id = anime_doc_id or None
        log.info("bot.bound", id=bot_id, anime=anime_doc_id)

        if not anime_doc_id:
            return
        # Auto-brand the live bot (best-effort) and refresh the main-channel post.
        manager = getattr(self._c, "bot_manager", None)
        client = manager.get_client(bot_id) if manager else None
        if client is not None:
            from nekofetch.services.bot_branding import apply_bot_branding

            await apply_bot_branding(self._c, client, anime_doc_id)
        from nekofetch.services.main_channel_service import MainChannelService

        await MainChannelService(self._c).publish(anime_doc_id)

    async def pending_bot_animes(self) -> list[tuple[str, str]]:
        """Titles that have stored content but no enabled bot bound yet."""
        from sqlalchemy import distinct

        from nekofetch.infrastructure.database.postgres.models import StoragePack

        async with session_scope(self._c.pg_sessionmaker) as session:
            packs = (
                await session.execute(
                    select(distinct(StoragePack.anime_doc_id), StoragePack.anime_title)
                )
            ).all()
            bound = set(
                (
                    await session.execute(
                        select(DistributionBot.anime_doc_id).where(
                            DistributionBot.anime_doc_id.is_not(None),
                            DistributionBot.enabled.is_(True),
                        )
                    )
                ).scalars().all()
            )
        seen: dict[str, str] = {}
        for doc_id, title in packs:
            if doc_id not in bound:
                seen.setdefault(doc_id, title)
        return list(seen.items())
