"""Wipe stale/active download state immediately.

Cancels every queued/running/orphaned DownloadJob and clears their live-progress
snapshots, so a ghost "active download" left over from a crash disappears. Run this
once, then restart the bot (startup recovery keeps it accurate from then on).

    python scripts/clear_downloads.py
"""

from __future__ import annotations

import asyncio

from nekofetch.core.container import Container


async def main() -> None:
    container = Container.create()
    await container.startup()
    try:
        from nekofetch.services.queue_service import QueueService

        n = await QueueService(container).cancel_all_active()
        print(f"cleared {n} active/queued/orphaned download job(s)")
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
