"""Unit tests for BotOrchestratorService — coordination logic.

Tests focus on the decision-making in ensure_bot_for_anime and recreate_bot:
feature-gate returns None, existing-bot short-circuit, full create flow, and
recreate cleanup. DB and external service calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nekofetch.services.bot_orchestrator import BotOrchestratorService


def _mock_session() -> MagicMock:
    """Create a properly chained async async context manager mock for a DB session."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    # DB operations must be awaitable (context manager calls rollback/commit on exit)
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    return session


def _prepare_session_scalars(session, *, first_value=None):
    """Configure session.execute().scalars().first() and .all() chains."""
    execute_return = MagicMock()
    scalars_chain = MagicMock()
    scalars_chain.first.return_value = first_value
    scalars_chain.all.return_value = [first_value] if first_value is not None else []
    execute_return.scalars = MagicMock(return_value=scalars_chain)
    session.execute.return_value = execute_return


@pytest.fixture
def service():
    """Create BotOrchestratorService with a fully-mocked container."""
    container = MagicMock()
    container.config.features.distribution_bots = True
    session = _mock_session()
    container.pg_sessionmaker = MagicMock(return_value=session)
    container.session = MagicMock(return_value=session)
    container.scheduler = MagicMock()
    return BotOrchestratorService(container)


# ── ensure_bot_for_anime ─────────────────────────────────────────────────────


class TestEnsureBotForAnime:
    async def test_returns_none_when_feature_disabled(self, service):
        service._c.config.features.distribution_bots = False
        result = await service.ensure_bot_for_anime("naruto")
        assert result is None

    async def test_returns_existing_bot(self, service):
        """When a bot already exists, return it without creating a new one."""
        from nekofetch.services.bot_management_service import BotInfo

        existing = BotInfo(id=42, name="Naruto Bot", username="naruto_bot", enabled=True)
        service._find_existing_bot = AsyncMock(return_value=existing)

        result = await service.ensure_bot_for_anime("naruto")
        assert result is not None
        assert result.id == 42
        assert result.name == "Naruto Bot"
        service._find_existing_bot.assert_awaited_once_with("naruto")

    @patch("nekofetch.services.bot_factory.BotFactory")
    @patch("nekofetch.services.log_channel_service.LogChannelService")
    async def test_creates_new_bot_when_none_exists(
        self, LogChannelMock, BotFactoryMock, service
    ):
        """Full flow: find_existing returns None -> create -> generate -> bind -> publish."""
        from nekofetch.services.bot_management_service import BotInfo

        service._find_existing_bot = AsyncMock(return_value=None)
        bot_info = BotInfo(id=99, name="New Bot", username="new_bot", enabled=True)
        BotFactoryMock.return_value.create_for_anime = AsyncMock(return_value=bot_info)
        service._generate_content = AsyncMock()
        service._bind_and_publish = AsyncMock()
        LogChannelMock.return_value.event = AsyncMock()

        result = await service.ensure_bot_for_anime("naruto")

        assert result is not None
        assert result.id == 99
        BotFactoryMock.return_value.create_for_anime.assert_awaited_once_with("naruto")
        service._generate_content.assert_awaited_once_with(99, "naruto")
        service._bind_and_publish.assert_awaited_once_with(99, "naruto")

    @patch("nekofetch.services.bot_factory.BotFactory")
    async def test_create_failure_returns_none(self, BotFactoryMock, service):
        """When bot factory raises, return None and don't proceed."""
        from nekofetch.core.exceptions import NekoFetchError

        service._find_existing_bot = AsyncMock(return_value=None)
        BotFactoryMock.return_value.create_for_anime = AsyncMock(
            side_effect=NekoFetchError("rate limited")
        )
        service._generate_content = AsyncMock()
        service._bind_and_publish = AsyncMock()

        result = await service.ensure_bot_for_anime("naruto")
        assert result is None
        service._generate_content.assert_not_called()
        service._bind_and_publish.assert_not_called()


# ── recreate_bot ─────────────────────────────────────────────────────────────


