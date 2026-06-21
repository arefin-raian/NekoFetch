"""Publish-approval panel.

    Anime / Files / Resolution / Language / Thumbnail / Metadata
    [ Publish ] [ Reprocess ] [ Cancel ]

Only after approval does content become available to users.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard


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

        await q.answer()
        ready = await PublishingService(container).list_ready()
        if not ready:
            await q.message.edit_text("**▸ Approvals**\n\nNothing awaiting approval.")
            return
        item = ready[0]
        text = (
            f"**{L('publish_panel_title')}**\n\n"
            f"{L('label_anime')}: {item.title}\n"
            f"{L('label_files')}: {item.files}\n"
            f"{L('label_resolution')}: {item.resolution or '—'}\n"
            f"{L('label_language')}: {item.audio or '—'}\n"
            f"{L('label_thumbnail')}: "
            f"{L('value_available') if item.has_thumbnail else L('value_unavailable')}\n"
            f"{L('label_metadata')}: {L('value_updated')}"
        )
        await q.message.edit_text(
            text,
            reply_markup=keyboard(
                [(L("btn_publish"), cb("approve", "pub", item.code)),
                 (L("btn_reprocess"), cb("approve", "reproc", item.code))],
                [(L("btn_cancel"), cb("approve", "cancel", item.code))],
            ),
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
            count = await svc.publish(code)
            await q.answer(f"Published {count} files", show_alert=True)
            await q.message.edit_text(f"**{L('status_published')}**\n\n#{code} — {count} files.")
        elif action == "reproc":
            await svc.reprocess(code)
            await q.answer("Reprocessed")
        else:
            await svc.cancel(code)
            await q.answer("Cancelled")
            await q.message.edit_text(f"#{code} cancelled.")
