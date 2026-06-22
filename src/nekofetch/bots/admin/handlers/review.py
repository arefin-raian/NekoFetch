"""Request review panel (staff).

    Review Requests -> [pending list] -> detail -> [ Approve -> Queue ] [ Reject ]

This is the bridge between a *pending* request and the download queue: approving a
request calls ``QueueService.enqueue`` (which creates a ``DownloadJob`` and flips the
request to ``QUEUED``), which is exactly what the Downloads Queue then displays. Without
this screen a request can never leave ``PENDING`` and the queue stays empty.

Listing/detail/reject require ``REVIEW_REQUESTS``; approving (enqueue) additionally
requires ``QUEUE_DOWNLOADS``. Staff hold both.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard, paginate

PAGE_SIZE = 8


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    def _scope_label(req) -> str:
        if req.episodes:
            return f"S{req.season or 1} · eps {', '.join(map(str, req.episodes))}"
        if req.season:
            return f"Season {req.season}"
        return req.scope.replace("_", " ").title()

    # ── list: "Review Requests" ──
    async def _render_list(q: CallbackQuery, page: int) -> None:
        from nekofetch.services.request_service import RequestService

        pending = await RequestService(container).list_pending()
        if not pending:
            await q.message.edit_text(
                "**▸ Review Requests**\n\nNo pending requests right now.",
                reply_markup=keyboard([("◂ Back", cb("admin", "home"))]),
            )
            return
        items = [
            (f"#{r.code} · {r.anime_title[:28]}", cb("staff", "rdetail", r.code))
            for r in pending
        ]
        kb = paginate(items, page=page, nav_action="staff|rpage", page_size=PAGE_SIZE)
        kb.inline_keyboard.append(keyboard([("◂ Back", cb("admin", "home"))]).inline_keyboard[0])
        await q.message.edit_text(
            f"**▸ Review Requests**\n\n{len(pending)} awaiting review. Tap one to review.",
            reply_markup=kb,
        )

    @client.on_callback_query(filters.regex(r"^staff\|requests"))
    async def _requests(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        # data: staff|requests|<page>
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

    # ── detail ──
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
            f"**▸ Review · #{req.code}**\n\n"
            f"{DIAMOND_FILLED} {L('label_anime')}: {req.anime_title}\n"
            f"{DIAMOND_FILLED} {L('label_status')}: {req.status}\n"
            f"{DIAMOND_FILLED} Scope: {_scope_label(req)}\n"
            f"{DIAMOND_FILLED} Source: {req.source}\n"
            f"{DIAMOND_FILLED} {L('label_requested_by')}: {req.user_id}"
        )
        await q.message.edit_text(
            text,
            reply_markup=keyboard(
                [("✓ Approve → Queue", cb("staff", "rapprove", req.code)),
                 ("✕ Reject", cb("staff", "rreject", req.code))],
                [("◂ Back", cb("staff", "requests", 0))],
            ),
        )

    # ── approve -> enqueue (the missing PENDING -> QUEUED bridge) ──
    @client.on_callback_query(filters.regex(r"^staff\|rapprove"))
    async def _approve(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService

        code = q.data.split("|", 2)[2]
        try:
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L("error_generic"), show_alert=True)
            return
        await q.answer(f"Queued (job #{job_id})", show_alert=True)
        await _render_list(q, 0)

    # ── reject ──
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
        await q.answer("Rejected")
        await _render_list(q, 0)
