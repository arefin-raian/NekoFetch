from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from nekofetch.bots.admin.keyboards import admin_home_keyboard
from nekofetch.core.constants import DIAMOND_FILLED, DIAMOND_HOLLOW
from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui import progress
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx, small_caps


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    @client.on_callback_query(filters.regex(r"^admin\|home"))
    async def _home(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await q.message.edit_text(
            f"{bq('<b>ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>')}\n\n"
            f"{bqx('ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ᴅᴏᴡɴʟᴏᴀᴅs, ᴀᴘᴘʀᴏᴠᴀʟs, sᴛᴀꜰꜰ, ᴀɴᴅ sᴇᴛᴛɪɴɢs.')}",
            reply_markup=admin_home_keyboard(),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^settings\|home"))
    async def _settings(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await _render_settings(q)

    async def _render_settings(q: CallbackQuery) -> None:
        from nekofetch.services.settings_service import SettingsService

        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ sᴇᴛᴛɪɴɢs")
        features = SettingsService(container).feature_map()
        rows = []
        for name, on in features.items():
            glyph = DIAMOND_FILLED if on else DIAMOND_HOLLOW
            label = f"{glyph} {small_caps(name.replace('_', ' ').title())}"
            rows.append([(label, cb("settings", "toggle", name))])
        rows.append([("← ʙᴀᴄᴋ", cb("admin", "home"))])
        await q.message.edit_text(
            f"{bq('<b>▸ ꜰᴇᴀᴛᴜʀᴇ sᴇᴛᴛɪɴɢs</b>')}\n\n"
            f"{bq(f'{DIAMOND_FILLED} ᴇɴᴀʙʟᴅ   {DIAMOND_HOLLOW} ᴅɪsᴀʙʟᴇᴅ')}\n\n"
            f"{bq('ᴛᴀᴘ ᴛᴏ ᴛᴏɢɢʟᴇ. ᴄʜᴀɴɢᴇs ᴀᴘᴘʟʏ ɪᴍᴍᴇᴅɪᴀᴛᴇʟʏ.')}",
            reply_markup=keyboard(*rows),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^settings\|toggle"))
    async def _toggle(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.settings_service import SettingsService

        feature = q.data.split("|", 2)[2]
        new_val = await SettingsService(container).toggle_feature(feature)
        await q.answer(small_caps(f"{feature} {'on' if new_val else 'off'}"))
        await _render_settings(q)

    @client.on_callback_query(filters.regex(r"^queue\|view"))
    async def _queue(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService

        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ ǫᴜᴇᴜᴇ")
        await q.answer()
        rows = await QueueService(container).dashboard()
        qt = L("queue_title")
        qe = L("queue_empty")
        if not rows:
            await q.message.edit_text(
                f"{bq(f'<b>{qt}</b>')}\n\n{bq(qe)}",
                parse_mode=ParseMode.HTML,
            )
            return
        blocks = []
        for r in rows:
            blocks.append(
                progress.queue_block_html(
                    anime_title=r.anime_title,
                    status=r.status,
                    progress=r.progress,
                    speed_bps=r.speed_bps,
                    eta_seconds=r.eta_seconds,
                    current_episode=r.current_episode,
                    downloaded_bytes=r.downloaded_bytes,
                    total_bytes=r.total_bytes,
                    job_id=r.job_id,
                )
            )
        await q.message.edit_text(
            f"{bq(f'<b>{qt}</b>')}\n\n" + "\n\n".join(blocks),
            reply_markup=keyboard([("⟳ ʀᴇꜰʀᴇsʜ", cb("queue", "view", 0)),
                                   ("← ʙᴀᴄᴋ", cb("admin", "home"))]),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^admin\|analytics"))
    async def _analytics(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.VIEW_ANALYTICS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.analytics_service import AnalyticsService

        await loading_animation(q.message, "ꜰᴇᴛᴄʜɪɴɢ sᴛᴀᴛs")
        await q.answer()
        s = await AnalyticsService(container).dashboard()
        top = "\n".join(f"  {i + 1}. {t} ({c})" for i, (t, c) in enumerate(s.most_requested)) or "  —"
        await q.message.edit_text(
            f"{bq('<b>▸ ᴀɴᴀʟʏᴛɪᴄs</b>')}\n\n"
            f"{bq(f'<b>{DIAMOND_FILLED} ᴛᴏᴛᴀʟ ᴜsᴇʀs:</b> <code>{s.total_users}</code>')}\n"
            f"{bq(f'<b>{DIAMOND_FILLED} ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅs:</b> <code>{s.total_downloads}</code>')}\n"
            f"{bq(f'<b>{DIAMOND_FILLED} ǫᴜᴇᴜᴇ sɪᴢᴇ:</b> <code>{s.queue_size}</code>')}\n"
            f"{bq(f'<b>{DIAMOND_FILLED} ꜰᴀɪʟᴇᴅ ᴛᴀsᴋs:</b> <code>{s.failed_tasks}</code>')}\n"
            f"{bq(f'<b>{DIAMOND_FILLED} ᴘᴜʙʟɪsʜᴇᴅ:</b> <code>{s.published}</code>')}\n\n"
            f"{bq(f'<b>ᴍᴏsᴛ ʀᴇǫᴜᴇsᴛᴇᴅ:</b>\n{top}')}",
            reply_markup=keyboard([("← ʙᴀᴄᴋ", cb("admin", "home"))]),
            parse_mode=ParseMode.HTML,
        )
