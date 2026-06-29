"""Wipe ALL application state except users.

Truncates every Postgres table except ``users`` (and ``alembic_version``), empties
every Mongo collection, and deletes every ``nf:*`` Redis key. Use it to reset to a
clean slate while keeping registered users.

    python scripts/clear_database.py            # asks for confirmation
    python scripts/clear_database.py --yes      # no prompt

The log channel rebuilds itself on the next startup (it's self-healing), so clearing
its Redis layout state is safe.
"""

from __future__ import annotations

import asyncio
import sys

from nekofetch.core.container import Container

_KEEP_TABLES = {"users", "alembic_version"}


async def main(assume_yes: bool) -> None:
    if not assume_yes:
        ans = input("This wipes ALL data except users (Postgres + Mongo + Redis). Type 'yes': ")
        if ans.strip().lower() != "yes":
            print("aborted")
            return

    container = Container.create()
    await container.startup()
    try:
        # ── Postgres: truncate every table except users ──
        from sqlalchemy import text

        from nekofetch.infrastructure.database.postgres.models import Base

        tables = [t.name for t in Base.metadata.sorted_tables if t.name not in _KEEP_TABLES]
        if tables and container.pg_engine is not None:
            async with container.pg_engine.begin() as conn:
                await conn.execute(
                    text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
                )
            print(f"postgres: truncated {len(tables)} table(s), kept {sorted(_KEEP_TABLES)}")

        # ── Mongo: empty every collection ──
        if container.mongo is not None:
            names = await container.mongo.list_collection_names()
            for name in names:
                await container.mongo[name].delete_many({})
            print(f"mongo: cleared {len(names)} collection(s)")

        # ── Redis: drop every namespaced key ──
        if container.redis is not None:
            removed = 0
            async for key in container.redis.scan_iter("nf:*"):
                await container.redis.delete(key)
                removed += 1
            print(f"redis: deleted {removed} nf:* key(s)")

        print("done — database cleared (users preserved)")
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main("--yes" in sys.argv[1:]))
