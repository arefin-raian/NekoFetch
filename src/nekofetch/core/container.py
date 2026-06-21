"""Dependency-injection container.

A single composition root that builds and holds long-lived singletons (DB clients,
cipher, config) and lazily constructs repositories and services. Bots and handlers
receive the container rather than importing infrastructure directly, keeping the
dependency arrows pointing inward.

Infrastructure imports are deferred to ``startup()`` so importing this module is cheap
and free of side effects (useful for tests and tooling).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nekofetch.core.config import AppConfig, EnvSettings, get_app_config, get_env
from nekofetch.core.logging import get_logger
from nekofetch.core.security import TokenCipher
from nekofetch.localization.i18n import Localizer
from nekofetch.sources.registry import SourceRegistry, build_default_registry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from motor.motor_asyncio import AsyncIOMotorDatabase
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from nekofetch.infrastructure.database.mongo.collections import Collections
    from nekofetch.infrastructure.database.redis.progress import ProgressStore

log = get_logger(__name__)


class Container:
    """Composition root. Build with :meth:`create`, then ``await startup()``."""

    def __init__(self, env: EnvSettings, config: AppConfig) -> None:
        self.env = env
        self.config = config
        self.cipher = TokenCipher(env.secret_key)

        # Stateless singletons available immediately.
        self.localizer = Localizer(
            config.localization.directory, default=config.localization.default_language
        )
        self.sources: SourceRegistry = build_default_registry()

        # Populated by startup()
        self.pg_engine: AsyncEngine | None = None
        self.pg_sessionmaker: async_sessionmaker | None = None
        self.mongo: AsyncIOMotorDatabase | None = None
        self.collections: Collections | None = None
        self.redis: Redis | None = None
        self.progress: ProgressStore | None = None
        self._services: dict[str, Any] = {}

    @classmethod
    def create(cls) -> "Container":
        return cls(env=get_env(), config=get_app_config())

    async def startup(self) -> None:
        """Open all infrastructure connections. Idempotent per process."""
        from motor.motor_asyncio import AsyncIOMotorClient
        from redis.asyncio import Redis
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from nekofetch.infrastructure.database.mongo.collections import Collections
        from nekofetch.infrastructure.database.postgres.session import create_all
        from nekofetch.infrastructure.database.redis.progress import ProgressStore

        log.info("container.startup", db="postgres+mongo+redis")

        self.pg_engine = create_async_engine(self.env.postgres_dsn, pool_pre_ping=True)
        self.pg_sessionmaker = async_sessionmaker(self.pg_engine, expire_on_commit=False)
        await create_all(self.pg_engine)  # dev convenience; Alembic owns prod schema

        self.mongo = AsyncIOMotorClient(self.env.mongo_uri)[self.env.mongo_db]
        self.collections = Collections(self.mongo)
        await self.collections.ensure_indexes()

        self.redis = Redis.from_url(self.env.redis_url, decode_responses=True)
        self.progress = ProgressStore(self.redis)

        # Apply persisted runtime overrides (admin settings panel) over config.yaml.
        from nekofetch.services.settings_service import SettingsService

        await SettingsService(self).apply_overrides()

        # Activate only authorized sources listed in config.
        self.sources.activate(self.config.sources.enabled)

        self.env.storage_path.mkdir(parents=True, exist_ok=True)
        self.env.session_path.mkdir(parents=True, exist_ok=True)

    def session(self) -> "AsyncSession":
        """Open a new Postgres session (caller manages the transaction scope)."""
        assert self.pg_sessionmaker is not None, "Container not started"
        return self.pg_sessionmaker()

    async def shutdown(self) -> None:
        log.info("container.shutdown")
        if self.redis is not None:
            await self.redis.aclose()
        if self.pg_engine is not None:
            await self.pg_engine.dispose()
