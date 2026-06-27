"""Multi-bot runtime manager.

Runs the admin bot plus every enabled distribution bot as separate Pyrogram clients
on one event loop. Distribution bots are loaded from the ``bots`` table (tokens are
decrypted on demand) and can be added/removed at runtime.
"""

from __future__ import annotations

import asyncio

from pyrogram.enums import ParseMode

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.ui.typography import bq

log = get_logger(__name__)

_RESOLVE_RETRY_SECONDS = 10
_RESOLVE_MAX_RETRIES = 12  # 2 minutes of retries


class BotManager:
    def __init__(self, container: Container) -> None:
        self._c = container
        self._admin = None
        self._distribution: dict[int, object] = {}
        self._worker = None
        self._worker_task: asyncio.Task | None = None
        self._scheduler = None

    async def start(self) -> None:
        from nekofetch.bots.admin.app import build_admin_bot

        # Expose the manager so services can bring bots online without a restart.
        self._c.bot_manager = self  # type: ignore[attr-defined]

        self._admin = build_admin_bot(self._c)
        await self._admin.start()
        # The admin client is the privileged actor for storage/log channels (it must be an
        # administrator of both). Expose it so services can use it.
        self._c.admin_client = self._admin  # type: ignore[attr-defined]
        await self._publish_commands(self._admin, kind="admin")
        await self._preflight_channels()
        log.info("bots.admin.started")

        if self._c.config.features.distribution_bots:
            await self._load_distribution_bots()

        await self._start_background_workers()

    async def _alert_admin(self, text: str) -> None:
        owner_id = self._c.config.security.owner_id
        if not owner_id or not self._admin:
            return
        try:
            await self._admin.send_message(owner_id, bq(text), parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("bot.alert_admin.failed", error=str(exc))

    async def _preflight_channels(self) -> None:
        """Resolve every configured Telegram channel at startup and retry in background."""
        cfg = self._c.config
        sections = [
            ("storage", cfg.storage_channel),
            ("log", cfg.log_channel),
            ("main", cfg.main_channel),
            ("index", cfg.index_channel),
        ]
        for name, section in sections:
            if not getattr(section, "enabled", False) or not getattr(section, "channel_id", 0):
                continue
            cid = section.channel_id
            if await self._try_resolve(name, cid):
                continue
            asyncio.create_task(self._retry_resolve(name, cid))

    async def _try_resolve(self, name: str, cid: int) -> bool:
        try:
            chat = await self._admin.get_chat(cid)
            log.info("bots.channel.ok", channel=name, id=cid, title=getattr(chat, "title", None))
            return True
        except Exception as exc:
            log.warning(
                "bots.channel.unreachable",
                channel=name,
                id=cid,
                error=str(exc),
                hint=(
                    "Make the admin bot an administrator of this channel, then post any "
                    "message in it (or remove + re-add the bot) while NekoFetch is running "
                    "so Telegram caches the peer. Confirm the id is the full -100... value. "
                    "Deleting the Pyrogram .session on each launch wipes this cache and "
                    "brings the error back."
                ),
            )
            return False

    async def _retry_resolve(self, name: str, cid: int) -> None:
        """Keep trying to resolve the channel peer in the background for ~2 minutes.

        When the bot is added to a private channel it receives a ``ChatMemberUpdated``
        update that contains only the ``chat_id`` — the ``access_hash`` needed for
        subsequent API calls is only cached after the bot *receives a message* from
        that channel (or the user mentions the bot there). This retry window gives the
        user time to trigger that event.
        """
        log.info("bots.channel.retrying", channel=name, id=cid)
        for attempt in range(1, _RESOLVE_MAX_RETRIES + 1):
            await asyncio.sleep(_RESOLVE_RETRY_SECONDS)
            try:
                chat = await self._admin.get_chat(cid)
                log.info("bots.channel.resolved", channel=name, id=cid, title=getattr(chat, "title", None))
                return
            except Exception:
                log.debug("bots.channel.retry_pending", channel=name, id=cid, attempt=attempt)
        log.warning("bots.channel.retry_exhausted", channel=name, id=cid)
        await self._alert_admin(
            f"❌ <b>channel retry exhausted!</b>\n\n"
            f"<b>channel:</b> {name}\n"
            f"<b>id:</b> <code>{cid}</code>\n\n"
            f"could not resolve channel peer after {_RESOLVE_MAX_RETRIES} attempts. "
            f"make sure the bot is an admin of the channel and that a message has been posted."
        )

    async def _publish_commands(self, client, *, kind: str) -> None:
        """Publish the Telegram command menu so users can discover commands.

        Best-effort: a transient API hiccup here must never stop a bot from running.
        """
        try:
            if kind == "admin":
                from nekofetch.bots.admin.handlers.commands import publish_admin_commands

                await publish_admin_commands(client)
            else:
                from nekofetch.bots.distribution.app import publish_distribution_commands

                await publish_distribution_commands(client)
        except Exception as exc:  # noqa: BLE001
            log.warning("bots.commands.publish_failed", kind=kind, error=str(exc))

    async def _start_background_workers(self) -> None:
        from nekofetch.infrastructure.scheduler import Scheduler
        from nekofetch.services.distribution_service import DistributionService
        from nekofetch.services.download_service import DownloadWorker

        # Download worker loop.
        if self._c.config.features.download_queue:
            self._worker = DownloadWorker(self._c)
            self._worker_task = asyncio.create_task(self._worker.run_forever())
            log.info("worker.download.started")

        # Scheduled maintenance jobs.
        self._scheduler = Scheduler()
        self._c.scheduler = self._scheduler  # type: ignore[attr-defined]
        dist = DistributionService(self._c)
        if self._c.config.features.temporary_links:
            self._scheduler.every(60, dist.sweep_expired, id="link-expiry-sweep")

        # Log channel: create/pin the dashboard + catalog, then refresh on an interval.
        if self._c.config.log_channel.enabled:
            from nekofetch.services.log_channel_service import LogChannelService

            log_svc = LogChannelService(self._c)
            await log_svc.ensure_pins()
            self._scheduler.every(
                self._c.config.log_channel.refresh_seconds, log_svc.refresh, id="log-pins-refresh"
            )

        self._scheduler.start()

    async def _load_distribution_bots(self) -> None:
        from sqlalchemy import select

        from nekofetch.bots.distribution.app import build_distribution_bot
        from nekofetch.infrastructure.database.postgres.models import DistributionBot

        async with self._c.session() as session:
            rows = (
                await session.execute(
                    select(DistributionBot).where(DistributionBot.enabled.is_(True))
                )
            ).scalars().all()

        for row in rows:
            try:
                token = self._c.cipher.decrypt(row.encrypted_token)
                client = build_distribution_bot(self._c, row, token)
                await client.start()
                await self._publish_commands(client, kind="distribution")
                self._distribution[row.id] = client
                log.info("bots.distribution.started", bot=row.name, id=row.id)
            except Exception as exc:  # one bad token must not stop the fleet
                log.error("bots.distribution.failed", id=row.id, error=str(exc))
                await self._alert_admin(
                    f"⚠️ <b>distribution bot failed to start</b>\n\n"
                    f"<b>id:</b> <code>{row.id}</code>\n"
                    f"<b>name:</b> {row.name}\n"
                    f"<b>error:</b> {str(exc)[:200]}"
                )

    def get_client(self, bot_id: int):
        """Return the running Pyrogram client for a distribution bot, if any."""
        return self._distribution.get(bot_id)

    async def add_distribution_bot(self, bot_id: int) -> None:
        """Start a single newly-registered distribution bot at runtime."""
        from nekofetch.bots.distribution.app import build_distribution_bot
        from nekofetch.infrastructure.database.postgres.models import DistributionBot

        if bot_id in self._distribution:
            return
        async with self._c.session() as session:
            row = await session.get(DistributionBot, bot_id)
            if row is None or not row.enabled:
                return
            token = self._c.cipher.decrypt(row.encrypted_token)
            client = build_distribution_bot(self._c, row, token)
        await client.start()
        await self._publish_commands(client, kind="distribution")
        self._distribution[bot_id] = client
        log.info("bots.distribution.added", id=bot_id)

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown()
        if self._worker is not None:
            await self._worker.stop()
        if self._worker_task is not None:
            self._worker_task.cancel()
        for client in self._distribution.values():
            try:
                await client.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._admin is not None:
            await self._admin.stop()
        log.info("bots.stopped")
