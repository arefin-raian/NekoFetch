"""Admin storage-channel panel: assisted pack indexing + pack listing.

Assisted indexing records content you've already posted to the database channel as a
deliverable pack. The admin supplies a compact line:

    anime_ref | season | resolution | language | start_message_id | end_message_id

where ``language`` is one of sub / dub / dual. NekoFetch reads the message range, keeps
the media as the ordered file list, and stores the pack.
"""

from __future__ import annotations

from pyrogram import Client, filters
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
        await q.message.edit_text(
            "**▸ Storage Channel**\n\n"
            f"Status: {'enabled' if enabled else 'disabled'}\n"
            f"Channel: `{container.config.storage_channel.channel_id or 'not set'}`",
            reply_markup=keyboard(
                [("➜ Index Pack", cb("storage", "index"))],
                [("▸ List Packs", cb("storage", "list"))],
                [("◂ Back", cb("admin", "home"))],
            ),
        )

    @client.on_callback_query(filters.regex(r"^storage\|index"))
    async def _index(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_INDEX)
        await q.answer()
        await q.message.edit_text(
            "**Index a Pack**\n\n"
            "Send one line:\n"
            "`anime_ref | season | resolution | language | start_id | end_id`\n\n"
            "Example:\n"
            "`naruto-shippuden | 1 | 1080p | dual | 1201 | 1705`\n\n"
            "language = sub / dub / dual. start_id..end_id is the message range in the "
            "database channel (header through end sticker)."
        )

    @client.on_callback_query(filters.regex(r"^storage\|list"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        async with container.session() as session:
            packs = (
                await session.execute(select(StoragePack).limit(30))
            ).scalars().all()
        if not packs:
            await q.message.edit_text("**▸ Storage Packs**\n\nNo packs indexed yet.")
            return
        lines = [
            f"{DIAMOND_FILLED} {p.anime_title} S{p.season} [{p.resolution}] "
            f"[{p.audio.value if hasattr(p.audio, 'value') else p.audio}] — {p.file_count} files"
            for p in packs
        ]
        await q.message.edit_text("**▸ Storage Packs**\n\n" + "\n".join(lines))

    # Group 2 so it coexists with request-flow (0) and bot-token (1) text handlers.
    @client.on_message(filters.text & ~filters.command(["start"]), group=2)
    async def _index_input(_: Client, message: Message) -> None:
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_INDEX:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.MANAGE_STORAGE)):
            return
        await fsm.clear(message.from_user.id)

        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 6:
            await message.reply("Expected 6 fields separated by `|`. Try again from the panel.")
            return
        ref, season_s, resolution, lang_s, start_s, end_s = parts
        audio = _LANG.get(lang_s.lower())
        if audio is None or not (season_s.isdigit() and start_s.isdigit() and end_s.isdigit()):
            await message.reply("Couldn't parse fields. Check season/ids are numbers and language is sub/dub/dual.")
            return

        storage = StorageChannelService(container)
        status = await message.reply("Indexing pack…")
        try:
            pack = await storage.index_pack(
                storage.key_from(ref, int(season_s), resolution, audio),
                title=ref.replace("-", " ").title(),
                start_message_id=int(start_s),
                end_message_id=int(end_s),
            )
        except NekoFetchError as exc:
            await status.edit_text(f"✕ {exc.detail or 'Indexing failed (is the storage channel enabled?)'}")
            return
        await status.edit_text(
            f"{DIAMOND_FILLED} **Pack indexed**\n\n"
            f"{pack.anime_title} S{pack.season} [{pack.resolution}] [{audio.value}]\n"
            f"{pack.file_count} files (messages {pack.start_message_id}–{pack.end_message_id})"
        )
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).event(
            "admin", "pack_indexed", anime=pack.anime_title, season=pack.season,
            resolution=pack.resolution, files=pack.file_count, user=message.from_user.id,
        )