class TestRecreateBot:
    async def test_returns_none_when_feature_disabled(self, service):
        service._c.config.features.distribution_bots = False
        result = await service.recreate_bot("naruto")
        assert result is None

    async def test_removes_old_bot_and_content_then_creates_new(self, service):
        """recreate_bot deletes old content posts + bot, then delegates to ensure."""
        from nekofetch.services.bot_management_service import BotInfo

        session = service._c.pg_sessionmaker.return_value.__aenter__.return_value
        old_bot = MagicMock()
        old_bot.id = 42
        old_bot.anime_doc_id = "naruto"
        _prepare_session_scalars(session, first_value=old_bot)

        service.ensure_bot_for_anime = AsyncMock(
            return_value=BotInfo(id=43, name="New Bot", username="new_bot", enabled=True)
        )

        result = await service.recreate_bot("naruto")

        assert result is not None
        assert result.id == 43
        session.delete.assert_called_once_with(old_bot)
        session.flush.assert_awaited_once()
        service.ensure_bot_for_anime.assert_awaited_once_with("naruto")

    async def test_no_old_bot_just_creates_new(self, service):
        """When no old bot exists, recreate just delegates to ensure."""
        from nekofetch.services.bot_management_service import BotInfo

        session = service._c.pg_sessionmaker.return_value.__aenter__.return_value
        _prepare_session_scalars(session, first_value=None)

        service.ensure_bot_for_anime = AsyncMock(
            return_value=BotInfo(id=44, name="Another Bot", username="another_bot", enabled=True)
        )

        result = await service.recreate_bot("naruto")
        assert result is not None
        assert result.id == 44
        session.delete.assert_not_called()


# ── _find_existing_bot ───────────────────────────────────────────────────────


class TestFindExistingBot:
    async def test_returns_none_when_no_bot(self, service):
        session = service._c.pg_sessionmaker.return_value.__aenter__.return_value
        _prepare_session_scalars(session, first_value=None)

        result = await service._find_existing_bot("naruto")
        assert result is None

    async def test_returns_bot_info_when_found(self, service):
        from nekofetch.services.bot_management_service import BotInfo

        session = service._c.pg_sessionmaker.return_value.__aenter__.return_value
        existing = MagicMock()
        existing.id = 42
        existing.name = "Naruto Bot"
        existing.username = "naruto_bot"
        existing.enabled = True
        _prepare_session_scalars(session, first_value=existing)

        result = await service._find_existing_bot("naruto")
        assert isinstance(result, BotInfo)
        assert result.id == 42
        assert result.name == "Naruto Bot"
        assert result.username == "naruto_bot"
        assert result.enabled is True


# ── _generate_content ────────────────────────────────────────────────────────


class TestGenerateContent:
    async def test_generates_content(self, service):
        with patch("nekofetch.services.bot_content.BotContentService") as ContentMock:
            content_svc = ContentMock.return_value
            content_svc.generate_posts = AsyncMock()

            await service._generate_content(42, "naruto")

            content_svc.generate_posts.assert_awaited_once_with(42, "naruto")

    async def test_tolerates_failure(self, service):
        with patch("nekofetch.services.bot_content.BotContentService") as ContentMock:
            content_svc = ContentMock.return_value
            content_svc.generate_posts = AsyncMock(side_effect=RuntimeError("DB gone"))

            await service._generate_content(42, "naruto")

            content_svc.generate_posts.assert_awaited_once_with(42, "naruto")


# ── _bind_and_publish ────────────────────────────────────────────────────────


class TestBindAndPublish:
    async def test_binds_and_publishes(self, service):
        with (
            patch("nekofetch.services.bot_management_service.BotManagementService") as MgmtMock,
            patch("nekofetch.services.main_channel_service.MainChannelService") as ChannelMock,
        ):
            mgmt_svc = MgmtMock.return_value
            mgmt_svc.bind_title = AsyncMock()
            channel_svc = ChannelMock.return_value
            channel_svc.publish = AsyncMock()

            await service._bind_and_publish(42, "naruto")

            mgmt_svc.bind_title.assert_awaited_once_with(42, "naruto")
            channel_svc.publish.assert_awaited_once_with("naruto")

    async def test_tolerates_bind_failure(self, service):
        with (
            patch("nekofetch.services.bot_management_service.BotManagementService") as MgmtMock,
            patch("nekofetch.services.main_channel_service.MainChannelService") as ChannelMock,
        ):
            mgmt_svc = MgmtMock.return_value
            mgmt_svc.bind_title = AsyncMock(side_effect=RuntimeError("bind failed"))
            channel_svc = ChannelMock.return_value
            channel_svc.publish = AsyncMock()

            await service._bind_and_publish(42, "naruto")

            channel_svc.publish.assert_awaited_once_with("naruto")
