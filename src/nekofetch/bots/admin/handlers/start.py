from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from nekofetch.bots.admin.keyboards import welcome_keyboard
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.localization.i18n import Localizer
from nekofetch.ui.progress import staged_loading
from nekofetch.ui.typography import bq, bqx, heading, small_caps


def _welcome_caption(localizer: Localizer, role: Role, lang: str = "en") -> str:
    g = localizer.get
    mention = "{mention}"
    role_label = small_caps(g(f"role_{role.value}", lang))
    title = g("welcome_title", lang)
    subtitle = g("welcome_subtitle", lang)
    access_lvl = g("welcome_access_level", lang)
    return (
        f"{heading(title)}\n\n"
        f"{bqx(f'<b>{small_caps(subtitle)}</b>')}\n\n"
        f"{bq(f'<b>{small_caps(access_lvl)}:</b> <code>{role_label}</code>')}"
    )


def register(client: Client, container: Container) -> None:
    localizer = container.localizer
    ui_cfg = container.config.ui

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        user = getattr(message, "nf_user", None)
        role = Role(user.role) if user else Role.USER
        lang = user.language if user else "en"

        start_sticker = await client.send_sticker(
            chat_id=message.chat.id, sticker=ui_cfg.start_sticker_id
        )

        msg = await message.reply(
            "<code>ᴄᴏɴɴᴇᴄᴛɪɴɢ!</code>", parse_mode=ParseMode.HTML
        )
        await staged_loading(
            msg,
            ["ᴄᴏɴɴᴇᴄᴛɪɴɢ", "ʟᴏᴀᴅɪɴɢ", "ᴠᴇʀɪꜰʏɪɴɢ ᴀᴄᴄᴇss"],
            delay_per_stage=ui_cfg.loading_dot_delay * 3,
        )

        mention = message.from_user.mention if message.from_user else "User"
        caption = _welcome_caption(localizer, role, lang).replace("{mention}", mention)

        await asyncio.sleep(ui_cfg.sticker_delete_delay)
        await start_sticker.delete()
        await msg.delete()

        await client.send_photo(
            chat_id=message.chat.id,
            photo=ui_cfg.start_image_url,
            caption=caption,
            has_spoiler=ui_cfg.start_image_has_spoiler,
            parse_mode=ParseMode.HTML,
            reply_markup=welcome_keyboard(localizer, role, lang),
        )
