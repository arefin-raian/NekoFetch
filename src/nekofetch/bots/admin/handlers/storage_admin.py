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
        status_text = "enabled" if enabled else "disabled"
        ch_id = container.config.storage_channel.channel_id or "not set"
        await q.message.edit_text(
            f"{bq('<b>▸ storage channel</b>')}\n\n"
            f"{bq(f'status: {status_text}')}\n"
            f"{bq(f'channel: <code>{ch_id}</code>')}",
            reply_markup=keyboard(
                [("➜ index pack", cb("storage", "index"))],
                [("▸ list packs", cb("storage", "list"))],
                [("← back", cb("admin", "home"))],
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
            bq("<b>index a pack</b>\n\n"
               "send one line:\n"
               "<code>anime_ref | season | resolution | language | start_id | end_id</code>\n\n"
               "example:\n"
               "<code>naruto-shippuden | 1 | 1080p | dual | 1201 | 1705</code>\n\n"
               "language = sub / dub / dual. start_id..end_id is the message range "
               "in the database channel (header through end sticker)."),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^storage\|list"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await loading_animation(q.message, "loading packs")
        await q.answer()
        async with container.session() as session:
            packs = (
                await session.execute(select(StoragePack).limit(30))
            ).scalars().all()
        if not packs:
            await q.message.edit_text(
                f"{bq('<b>▸ storage packs</b>')}\n\n{bq('no packs indexed yet.')}",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [
            f"{DIAMOND_FILLED} {p.anime_title} S{p.season} [{p.resolution}] "
            f"[{p.audio.value if hasattr(p.audio, 'value') else p.audio}] — {p.file_count} files"
            for p in packs
        ]
        await q.message.edit_text(
            f"{bq('<b>▸ storage packs</b>')}\n\n" + "\n".join(lines),
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
                bq("expected 6 fields separated y <code>|</code>. try again from the panel."),
                parse_mode=ParseMode.HTML,
            )
            return
        ref, season_s, resolution, lang_s, start_s, end_s = parts
        audio = _LANG.get(lang_s.lower())
        if audio is None or not (season_s.isdigit() and start_s.isdigit() and end_s.isdigit()):
            await message.reply(
                bq("couldn't parse fields. check season/ids are numbers and language is sub/dub/dual."),
                parse_mode=ParseMode.HTML,
            )
            return

        storage = StorageChannelService(container)
        status = await message.reply(
            "<b>indexing pack!</b>", parse_mode=ParseMode.HTML
        )
        await loading_animation(status, "indexing pack")
        try:
            pack = await storage.index_pack(
                storage.key_from(ref, int(season_s), resolution, audio),
                title=ref.replace("-", " ").title(),
                start_message_id=int(start_s),
                end_message_id=int(end_s),
            )
        except NekoFetchError as exc:
            await status.edit_text(
                bq(f"✕ {exc.detail or 'indexing failed (is the storage channel enabld?)'}"),
                parse_mode=ParseMode.HTML,
            )
            return
        detail = (
            f"{pack.anime_title} S{pack.season} [{pack.resolution}] [{audio.value}]\n"
            f"{pack.file_count} files (messages {pack.start_message_id}–{pack.end_message_id})"
        )
        await status.edit_text(
            f"{bq(f'{DIAMOND_FILLED} <b>pack indexed</b>')}\n\n"
            f"{bq(detail)}",
            parse_mode=ParseMode.HTML,
        )
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "pack_indexed", anime=pack.anime_title, season=pack.season,
            resolution=pack.resolution, files=pack.file_count, user=message.from_user.id,
        )
