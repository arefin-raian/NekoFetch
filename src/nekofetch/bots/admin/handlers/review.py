from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.localization.messages import M
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard, paginate
from nekofetch.ui.screens import show

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
            return L(M.SCOPE_SEASON_EPS, n=req.season or 1,
                     eps=", ".join(map(str, req.episodes)))
        if req.season:
            return L(M.SCOPE_SEASON, n=req.season)
        return req.scope.replace("_", " ").title()

    async def _render_list(q: CallbackQuery, page: int) -> None:
        from nekofetch.services.request_service import RequestService

        pending = await RequestService(container).list_pending()
        back = [(L(M.BTN_BACK), cb("admin", "home"))]
        if not pending:
            caption = f"{L(M.REVIEW_TITLE)}\n\n{L(M.REVIEW_EMPTY)}"
            await show(client, q.message, caption, keyboard(back))
            return
        items = [
            (L(M.REVIEW_ROW, code=r.code, title=r.anime_title[:28]),
             cb("staff", "rdetail", r.code))
            for r in pending
        ]
        kb = paginate(items, page=page, nav_action="staff|rpage", page_size=PAGE_SIZE)
        kb.inline_keyboard.append(keyboard(back).inline_keyboard[0])
        caption = f"{L(M.REVIEW_TITLE)}\n\n{L(M.REVIEW_COUNT, n=len(pending))}"
        await show(client, q.message, caption, kb)

    @client.on_callback_query(filters.regex(r"^staff\|requests"))
    async def _requests(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        parts = q.data.split("|")
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _render_list(q, page)

    @client.on_callback_query(filters.regex(r"^staff\|rpage"))
    async def _rpage(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        await _render_list(q, int(q.data.split("|")[-1]))

    @client.on_callback_query(filters.regex(r"^staff\|rdetail"))
    async def _detail(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        try:
            req = await RequestService(container).get(code)
        except NekoFetchError:
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            await _render_list(q, 0)
            return
        await q.answer()
        caption = (
            f"{L(M.REVIEW_DETAIL_TITLE, code=req.code)}\n\n"
            + L(M.REVIEW_DETAIL_BODY, anime=req.anime_title, status=req.status,
                scope=_scope_label(req), source=req.source, by=req.user_id)
        )
        kb = keyboard(
            [(L(M.ADMIN_BTN_TELEGRAM), cb("staff", "rsource", code, "telegram")),
             (L(M.ADMIN_BTN_WEBSITE), cb("staff", "rsource", code, "website")),
             (L(M.ADMIN_BTN_TORRENT), cb("staff", "rsource", code, "torrent"))],
            [(L(M.ADMIN_BTN_REJECT), cb("staff", "rreject", code))],
            [(L(M.BTN_BACK), cb("staff", "requests", 0))],
        )
        await show(client, q.message, caption, kb)

    @client.on_callback_query(filters.regex(r"^staff\|rsource"))
    async def _source_select(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, chosen_source = parts[2], parts[3]

        if chosen_source == "telegram":
            await q.answer()
            kb = keyboard(
                [(L(M.ADMIN_BTN_AUTOMATIC), cb("staff", "rtgmode", code, "auto")),
                 (L(M.ADMIN_BTN_MANUAL), cb("staff", "rtgmode", code, "manual"))],
                [(L(M.BTN_BACK), cb("staff", "rdetail", code))],
            )
            await show(client, q.message, L(M.ADMIN_TG_CHOOSE), kb)
            return

        if chosen_source == "website":
            # Website sources always process the ENTIRE franchise, never a season.
            await q.answer()
            caption = f"{L(M.SITE_PREFERENCE_TITLE)}\n\n{L(M.SITE_PREFERENCE_PROMPT)}"
            kb = keyboard(
                [(L(M.SITE_BTN_ANIKOTO_PRIMARY),
                  cb("staff", "rsiteprio", code, "anikoto", "kickassanime")),
                 (L(M.SITE_BTN_KICKASS_PRIMARY),
                  cb("staff", "rsiteprio", code, "kickassanime", "anikoto"))],
                [(L(M.BTN_BACK), cb("staff", "rdetail", code))],
            )
            await show(client, q.message, caption, kb)
            return

        # Torrent: torrent packs are already complete — assign and queue directly.
        try:
            await RequestService(container).update_source(code, chosen_source)
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_QUEUED, source=chosen_source, job=job_id), show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rsiteprio"))
    async def _site_priority(_: Client, q: CallbackQuery) -> None:
        """Confirm website provider priority list and queue the request."""
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 4)
        code, primary, fallback = parts[2], parts[3], parts[4]
        priority_str = f"{primary}>{fallback}"
        try:
            await RequestService(container).update_source(code, priority_str)
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_QUEUED, source=primary, job=job_id), show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rtgmode"))
    async def _tg_mode(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, mode = parts[2], parts[3]

        if mode == "auto":
            try:
                await RequestService(container).update_source(code, "telegram")
                job_id = await QueueService(container).enqueue(code)
            except NekoFetchError as exc:
                await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
                return
            await q.answer(L(M.TOAST_QUEUED, source="telegram", job=job_id), show_alert=True)
            await _render_list(q, 0)
        elif mode == "manual":
            await fsm.set(q.from_user.id, STATE_MANUAL, code=code)
            await q.answer()
            kb = keyboard([(L(M.BTN_BACK), cb("staff", "rdetail", code))])
            await show(client, q.message, L(M.ADMIN_TG_MANUAL_PROMPT), kb)

    @client.on_callback_query(filters.regex(r"^staff\|rreject"))
    async def _reject(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        try:
            await RequestService(container).reject(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_REJECTED))
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

        try:
            await RequestService(container).update_source(code, "telegram_manual")
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await message.reply(
                L(M.MANUAL_QUEUE_FAILED, reason=exc.detail or L(M.ERR_GENERIC)),
                parse_mode=ParseMode.HTML,
            )
            await fsm.clear(message.from_user.id)
            return

        await fsm.clear(message.from_user.id)
        await message.reply(L(M.MANUAL_QUEUED, job=job_id), parse_mode=ParseMode.HTML)
