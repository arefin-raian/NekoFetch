"""Admin panel: settings (feature toggles), queue view, analytics, publish approval.

All handlers are gated by role — staff can see the queue and approval panel; admins can
additionally toggle features and view analytics. Feature toggles are applied live via
SettingsService and persisted to MongoDB.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from nekofetch.bots.admin.keyboards import admin_home_keyboard
from nekofetch.core.constants import DIAMOND_FILLED, DIAMOND_HOLLOW
from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui import progress
from nekofetch.ui.components import cb, keyboard


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    # ── admin home ──
    @client.on_callback_query(filters.regex(r"^admin\|home"))
    async def _home(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await q.message.edit_text("**◈ Admin Panel**", reply_markup=admin_home_keyboard())

    # ── settings: feature toggles ──
    @client.on_callback_query(filters.regex(r"^settings\|home"))
    async def _settings(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await _render_settings(q)

    async def _render_settings(q: CallbackQuery) -> None:
        from nekofetch.services.settings_service import SettingsService

        features = SettingsService(container).feature_map()
        rows = []
        for name, on in features.items():
            glyph = DIAMOND_FILLED if on else DIAMOND_HOLLOW
            label = f"{glyph} {name.replace('_', ' ').title()}"
            rows.append([(label, cb("settings", "toggle", name))])
        rows.append([("◂ Back", cb("admin", "home"))])
        await q.message.edit_text(
            "**▸ Feature Settings**\n\n"
            f"{DIAMOND_FILLED} enabled   {DIAMOND_HOLLOW} disabled\n"
            "Tap to toggle. Changes apply immediately.",
            reply_markup=keyboard(*rows),
        )

    @client.on_callback_query(filters.regex(r"^settings\|toggle"))
    async def _toggle(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.settings_service import SettingsService

        feature = q.data.split("|", 2)[2]
        new_val = await SettingsService(container).toggle_feature(feature)
        await q.answer(f"{feature} {'on' if new_val else 'off'}")
        await _render_settings(q)

    # ── downloads queue ──
    @client.on_callback_query(filters.regex(r"^queue\|view"))
    async def _queue(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService

        await q.answer()
        rows = await QueueService(container).dashboard()
        if not rows:
            await q.message.edit_text(f"**{L('queue_title')}**\n\n{L('queue_empty')}")
            return
        blocks = []
        for r in rows:
            blocks.append(
                f"{DIAMOND_FILLED} **{r.anime_title}**\n"
                f"{L('label_status')}: {r.status}\n"
                f"{progress.bar(r.progress)}\n"
                f"{L('label_speed')}: {progress.human_speed(r.speed_bps)}   "
                f"{L('label_eta')}: {progress.human_eta(r.eta_seconds)}"
            )
        await q.message.edit_text(
            f"**{L('queue_title')}**\n\n" + "\n\n".join(blocks),
            reply_markup=keyboard([("⟳ Refresh", cb("queue", "view", 0)),
                                   ("◂ Back", cb("admin", "home"))]),
        )

    # ── analytics ──
    @client.on_callback_query(filters.regex(r"^admin\|analytics"))
    async def _analytics(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.VIEW_ANALYTICS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.analytics_service import AnalyticsService

        await q.answer()
        s = await AnalyticsService(container).dashboard()
        top = "\n".join(f"  {i + 1}. {t} ({c})" for i, (t, c) in enumerate(s.most_requested)) or "  —"
        await q.message.edit_text(
            "**▸ Analytics**\n\n"
            f"{DIAMOND_FILLED} Total Users: {s.total_users}\n"
            f"{DIAMOND_FILLED} Total Downloads: {s.total_downloads}\n"
            f"{DIAMOND_FILLED} Queue Size: {s.queue_size}\n"
            f"{DIAMOND_FILLED} Failed Tasks: {s.failed_tasks}\n"
            f"{DIAMOND_FILLED} Published: {s.published}\n\n"
            f"Most Requested:\n{top}",
            reply_markup=keyboard([("◂ Back", cb("admin", "home"))]),
        )
