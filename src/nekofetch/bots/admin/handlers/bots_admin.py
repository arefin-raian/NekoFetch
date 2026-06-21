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
        if bots:
            lines = "\n".join(
                f"{DIAMOND_FILLED if b.enabled else DIAMOND_HOLLOW} {b.name}"
                f" (@{b.username})" if b.username else f" {b.name}"
                for b in bots
            )
        else:
            lines = "No distribution bots yet."
        await q.message.edit_text(
            f"**▸ Distribution Bots**\n\n{lines}",
            reply_markup=keyboard(
                [("➜ Add Bot", cb("botmgr", "add"))],
                [("◂ Back", cb("admin", "home"))],
            ),
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
    @client.on_message(filters.text & ~filters.command(["start"]), group=1)
    async def _token(_: Client, message: Message) -> None:
        state, _ = await fsm.get(message.from_user.id)
        if state != STATE_TOKEN:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.GENERATE_BOTS)):
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
