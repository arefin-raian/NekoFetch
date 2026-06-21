"""Multi-bot runtime manager.

Runs the admin bot plus every enabled distribution bot as separate Pyrogram clients
on one event loop. Distribution bots are loaded from the ``bots`` table (tokens are
decrypted on demand) and can be added/removed at runtime.
"""

from __future__ import annotations

import asyncio

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)


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
        log.info("bots.admin.started")

        if self._c.config.features.distribution_bots:
            await self._load_distribution_bots()

        await self._start_background_workers()

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
                self._distribution[row.id] = client
                log.info("bots.distribution.started", bot=row.name, id=row.id)
            except Exception as exc:  # one bad token must not stop the fleet
                log.error("bots.distribution.failed", id=row.id, error=str(exc))

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
