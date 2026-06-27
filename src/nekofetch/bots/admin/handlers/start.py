from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.ui.components import cb
from nekofetch.ui.progress import staged_loading
from nekofetch.ui.screens import welcome as welcome_screen, send_screen


def register(client: Client, container: Container) -> None:
    ui_cfg = container.config.ui

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        user = getattr(message, "nf_user", None)
        role = Role(user.role) if user else Role.USER

        start_sticker = await client.send_sticker(
            chat_id=message.chat.id, sticker=ui_cfg.start_sticker_id
        )

        msg = await message.reply(
            "<b>connecting!</b>", parse_mode=ParseMode.HTML
        )
        await staged_loading(
            msg,
            ["connecting", "loading", "verifying access"],
            delay_per_stage=ui_cfg.loading_dot_delay * 3,
        )

        name = message.from_user.first_name if message.from_user else ""
        screen = welcome_screen(name)

        await asyncio.sleep(ui_cfg.sticker_delete_delay)
        await start_sticker.delete()
        await msg.delete()

        await send_screen(client, message.chat.id, screen)
