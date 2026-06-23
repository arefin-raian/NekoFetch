from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, Permission.UPLOAD_CONTENT))

    @client.on_callback_query(filters.regex(r"^approve\|panel"))
    async def _panel(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.publishing_service import PublishingService

        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ ᴀᴘᴘʀᴏᴠᴀʟs")
        await q.answer()
        ready = await PublishingService(container).list_ready()
        if not ready:
            await q.message.edit_text(
                f"{bq('<b>▸ ᴀᴘᴘʀᴏᴠᴀʟs</b>')}\n\n{bq('ɴᴏᴛʜɪɴɢ ᴀᴡᴀɪᴛɪɴɢ ᴀᴘᴘʀᴏᴠᴀʟ.')}",
                parse_mode=ParseMode.HTML,
            )
            return
        item = ready[0]
        res = item.resolution or "—"
        aud = item.audio or "—"
        thumb = "✓ ᴀᴠᴀɪʟᴀʙʟᴇ" if item.has_thumbnail else "✗ ɴᴏɴᴇ"
        text = (
            f"{bq('<b>ᴄᴏɴᴛᴇɴᴛ ᴀᴘᴘʀᴏᴠᴀʟ</b>')}\n\n"
            f"{bqx(f'<b>ᴀɴɪᴍᴇ:</b> <code>{item.title}</code>\n'
                   f'<b>ꜰɪʟᴇs:</b> <code>{item.files}</code>\n'
                   f'<b>ʀᴇsᴏʟᴜᴛɪᴏɴ:</b> <code>{res}</code>\n'
                   f'<b>ʟᴀɴɢᴜᴀɢᴇ:</b> <code>{aud}</code>\n'
                   f'<b>ᴛʜᴜᴍʙɴᴀɪʟ:</b> <code>{thumb}</code>\n'
                   f'<b>ᴍᴇᴛᴀᴅᴀᴛᴀ:</b> <code>✓ ᴜᴘᴅᴀᴛᴇᴅ</code>')}"
        )
        await q.message.edit_text(
            text,
            reply_markup=keyboard(
                [(L("btn_publish"), cb("approve", "pub", item.code)),
                 (L("btn_reprocess"), cb("approve", "reproc", item.code))],
                [(L("btn_cancel"), cb("approve", "cancel", item.code))],
            ),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^approve\|(pub|reproc|cancel)"))
    async def _action(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.publishing_service import PublishingService

        _, action, code = q.data.split("|", 2)
        svc = PublishingService(container)
        if action == "pub":
            await loading_animation(q.message, "ᴘʀᴏᴄᴇssɪɴɢ")
            count = await svc.publish(code)
            await q.answer(f"Published {count} files", show_alert=True)
            sp = L("status_published")
            await q.message.edit_text(
                f"{bq(f'<b>{sp}</b>')}\n\n"
                f"{bq(f'<code>#{code}</code> — {count} ꜰɪʟᴇs.')}",
                parse_mode=ParseMode.HTML,
            )
        elif action == "reproc":
            await loading_animation(q.message, "ᴘʀᴏᴄᴇssɪɴɢ")
            await svc.reprocess(code)
            await q.answer("Reprocessed")
        else:
            await svc.cancel(code)
            await q.answer("Cancelled")
            await q.message.edit_text(
                bq(f"<code>#{code}</code> ᴄᴀɴᴄᴇʟʟᴇᴅ."),
                parse_mode=ParseMode.HTML,
            )
