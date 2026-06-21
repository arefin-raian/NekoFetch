"""Admin tools: broadcast to all users.

Sends a copy of the admin's next message to every (non-banned) user, sequentially with a
small delay to stay within Telegram limits. Reports delivered/failed counts.
"""

from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.user_repo import UserRepository
from nekofetch.services.auth_service import AuthService

STATE_BROADCAST = "admin:await_broadcast"


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(obj) -> bool:
        user = getattr(obj, "nf_user", None)
        return bool(user and auth.has_permission(user, Permission.MANAGE_STAFF))

    @client.on_callback_query(filters.regex(r"^admin\|broadcast"))
    async def _start(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_BROADCAST)
        await q.answer()
        await q.message.edit_text(
            "**Broadcast**\n\nSend the message to broadcast (text or media). "
            "It will be copied to all users."
        )

    # Group 5 so it coexists with the other stateful text handlers.
    @client.on_message(filters.text & ~filters.command(["start"]), group=5)
    async def _broadcast(_: Client, message: Message) -> None:
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_BROADCAST or not _allowed(message):
            return
        await fsm.clear(message.from_user.id)

        async with session_scope(container.pg_sessionmaker) as session:
            ids = await UserRepository(session).all_telegram_ids()

        status = await message.reply(f"Broadcasting to {len(ids)} users…")
        sent = failed = 0
        for uid in ids:
            try:
                await message.copy(uid)
                sent += 1
            except Exception:  # noqa: BLE001 - blocked/deactivated users
                failed += 1
            await asyncio.sleep(0.05)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "broadcast", sent=sent, failed=failed, by=message.from_user.id
        )
        await status.edit_text(f"**Broadcast complete**\n\nDelivered: {sent}\nFailed: {failed}")
