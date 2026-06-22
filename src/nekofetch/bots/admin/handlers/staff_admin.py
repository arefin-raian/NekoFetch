"""Staff & user management panel.

    Admin Panel -> Staff -> list team / Add Staff / Remove (per member) / Ban toggle

Add Staff prompts for a numeric Telegram user id. Promote/demote require MANAGE_STAFF;
ban/approve require APPROVE_USERS.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED, DIAMOND_HOLLOW
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.services.staff_service import StaffService
from nekofetch.ui.components import cb, keyboard

STATE_ADD = "staff:await_id"


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _can(obj, perm: Permission) -> bool:
        user = getattr(obj, "nf_user", None)
        return bool(user and auth.has_permission(user, perm))

    @client.on_callback_query(filters.regex(r"^admin\|staff"))
    async def _panel(_: Client, q: CallbackQuery) -> None:
        if not _can(q, Permission.MANAGE_STAFF):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await q.answer()
        await _render(q)

    async def _render(q: CallbackQuery) -> None:
        team = await StaffService(container).list_team()
        rows = []
        if team:
            lines = []
            for m in team:
                glyph = DIAMOND_HOLLOW if m.banned else DIAMOND_FILLED
                lines.append(f"{glyph} {m.name} — {m.role}" + ("  (banned)" if m.banned else ""))
                if m.role != "admin":
                    rows.append([
                        (f"Remove {m.name[:14]}", cb("staff", "rm", m.telegram_id)),
                        ("Unban" if m.banned else "Ban", cb("staff", "ban", m.telegram_id, 0 if m.banned else 1)),
                    ])
            body = "\n".join(lines)
        else:
            body = "No staff yet."
        rows.append([("➜ Add Staff", cb("staff", "add"))])
        rows.append([("◂ Back", cb("admin", "home"))])
        await q.message.edit_text(f"**▸ Staff & Users**\n\n{body}", reply_markup=keyboard(*rows))

    @client.on_callback_query(filters.regex(r"^staff\|add"))
    async def _add(_: Client, q: CallbackQuery) -> None:
        if not _can(q, Permission.MANAGE_STAFF):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_ADD)
        await q.answer()
        await q.message.edit_text(
            "**Add Staff**\n\nSend the Telegram **user id** to promote to staff.\n"
            "(The user can get their id from @userinfobot.)"
        )

    @client.on_callback_query(filters.regex(r"^staff\|rm"))
    async def _remove(_: Client, q: CallbackQuery) -> None:
        if not _can(q, Permission.MANAGE_STAFF):
            await q.answer(L("access_denied"), show_alert=True)
            return
        target = int(q.data.split("|")[2])
        try:
            await StaffService(container).remove_staff(q.from_user.id, target)
            await q.answer("Demoted to user")
        except NekoFetchError as exc:
            await q.answer(exc.detail or L("error_generic"), show_alert=True)
            return
        await _render(q)

    @client.on_callback_query(filters.regex(r"^staff\|ban"))
    async def _ban(_: Client, q: CallbackQuery) -> None:
        if not _can(q, Permission.APPROVE_USERS):
            await q.answer(L("access_denied"), show_alert=True)
            return
        parts = q.data.split("|")
        target, banned = int(parts[2]), bool(int(parts[3]))
        try:
            await StaffService(container).set_banned(q.from_user.id, target, banned)
            await q.answer("Banned" if banned else "Unbanned")
        except NekoFetchError as exc:
            await q.answer(exc.detail or L("error_generic"), show_alert=True)
            return
        await _render(q)

    # Group 6 so it coexists with the other stateful text handlers.
    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=6)
    async def _add_input(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_ADD or not _can(message, Permission.MANAGE_STAFF):
            return
        await fsm.clear(message.from_user.id)
        raw = message.text.strip()
        if not raw.lstrip("-").isdigit():
            await message.reply("That doesn't look like a numeric user id.")
            return
        try:
            await StaffService(container).add_staff(message.from_user.id, int(raw))
        except NekoFetchError as exc:
            await message.reply(exc.detail or L("error_generic"))
            return
        await message.reply(f"{DIAMOND_FILLED} User `{raw}` promoted to staff.")
