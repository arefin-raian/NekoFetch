from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message
from sqlalchemy import select

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import AudioType, Permission
from nekofetch.infrastructure.database.postgres.models import StoragePack
from nekofetch.localization.messages import M
from nekofetch.services.auth_service import AuthService
from nekofetch.services.storage_channel_service import StorageChannelService
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.screens import show

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
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        enabled = container.config.storage_channel.enabled
        status = L(M.STORAGE_STATUS_ENABLED) if enabled else L(M.STORAGE_STATUS_DISABLED)
        ch_id = container.config.storage_channel.channel_id or L(M.STORAGE_CHANNEL_UNSET)
        caption = f"{L(M.STORAGE_TITLE)}\n\n{L(M.STORAGE_STATUS, status=status, channel=ch_id)}"
        kb = keyboard(
            [(L(M.STORAGE_BTN_INDEX), cb("storage", "index"))],
            [(L(M.STORAGE_BTN_LIST), cb("storage", "list"))],
            [(L(M.BTN_BACK), cb("admin", "home"))],
        )
        await show(client, q.message, caption, kb)

    @client.on_callback_query(filters.regex(r"^storage\|index"))
    async def _index(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_INDEX)
        await q.answer()
        kb = keyboard([(L(M.BTN_BACK), cb("admin", "storage"))])
        await show(client, q.message, L(M.STORAGE_INDEX_PROMPT), kb)

    @client.on_callback_query(filters.regex(r"^storage\|list"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        async with container.session() as session:
            packs = (await session.execute(select(StoragePack).limit(30))).scalars().all()
        back = keyboard([(L(M.BTN_BACK), cb("admin", "storage"))])
        if not packs:
            await show(client, q.message,
                       f"{L(M.STORAGE_PACKS_TITLE)}\n\n{L(M.STORAGE_PACKS_EMPTY)}", back)
            return
        lines = [
            L(M.STORAGE_PACK_ROW, title=p.anime_title, season=p.season,
              resolution=p.resolution,
              audio=p.audio.value if hasattr(p.audio, "value") else p.audio,
              files=p.file_count)
            for p in packs
        ]
        await show(client, q.message,
                   f"{L(M.STORAGE_PACKS_TITLE)}\n\n" + "\n".join(lines), back)

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
            await message.reply(L(M.STORAGE_INDEX_BAD_COUNT), parse_mode=ParseMode.HTML)
            return
        ref, season_s, resolution, lang_s, start_s, end_s = parts
        audio = _LANG.get(lang_s.lower())
        if audio is None or not (season_s.isdigit() and start_s.isdigit() and end_s.isdigit()):
            await message.reply(L(M.STORAGE_INDEX_BAD_FIELDS), parse_mode=ParseMode.HTML)
            return

        storage = StorageChannelService(container)
        status = await message.reply(L(M.STORAGE_INDEXING), parse_mode=ParseMode.HTML)
        await loading_animation(status, L(M.STORAGE_INDEXING))
        try:
            pack = await storage.index_pack(
                storage.key_from(ref, int(season_s), resolution, audio),
                title=ref.replace("-", " ").title(),
                start_message_id=int(start_s),
                end_message_id=int(end_s),
            )
        except NekoFetchError as exc:
            await status.edit_text(
                L(M.STORAGE_INDEX_FAILED, reason=exc.detail or L(M.STORAGE_INDEX_FAILED_DEFAULT)),
                parse_mode=ParseMode.HTML,
            )
            return
        await status.edit_text(
            L(M.STORAGE_INDEXED, title=pack.anime_title, season=pack.season,
              resolution=pack.resolution, audio=audio.value, files=pack.file_count,
              start=pack.start_message_id, end=pack.end_message_id),
            parse_mode=ParseMode.HTML,
        )
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "pack_indexed", anime=pack.anime_title, season=pack.season,
            resolution=pack.resolution, files=pack.file_count, user=message.from_user.id,
        )
