"""Bot orchestration — coordinates the storage→bot→content→main channel flow.

After content is uploaded to the storage channel, this service:
  1. Creates a distribution bot via BotFactory (if one doesn't exist)
  2. Generates content posts (watch guide, season cards, etc.)
  3. Binds the bot to the title and applies branding
  4. Posts to the main channel with a Download button pointing to the bot

Also handles bot re-creation when a bot is banned.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.infrastructure.database.postgres.models import BotContentPost, DistributionBot
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.services.bot_management_service import BotInfo

log = get_logger(__name__)


class BotOrchestratorService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def ensure_bot_for_anime(self, anime_doc_id: str) -> BotInfo | None:
        """Create a distribution bot for an anime if one doesn't exist.

        Returns the BotInfo if a bot was created or already exists.
        Returns None if distribution_bots feature is disabled.
        """
        if not self._c.config.features.distribution_bots:
            return None

        # Check if a bot already exists for this title.
        existing = await self._find_existing_bot(anime_doc_id)
        if existing is not None:
            log.info("bot.orchestrator.exists", anime=anime_doc_id, bot=existing.id)
            return existing

        # Create brand new bot via BotFactory.
        from nekofetch.core.exceptions import NekoFetchError
        from nekofetch.services.bot_factory import BotFactory

        log.info("bot.orchestrator.creating", anime=anime_doc_id)

        try:
            bot_info = await BotFactory(self._c).create_for_anime(anime_doc_id)
        except NekoFetchError as exc:
            log.error("bot.orchestrator.create.failed", anime=anime_doc_id, error=str(exc))
            return None

        # Generate content posts for this bot.
        await self._generate_content(bot_info.id, anime_doc_id)

        # Bind and refresh main channel.
        await self._bind_and_publish(bot_info.id, anime_doc_id)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "bot", "created", id=bot_info.id, name=bot_info.name,
            anime=anime_doc_id,
        )

        log.info("bot.orchestrator.created", anime=anime_doc_id, bot=bot_info.id)
        return bot_info

    async def recreate_bot(self, anime_doc_id: str) -> BotInfo | None:
        """Recreate a bot for an anime (after a ban or failure).

        Removes the old bot record, creates a new one, regenerates content,
        and refreshes the main channel.
        """
        if not self._c.config.features.distribution_bots:
            return None

        # Remove the old bot record and its content posts.
        async with session_scope(self._c.pg_sessionmaker) as session:
            old = (
                await session.execute(
                    select(DistributionBot)
                    .where(DistributionBot.anime_doc_id == anime_doc_id)
                    .order_by(DistributionBot.id.desc())
                )
            ).scalars().first()
            if old is not None:
                await session.execute(
                    delete(BotContentPost).where(BotContentPost.bot_id == old.id)
                )
                await session.delete(old)
                await session.flush()

        # Create new bot.
        return await self.ensure_bot_for_anime(anime_doc_id)

    async def _find_existing_bot(self, anime_doc_id: str) -> BotInfo | None:
        """Find an existing enabled bot bound to this anime."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            bot = (
                await session.execute(
                    select(DistributionBot).where(
                        DistributionBot.anime_doc_id == anime_doc_id,
                        DistributionBot.enabled.is_(True),
                    )
                )
            ).scalars().first()
            if bot is None:
                return None
            return BotInfo(id=bot.id, name=bot.name, username=bot.username, enabled=bot.enabled)

    async def _generate_content(self, bot_id: int, anime_doc_id: str) -> None:
        """Generate and store content posts for a bot."""
        from nekofetch.services.bot_content import BotContentService

        try:
            await BotContentService(self._c).generate_posts(bot_id, anime_doc_id)
        except Exception as exc:
            log.warning("bot.orchestrator.content.failed", bot_id=bot_id, error=str(exc))

    async def _bind_and_publish(self, bot_id: int, anime_doc_id: str) -> None:
        """Bind the bot to the title, apply branding, and refresh main channel."""
        from nekofetch.services.bot_management_service import BotManagementService
        from nekofetch.services.main_channel_service import MainChannelService

        try:
            await BotManagementService(self._c).bind_title(bot_id, anime_doc_id)
        except Exception as exc:
            log.warning("bot.orchestrator.bind.failed", bot_id=bot_id, error=str(exc))

        try:
            await MainChannelService(self._c).publish(anime_doc_id)
        except Exception as exc:
            log.warning("bot.orchestrator.mainchannel.failed", anime=anime_doc_id, error=str(exc))
