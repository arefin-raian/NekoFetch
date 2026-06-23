"""Shared bot middleware: user resolution, rate limiting, anti-spam.

Pyrogram doesn't have ASGI-style middleware, so we register a high-priority handler
in an early group that resolves the user and enforces limits before feature handlers
(in later groups) run. The resolved user is stashed on the update for handlers to use.
"""

from __future__ import annotations

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.core.constants import REDIS_RATELIMIT
from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.typography import bq

log = get_logger(__name__)


def install_auth_middleware(client: Client, container: Container) -> None:
    auth = AuthService(container)
    rate_limit = container.config.security.rate_limit_per_minute

    async def _resolve(from_user) -> object | None:
        if from_user is None:
            return None
        return await auth.resolve_user(
            from_user.id, username=from_user.username, first_name=from_user.first_name
        )

    async def _rate_limited(user_id: int) -> bool:
        if container.redis is None:
            return False
        key = REDIS_RATELIMIT.format(user_id=user_id)
        count = await container.redis.incr(key)
        if count == 1:
            await container.redis.expire(key, 60)
        return count > rate_limit

    # Group -1 runs before feature handlers (group 0+).
    @client.on_message(group=-1)
    async def _msg_mw(_: Client, message: Message) -> None:
        if message.from_user and await _rate_limited(message.from_user.id):
            await message.reply(bq(container.localizer.get("rate_limited")), parse_mode=ParseMode.HTML)
            await message.stop_propagation()
        message.nf_user = await _resolve(message.from_user)  # type: ignore[attr-defined]

    @client.on_callback_query(group=-1)
    async def _cb_mw(_: Client, query: CallbackQuery) -> None:
        if query.from_user and await _rate_limited(query.from_user.id):
            await query.answer(bq(container.localizer.get("rate_limited")), show_alert=True)
            await query.stop_propagation()
        query.nf_user = await _resolve(query.from_user)  # type: ignore[attr-defined]
