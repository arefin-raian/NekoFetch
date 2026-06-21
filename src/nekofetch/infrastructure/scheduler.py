"""APScheduler wrapper for time-based jobs.

Owns recurring and one-shot jobs: access-link expiry sweeps, auto-deletion of delivered
messages, queue position recalculation, and analytics rollups.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from nekofetch.core.logging import get_logger

log = get_logger(__name__)


class Scheduler:
    def __init__(self) -> None:
        self._sched = AsyncIOScheduler()

    def start(self) -> None:
        self._sched.start()
        log.info("scheduler.start")

    def shutdown(self) -> None:
        self._sched.shutdown(wait=False)

    def every(self, seconds: int, func: Callable[..., Awaitable], *, id: str) -> None:
        self._sched.add_job(func, "interval", seconds=seconds, id=id, replace_existing=True)

    def at(self, when: datetime, func: Callable[..., Awaitable], *, id: str, args=None) -> None:
        self._sched.add_job(func, "date", run_date=when, id=id, args=args or [], replace_existing=True)

    def cancel(self, id: str) -> None:
        job = self._sched.get_job(id)
        if job:
            job.remove()
