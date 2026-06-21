"""Redis-backed live progress store.

Download/processing progress is written here frequently and read by the UI layer to
render live dashboards via message edits, avoiding hot writes to Postgres.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from nekofetch.core.constants import REDIS_PROGRESS


@dataclass(slots=True)
class ProgressSnapshot:
    job_id: int
    status: str
    progress: float = 0.0          # 0..100
    speed_bps: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    current_episode: int | None = None
    eta_seconds: int | None = None
    label: str | None = None


class ProgressStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def set(self, snap: ProgressSnapshot, ttl: int = 3600) -> None:
        key = REDIS_PROGRESS.format(job_id=snap.job_id)
        await self._redis.set(key, json.dumps(asdict(snap)), ex=ttl)

    async def get(self, job_id: int) -> ProgressSnapshot | None:
        raw = await self._redis.get(REDIS_PROGRESS.format(job_id=job_id))
        if not raw:
            return None
        return ProgressSnapshot(**json.loads(raw))
