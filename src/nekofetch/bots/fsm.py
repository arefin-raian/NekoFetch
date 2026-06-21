"""Lightweight Redis-backed finite-state machine for multi-step conversations.

Pyrogram has no built-in FSM; this stores a per-(bot, user) state string plus a small
JSON data bag with a TTL, so flows like "request anime" survive across messages without
in-memory state (works across restarts and multiple workers).
"""

from __future__ import annotations

import json

from redis.asyncio import Redis

from nekofetch.core.constants import REDIS_FSM


class FSM:
    def __init__(self, redis: Redis, bot: str, ttl: int = 900) -> None:
        self._redis = redis
        self._bot = bot
        self._ttl = ttl

    def _key(self, user_id: int) -> str:
        return REDIS_FSM.format(bot=self._bot, user_id=user_id)

    async def set(self, user_id: int, state: str, **data) -> None:
        await self._redis.set(
            self._key(user_id), json.dumps({"state": state, "data": data}), ex=self._ttl
        )

    async def get(self, user_id: int) -> tuple[str | None, dict]:
        raw = await self._redis.get(self._key(user_id))
        if not raw:
            return None, {}
        parsed = json.loads(raw)
        return parsed.get("state"), parsed.get("data", {})

    async def update(self, user_id: int, **data) -> None:
        state, existing = await self.get(user_id)
        existing.update(data)
        await self._redis.set(
            self._key(user_id), json.dumps({"state": state, "data": existing}), ex=self._ttl
        )

    async def clear(self, user_id: int) -> None:
        await self._redis.delete(self._key(user_id))
