from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.user_repo import UserRepository
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq

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
            bq("<b>broadcast</b>\n\n"
               "send the message to broadcast (text or media). "
               "it will be copied to all users."),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=5)
    async def _broadcast(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_BROADCAST or not _allowed(message):
            return
        await fsm.clear(message.from_user.id)

        async with session_scope(container.pg_sessionmaker) as session:
            ids = await UserRepository(session).all_telegram_ids()

        status = await message.reply(
            "<b>broadcasting!</b>", parse_mode=ParseMode.HTML
        )
        await loading_animation(status, "broadcasting")
        sent = failed = 0
        for uid in ids:
            try:
                await message.copy(uid)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "broadcast", sent=sent, failed=failed, by=message.from_user.id
        )
        await status.edit_text(
            f"{bq('<b>broadcast complete</b>')}\n\n"
            f"{bq(f'delivered: <b>{sent}</b>\nfailed: <b>{failed}</b>')}",
            parse_mode=ParseMode.HTML,
        )
