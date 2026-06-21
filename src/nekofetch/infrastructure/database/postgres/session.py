"""Postgres session utilities and schema creation helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nekofetch.infrastructure.database.postgres.base import Base


@asynccontextmanager
async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Transactional session scope: commit on success, rollback on error."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all(engine) -> None:
    """Create tables for first-run/dev. Production uses Alembic migrations."""
    # Import models so they register on Base.metadata.
    from nekofetch.infrastructure.database.postgres import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
