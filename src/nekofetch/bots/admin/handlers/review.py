from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard, paginate
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx

PAGE_SIZE = 8


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    def _scope_label(req) -> str:
        if req.episodes:
            return f"sᴇᴀsᴏɴ {req.season or 1} · ᴇᴘs {', '.join(map(str, req.episodes))}"
        if req.season:
            return f"sᴇᴀsᴏɴ {req.season}"
        return req.scope.replace("_", " ").title()

    async def _render_list(q: CallbackQuery, page: int) -> None:
        from nekofetch.services.request_service import RequestService

        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ ʀᴇᴠɪᴇᴡs")
        pending = await RequestService(container).list_pending()
        if not pending:
            await q.message.edit_text(
                f"{bq('<b>▸ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs</b>')}\n\n{bq('ɴᴏ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs ʀɪɢʜᴛ ɴᴏᴡ.')}",
                reply_markup=keyboard([("← ʙᴀᴄᴋ", cb("admin", "home"))]),
                parse_mode=ParseMode.HTML,
            )
            return
        items = [
            (f"#{r.code} · {r.anime_title[:28]}", cb("staff", "rdetail", r.code))
            for r in pending
        ]
        kb = paginate(items, page=page, nav_action="staff|rpage", page_size=PAGE_SIZE)
        kb.inline_keyboard.append(keyboard([("← ʙᴀᴄᴋ", cb("admin", "home"))]).inline_keyboard[0])
        await q.message.edit_text(
            f"{bq(f'<b>▸ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs</b>')}\n\n"
            f"{bq(f'{len(pending)} ᴀᴡᴀɪᴛɪɴɢ ʀᴇᴠɪᴇᴡ. ᴛᴀᴘ ᴏɴᴇ ᴛᴏ ʀᴇᴠɪᴇᴡ.')}",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^staff\|requests"))
    async def _requests(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        parts = q.data.split("|")
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _render_list(q, page)

    @client.on_callback_query(filters.regex(r"^staff\|rpage"))
    async def _rpage(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await _render_list(q, int(q.data.split("|")[-1]))

    @client.on_callback_query(filters.regex(r"^staff\|rdetail"))
    async def _detail(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        try:
            req = await RequestService(container).get(code)
        except NekoFetchError:
            await q.answer(L("error_generic"), show_alert=True)
            await _render_list(q, 0)
            return
        await q.answer()
        text = (
            f"{bq(f'<b>▸ ʀᴇᴠɪᴇᴡ · #{req.code}</b>')}\n\n"
            f"{bq(f'<b>ᴀɴɪᴍᴇ:</b> <code>{req.anime_title}</code>')}\n"
            f"{bq(f'<b>sᴛᴀᴛᴜs:</b> <code>{req.status}</code>')}\n"
            f"{bq(f'<b>sᴄᴏᴘᴇ:</b> <code>{_scope_label(req)}</code>')}\n"
            f"{bq(f'<b>sᴏᴜʀᴄᴇ:</b> <code>{req.source}</code>')}\n"
            f"{bq(f'<b>ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ:</b> <code>{req.user_id}</code>')}"
        )
        await q.message.edit_text(
            text,
            reply_markup=keyboard(
                [("✓ ᴀᴘᴘʀᴏᴠᴇ → ǫᴜᴇᴜᴇ", cb("staff", "rapprove", req.code)),
                 ("✕ ʀᴇᴊᴇᴄᴛ", cb("staff", "rreject", req.code))],
                [("← ʙᴀᴄᴋ", cb("staff", "requests", 0))],
            ),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^staff\|rapprove"))
    async def _approve(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService

        code = q.data.split("|", 2)[2]
        await loading_animation(q.message, "ǫᴜᴇᴜɪɴɢ")
        try:
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
            return
        await q.answer(f"ǫᴜᴇᴜᴇᴅ (ᴊᴏʙ #{job_id})", show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rreject"))
    async def _reject(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        try:
            await RequestService(container).reject(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
            return
        await q.answer("ʀᴇᴊᴇᴄᴛᴇᴅ")
        await _render_list(q, 0)
