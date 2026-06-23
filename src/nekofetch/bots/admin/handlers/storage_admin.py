from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message
from sqlalchemy import select

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import AudioType, Permission
from nekofetch.infrastructure.database.postgres.models import StoragePack
from nekofetch.services.auth_service import AuthService
from nekofetch.services.storage_channel_service import StorageChannelService
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx

STATE_INDEX = "storage:await_index"

_LANG = {
    "sub": AudioType.SUBBED, "subbed": AudioType.SUBBED,
    "dub": AudioType.DUBBED, "dubbed": AudioType.DUBBED,
    "dual": AudioType.DUAL_AUDIO, "dual_audio": AudioType.DUAL_AUDIO,
}


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(q: CallbackQuery) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, Permission.MANAGE_STORAGE))

    @client.on_callback_query(filters.regex(r"^admin\|storage"))
    async def _menu(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        enabled = container.config.storage_channel.enabled
        status_text = "ᴇɴᴀʙʟᴇᴅ" if enabled else "ᴅɪsᴀʙʟᴇᴅ"
        ch_id = container.config.storage_channel.channel_id or "ɴᴏᴛ sᴇᴛ"
        await q.message.edit_text(
            f"{bq('<b>▸ sᴛᴏʀᴀɢᴇ ᴄʜᴀɴɴᴇʟ</b>')}\n\n"
            f"{bq(f'sᴛᴀᴛᴜs: <code>{status_text}</code>')}\n"
            f"{bq(f'ᴄʜᴀɴɴᴇʟ: <code>{ch_id}</code>')}",
            reply_markup=keyboard(
                [("➜ ɪɴᴅᴇx ᴘᴀᴄᴋ", cb("storage", "index"))],
                [("▸ ʟɪsᴛ ᴘᴀᴄᴋs", cb("storage", "list"))],
                [("← ʙᴀᴄᴋ", cb("admin", "home"))],
            ),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^storage\|index"))
    async def _index(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_INDEX)
        await q.answer()
        await q.message.edit_text(
            bq("<b>ɪɴᴅᴇx ᴀ ᴘᴀᴄᴋ</b>\n\n"
               "sᴇɴᴅ ᴏɴᴇ ʟɪɴᴇ:\n"
               "<code>ᴀɴɪᴍᴇ_ʀᴇꜰ | sᴇᴀsᴏɴ | ʀᴇsᴏʟᴜᴛɪᴏɴ | ʟᴀɴɢᴜᴀɢᴇ | sᴛᴀʀᴛ_ɪᴅ | ᴇɴᴅ_ɪᴅ</code>\n\n"
               "ᴇxᴀᴍᴘʟᴇ:\n"
               "<code>ɴᴀʀᴜᴛᴏ-sʜɪᴘᴘᴜᴅᴇɴ | 1 | 1080ᴘ | ᴅᴜᴀʟ | 1201 | 1705</code>\n\n"
               "ʟᴀɴɢᴜᴀɢᴇ = sᴜʙ / ᴅᴜʙ / ᴅᴜᴀʟ. sᴛᴀʀᴛ_ɪᴅ..ᴇɴᴅ_ɪᴅ ɪs ᴛʜᴇ ᴍᴇssᴀɢᴇ ʀᴀɴɢᴇ "
               "ɪɴ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟ (ʜᴇᴀᴅᴇʀ ᴛʜʀᴏᴜɢʜ ᴇɴᴅ sᴛɪᴄᴋᴇʀ)."),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^storage\|list"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ ᴘᴀᴄᴋs")
        await q.answer()
        async with container.session() as session:
            packs = (
                await session.execute(select(StoragePack).limit(30))
            ).scalars().all()
        if not packs:
            await q.message.edit_text(
                f"{bq('<b>▸ sᴛᴏʀᴀɢᴇ ᴘᴀᴄᴋs</b>')}\n\n{bq('ɴᴏ ᴘᴀᴄᴋs ɪɴᴅᴇxᴇᴅ ʏᴇᴛ.')}",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [
            f"{DIAMOND_FILLED} {p.anime_title} S{p.season} [{p.resolution}] "
            f"[{p.audio.value if hasattr(p.audio, 'value') else p.audio}] — {p.file_count} ꜰɪʟᴇs"
            for p in packs
        ]
        await q.message.edit_text(
            f"{bq('<b>▸ sᴛᴏʀᴀɢᴇ ᴘᴀᴄᴋs</b>')}\n\n" + "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=2)
    async def _index_input(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_INDEX:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.MANAGE_STORAGE)):
            return
        await fsm.clear(message.from_user.id)

        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 6:
            await message.reply(
                bq("ᴇxᴘᴇᴄᴛᴇᴅ 6 ꜰɪᴇʟᴅs sᴇᴘᴀʀᴀᴛᴇᴅ ʏ <code>|</code>. ᴛʀʏ ᴀɢᴀɪɴ ꜰʀᴏᴍ ᴛʜᴇ ᴘᴀɴᴇʟ."),
                parse_mode=ParseMode.HTML,
            )
            return
        ref, season_s, resolution, lang_s, start_s, end_s = parts
        audio = _LANG.get(lang_s.lower())
        if audio is None or not (season_s.isdigit() and start_s.isdigit() and end_s.isdigit()):
            await message.reply(
                bq("ᴄᴏᴜʟᴅɴ'ᴛ ᴘᴀʀsᴇ ꜰɪᴇʟᴅs. ᴄʜᴇᴄᴋ sᴇᴀsᴏɴ/ɪᴅs ᴀʀᴇ ɴᴜᴍʙᴇʀs ᴀɴᴅ ʟᴀɴɢᴜᴀɢᴇ ɪs sᴜʙ/ᴅᴜʙ/ᴅᴜᴀʟ."),
                parse_mode=ParseMode.HTML,
            )
            return

        storage = StorageChannelService(container)
        status = await message.reply(
            "<code>ɪɴᴅᴇxɪɴɢ ᴘᴀᴄᴋ!</code>", parse_mode=ParseMode.HTML
        )
        await loading_animation(status, "ɪɴᴅᴇxɪɴɢ ᴘᴀᴄᴋ")
        try:
            pack = await storage.index_pack(
                storage.key_from(ref, int(season_s), resolution, audio),
                title=ref.replace("-", " ").title(),
                start_message_id=int(start_s),
                end_message_id=int(end_s),
            )
        except NekoFetchError as exc:
            await status.edit_text(
                bq(f"✕ {exc.detail or 'ɪɴᴅᴇxɪɴɢ ꜰᴀɪʟᴇᴅ (ɪs ᴛʜᴇ sᴛᴏʀᴀɢᴇ ᴄʜᴀɴɴᴇʟ ᴇɴᴀʙʟᴅ?)'}"),
                parse_mode=ParseMode.HTML,
            )
            return
        detail = (
            f"{pack.anime_title} S{pack.season} [{pack.resolution}] [{audio.value}]\n"
            f"{pack.file_count} ꜰɪʟᴇs (ᴍᴇssᴀɢᴇs {pack.start_message_id}–{pack.end_message_id})"
        )
        await status.edit_text(
            f"{bq(f'{DIAMOND_FILLED} <b>ᴘᴀᴄᴋ ɪɴᴅᴇxᴇᴅ</b>')}\n\n"
            f"{bq(detail)}",
            parse_mode=ParseMode.HTML,
        )
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "pack_indexed", anime=pack.anime_title, season=pack.season,
            resolution=pack.resolution, files=pack.file_count, user=message.from_user.id,
        )
