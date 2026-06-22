"""Distribution-bot generation (admin).

    Admin Panel -> Bots -> Add Bot -> paste BotFather token -> registered & live

The token is validated, encrypted, stored, and the bot is brought online immediately.
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
from nekofetch.ui.components import cb, keyboard

STATE_TOKEN = "bot:await_token"
STATE_BIND = "bot:await_bind"


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(q: CallbackQuery) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, Permission.GENERATE_BOTS))

    @client.on_callback_query(filters.regex(r"^admin\|bots"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        from nekofetch.services.bot_management_service import BotManagementService

        await q.answer()
        bots = await BotManagementService(container).list_bots()
        rows = []
        if bots:
            lines = []
            for b in bots:
                handle = f" (@{b.username})" if b.username else ""
                glyph = DIAMOND_FILLED if b.enabled else DIAMOND_HOLLOW
                lines.append(f"{glyph} {b.name}{handle}")
                rows.append([(f"Bind title — {b.name[:18]}", cb("botmgr", "bind", b.id))])
            body = "\n".join(lines)
        else:
            body = "No distribution bots yet."
        # Titles with content but no bot yet (provide a token + bind to launch them).
        pending = await BotManagementService(container).pending_bot_animes()
        if pending:
            body += "\n\n**Awaiting a bot:**\n" + "\n".join(
                f"{DIAMOND_HOLLOW} {title}  (`{doc}`)" for doc, title in pending[:15]
            )
        rows.append([("➜ Add Bot", cb("botmgr", "add"))])
        rows.append([("◂ Back", cb("admin", "home"))])
        await q.message.edit_text(
            f"**▸ Distribution Bots**\n\n{body}", reply_markup=keyboard(*rows)
        )

    @client.on_callback_query(filters.regex(r"^botmgr\|bind"))
    async def _bind(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        bot_id = int(q.data.split("|", 2)[2])
        await fsm.set(q.from_user.id, STATE_BIND, bot_id=bot_id)
        await q.answer()
        await q.message.edit_text(
            "**Bind Title**\n\nSend the anime reference (slug/id) to bind this bot to, "
            "or send `-` to unbind. A bound bot opens directly on that title."
        )

    @client.on_callback_query(filters.regex(r"^botmgr\|add"))
    async def _add(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_TOKEN)
        await q.answer()
        await q.message.edit_text(
            "**Add Distribution Bot**\n\n"
            "1. Create a bot with @BotFather.\n"
            "2. Paste its token here.\n\n"
            "The token is encrypted at rest and the bot goes live immediately."
        )

    # Separate group so this coexists with the request-flow text handler.
    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=1)
    async def _token(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        user = getattr(message, "nf_user", None)
        if state not in (STATE_TOKEN, STATE_BIND):
            return
        if not (user and auth.has_permission(user, Permission.GENERATE_BOTS)):
            return

        if state == STATE_BIND:
            await fsm.clear(message.from_user.id)
            from nekofetch.services.bot_management_service import BotManagementService

            ref = message.text.strip()
            anime_doc_id = None if ref == "-" else ref
            await BotManagementService(container).bind_title(int(data["bot_id"]), anime_doc_id)
            await message.reply(
                f"{DIAMOND_FILLED} Bot {'unbound' if anime_doc_id is None else f'bound to `{anime_doc_id}`'}."
            )
            return

        token = message.text.strip()
        await fsm.clear(message.from_user.id)
        from nekofetch.services.bot_management_service import BotManagementService

        status = await message.reply("Validating token…")
        try:
            info = await BotManagementService(container).register(token)
        except NekoFetchError as exc:
            await status.edit_text(f"{DIAMOND_HOLLOW} {exc.detail or 'Registration failed.'}")
            return
        await status.edit_text(
            f"{DIAMOND_FILLED} **Bot registered & live**\n\n"
            f"Name: {info.name}\n"
            f"Username: @{info.username}" if info.username else f"Name: {info.name}"
        )
        # Avoid the token lingering in chat history.
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
