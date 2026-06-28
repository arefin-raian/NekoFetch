"""Admin panel + Settings control center.

Both surfaces use rotating artwork (via :func:`send_screen`) and pull every
string from the catalog. The Settings panel is *config-driven*: it introspects
the live ``AppConfig`` through :class:`SettingsService`, so any new config field
becomes editable automatically — booleans get a toggle, scalars an edit prompt.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Permission
from nekofetch.localization.messages import M, t
from nekofetch.services.auth_service import AuthService
from nekofetch.services.settings_service import SettingsService
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.screens import Screen, send_screen

STATE_EDIT = "settings:edit"

# Order in which config sections appear in the Settings menu.
_SETTINGS_ORDER = (
    "features", "sources", "downloads", "acquisition", "processing",
    "rename", "metadata", "thumbnail", "watermark", "branding",
    "distribution", "queue", "security", "access", "shortlink",
    "storage_channel", "log_channel", "main_channel", "index_channel", "ui",
)


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    svc = SettingsService(container)
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    def _admin_home() -> Screen:
        caption = f"{t(M.ADMIN_HOME_TITLE)}\n\n{t(M.ADMIN_HOME_INTRO)}"
        kb = keyboard(
            [(t(M.ADMIN_BTN_QUEUE), cb("queue", "view", 0)),
             (t(M.ADMIN_BTN_ANALYTICS), cb("admin", "analytics"))],
            [(t(M.ADMIN_BTN_STAFF), cb("admin", "staff")),
             (t(M.ADMIN_BTN_BOTS), cb("admin", "bots"))],
            [(t(M.ADMIN_BTN_SETTINGS), cb("settings", "home")),
             (t(M.ADMIN_BTN_STORAGE), cb("admin", "storage"))],
            [(t(M.ADMIN_BTN_APPROVALS), cb("approve", "panel")),
             (t(M.ADMIN_BTN_BROADCAST), cb("admin", "broadcast"))],
        )
        return Screen(caption=caption, image=_art(), keyboard=kb)

    @client.on_callback_query(filters.regex(r"^admin\|home"))
    async def _home(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        await send_screen(client, q.message.chat.id, _admin_home(), old_msg=q.message)

    # ── Settings: section list ─────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^settings\|home"))
    async def _settings_home(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        rows = []
        order = [s for s in _SETTINGS_ORDER if svc.section(s) is not None]
        for i in range(0, len(order), 2):
            row = [(t(M.SETTINGS_SECTIONS[s]), cb("settings", "sec", s)) for s in order[i:i + 2]]
            rows.append(row)
        rows.append([(t(M.BTN_BACK), cb("admin", "home"))])
        screen = Screen(
            caption=f"{t(M.SETTINGS_HOME_TITLE)}\n\n{t(M.SETTINGS_HOME_INTRO)}",
            image=_art(), keyboard=keyboard(*rows),
        )
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)

    # ── Settings: one section ──────────────────────────────────────────────────
    async def _render_section(q: CallbackQuery, section: str) -> None:
        fields = svc.section_fields(section)
        rows = []
        for field, value, kind in fields:
            label = field.replace("_", " ").title()
            if kind == "bool":
                mark = t(M.SETTINGS_ON) if value else t(M.SETTINGS_OFF)
                rows.append([(f"{mark}  {label}", cb("settings", "tog", section, field))])
            else:
                shown = str(value)[:18] if str(value) else "—"
                rows.append([(f"{label}:  {shown}", cb("settings", "edit", section, field))])
        rows.append([(t(M.BTN_BACK), cb("settings", "home"))])
        caption = (
            f"{t(M.SETTINGS_SECTIONS[section])}\n\n{t(M.SETTINGS_SECTION_INTRO)}"
        )
        screen = Screen(caption=caption, image=_art(), keyboard=keyboard(*rows))
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)

    @client.on_callback_query(filters.regex(r"^settings\|sec"))
    async def _section(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        await _render_section(q, q.data.split("|", 2)[2])

    @client.on_callback_query(filters.regex(r"^settings\|tog"))
    async def _toggle(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        _, _, section, field = q.data.split("|", 3)
        new_val = await svc.toggle(section, field)
        state = t(M.SETTINGS_STATE_ON) if new_val else t(M.SETTINGS_STATE_OFF)
        await q.answer(t(M.SETTINGS_TOAST_TOGGLED,
                         field=field.replace("_", " ").title(), state=state))
        await _render_section(q, section)

    @client.on_callback_query(filters.regex(r"^settings\|edit"))
    async def _edit(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.CONFIGURE):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        _, _, section, field = q.data.split("|", 3)
        current = getattr(svc.section(section), field, "")
        await fsm.set(q.from_user.id, STATE_EDIT, section=section, field=field)
        await q.answer()
        await q.message.reply(
            t(M.SETTINGS_EDIT_PROMPT, field=field.replace("_", " ").title(), value=current),
            reply_markup=keyboard([(t(M.BTN_CANCEL), cb("settings", "sec", section))]),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=5)
    async def _edit_input(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_EDIT:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.CONFIGURE)):
            return
        section, field = data.get("section"), data.get("field")
        await fsm.clear(message.from_user.id)
        try:
            value = await svc.set_typed(section, field, message.text)
        except (ValueError, KeyError):
            await message.reply(t(M.SETTINGS_EDIT_BAD), parse_mode=ParseMode.HTML)
            return
        await message.reply(
            t(M.SETTINGS_EDIT_DONE, field=field.replace("_", " ").title(), value=value),
            reply_markup=keyboard([(t(M.BTN_BACK), cb("settings", "sec", section))]),
            parse_mode=ParseMode.HTML,
        )

    # ── Queue view ─────────────────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^queue\|view"))
    async def _queue(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.ui import progress

        await q.answer()
        rows = await QueueService(container).dashboard()
        if not rows:
            screen = Screen(caption=f"{t(M.QUEUE_TITLE)}\n\n{t(M.QUEUE_EMPTY)}",
                            image=_art(),
                            keyboard=keyboard([(t(M.BTN_BACK), cb("admin", "home"))]))
            await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
            return
        blocks = [
            progress.queue_block_html(
                anime_title=r.anime_title, status=r.status, progress=r.progress,
                speed_bps=r.speed_bps, eta_seconds=r.eta_seconds,
                current_episode=r.current_episode, downloaded_bytes=r.downloaded_bytes,
                total_bytes=r.total_bytes, job_id=r.job_id,
            )
            for r in rows
        ]
        screen = Screen(
            caption=f"{t(M.QUEUE_TITLE)}\n\n" + "\n".join(blocks), image=_art(),
            keyboard=keyboard([(t(M.BTN_REFRESH), cb("queue", "view", 0)),
                               (t(M.BTN_BACK), cb("admin", "home"))]),
        )
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)

    # ── Analytics ──────────────────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^admin\|analytics"))
    async def _analytics(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.VIEW_ANALYTICS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.analytics_service import AnalyticsService
        from nekofetch.ui import log_sections as S

        await q.answer()
        s = await AnalyticsService(container).dashboard()
        caption = S.dashboard_section(s, list(s.most_requested), _ts())
        screen = Screen(caption=caption, image=_art(),
                        keyboard=keyboard([(t(M.BTN_BACK), cb("admin", "home"))]))
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)


def _art():
    from nekofetch.ui.artwork import pick_artwork
    return pick_artwork()


def _ts() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).strftime("%H:%M:%S UTC")
