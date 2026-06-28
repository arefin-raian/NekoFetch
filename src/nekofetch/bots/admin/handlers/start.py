from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.localization.messages import M, t
from nekofetch.ui.progress import staged_loading
from nekofetch.ui.screens import send_screen
from nekofetch.ui.screens import welcome as welcome_screen


def register(client: Client, container: Container) -> None:
    ui_cfg = container.config.ui

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        user = getattr(message, "nf_user", None)
        role = Role(user.role) if user else Role.USER

        start_sticker = await client.send_sticker(
            chat_id=message.chat.id, sticker=ui_cfg.start_sticker_id
        )

        msg = await message.reply(t(M.CONNECTING), parse_mode=ParseMode.HTML)
        await staged_loading(
            msg,
            [t(M.LOADING_STAGE_CONNECTING), t(M.LOADING_STAGE_LOADING),
             t(M.LOADING_STAGE_VERIFYING)],
            delay_per_stage=ui_cfg.loading_dot_delay * 3,
        )

        name = message.from_user.first_name if message.from_user else ""
        screen = welcome_screen(
            name,
            is_staff=role in (Role.STAFF, Role.ADMIN),
            is_admin=role is Role.ADMIN,
        )

        await asyncio.sleep(ui_cfg.sticker_delete_delay)
        await start_sticker.delete()
        await msg.delete()

        await send_screen(client, message.chat.id, screen)
