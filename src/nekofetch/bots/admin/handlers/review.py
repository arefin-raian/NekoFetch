from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard, paginate
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx

PAGE_SIZE = 8
STATE_MANUAL = "staff:await_manual"


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    def _scope_label(req) -> str:
        if req.episodes:
            return f"season {req.season or 1} · eps {', '.join(map(str, req.episodes))}"
        if req.season:
            return f"season {req.season}"
        return req.scope.replace("_", " ").title()

    async def _render_list(q: CallbackQuery, page: int) -> None:
        from nekofetch.services.request_service import RequestService

        await loading_animation(q.message, "loading reviews")
        pending = await RequestService(container).list_pending()
        if not pending:
            await q.message.edit_text(
                f"{bq('<b>▸ review requests</b>')}\n\n{bq('no pending requests right now.')}",
                reply_markup=keyboard([("← back", cb("admin", "home"))]),
                parse_mode=ParseMode.HTML,
            )
            return
        items = [
            (f"#{r.code} · {r.anime_title[:28]}", cb("staff", "rdetail", r.code))
            for r in pending
        ]
        kb = paginate(items, page=page, nav_action="staff|rpage", page_size=PAGE_SIZE)
        kb.inline_keyboard.append(keyboard([("← back", cb("admin", "home"))]).inline_keyboard[0])
        await q.message.edit_text(
            f"{bq(f'<b>▸ review requests</b>')}\n\n"
            f"{bq(f'{len(pending)} awaiting review. tap one to review.')}",
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
            f"{bq(f'<b>▸ review · #{req.code}</b>')}\n\n"
            f"{bq(f'<b>anime:</b> {req.anime_title}')}\n"
            f"{bq(f'<b>status:</b> {req.status}')}\n"
            f"{bq(f'<b>scope:</b> {_scope_label(req)}')}\n"
            f"{bq(f'<b>current source:</b> {req.source}')}\n"
            f"{bq(f'<b>requested by:</b> <code>{req.user_id}</code>')}"
        )
        # Source selection: first row Telegram / Website / Torrent, second row Reject
        await q.message.edit_text(
            text,
            reply_markup=keyboard(
                [(L("admin_btn_telegram"), cb("staff", "rsource", code, "telegram")),
                 (L("admin_btn_website"), cb("staff", "rsource", code, "website")),
                 (L("admin_btn_torrent"), cb("staff", "rsource", code, "torrent"))],
                [(L("admin_btn_reject"), cb("staff", "rreject", code))],
                [("← back", cb("staff", "requests", 0))],
            ),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^staff\|rsource"))
    async def _source_select(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, chosen_source = parts[2], parts[3]

        if chosen_source == "telegram":
            # Show Automatic / Manual sub-flow
            await q.answer()
            await q.message.edit_text(
                f"{bq(L('admin_tg_choose'))}",
                reply_markup=keyboard(
                    [(L("admin_btn_automatic"), cb("staff", "rtgmode", code, "auto")),
                     (L("admin_btn_manual"), cb("staff", "rtgmode", code, "manual"))],
                    [("← back", cb("staff", "rdetail", code))],
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        if chosen_source == "website":
            # Website source: show provider preference + fallback priority
            await q.answer()
            await q.message.edit_text(
                f"{bq(L('admin_btn_website'))}\n\n"
                f"{bq(L('site_preference_prompt'))}",
                reply_markup=keyboard(
                    [("1️⃣ AniKoto (primary)", cb("staff", "rsiteprio", code, "anikoto", "kickassanime")),
                     ("1️⃣ KickAssAnime (primary)", cb("staff", "rsiteprio", code, "kickassanime", "anikoto"))],
                    [("← back", cb("staff", "rdetail", code))],
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        # Torrent: update source and queue directly
        await loading_animation(q.message, "updating")
        try:
            await RequestService(container).update_source(code, chosen_source)
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
            return
        await q.answer(f"{chosen_source} · queued (job #{job_id})", show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rsiteprio"))
    async def _site_priority(_: Client, q: CallbackQuery) -> None:
        """Confirm website provider priority list and queue the request."""
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 4)
        code, primary, fallback = parts[2], parts[3], parts[4]
        priority_str = f"{primary}>{fallback}"

        await loading_animation(q.message, "queuing")
        try:
            await RequestService(container).update_source(code, priority_str)
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
            return
        await q.answer(f"website ({primary}) · queued (job #{job_id})", show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rtgmode"))
    async def _tg_mode(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, mode = parts[2], parts[3]

        if mode == "auto":
            # Automatic: update source and queue
            await loading_animation(q.message, "queuing")
            try:
                await RequestService(container).update_source(code, "telegram")
                job_id = await QueueService(container).enqueue(code)
            except NekoFetchError as exc:
                await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
                return
            await q.answer(f"telegram · queued (job #{job_id})", show_alert=True)
            await _render_list(q, 0)
        elif mode == "manual":
            # Manual: set FSM state, prompt for files
            await fsm.set(q.from_user.id, STATE_MANUAL, code=code)
            await q.answer()
            await q.message.edit_text(
                bq(L("admin_tg_manual_prompt")),
                reply_markup=keyboard([("← back", cb("staff", "rdetail", code))]),
                parse_mode=ParseMode.HTML,
            )

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
        await q.answer("rejected")
        await _render_list(q, 0)

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=4)
    async def _manual_input(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_MANUAL:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.QUEUE_DOWNLOADS)):
            return

        code = data.get("code")
        if not code:
            await fsm.clear(message.from_user.id)
            return

        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        # Update source and queue
        try:
            await RequestService(container).update_source(code, "telegram_manual")
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await message.reply(
                bq(f"✕ {exc.detail or 'could not queue request.'}"),
                parse_mode=ParseMode.HTML,
            )
            await fsm.clear(message.from_user.id)
            return

        await fsm.clear(message.from_user.id)
        await message.reply(
            bq(f"<b>✅ request queued</b>\n\nfiles will be processed manually. job #{job_id}."),
            parse_mode=ParseMode.HTML,
        )
