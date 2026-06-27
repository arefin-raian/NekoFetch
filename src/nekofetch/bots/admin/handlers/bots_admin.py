from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED, DIAMOND_HOLLOW
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.typography import bq, bqx

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

        await loading_animation(q.message, "loading bots")
        await q.answer()
        bots = await BotManagementService(container).list_bots()
        rows = []
        if bots:
            lines = []
            for b in bots:
                handle = f" (@{b.username})" if b.username else ""
                glyph = DIAMOND_FILLED if b.enabled else DIAMOND_HOLLOW
                lines.append(f"{glyph} {b.name}{handle}")
                rows.append([(f"bind title — {b.name[:18]}", cb("botmgr", "bind", b.id))])
            body = "\n".join(lines)
        else:
            body = "no distribution bots yet."
        pending = await BotManagementService(container).pending_bot_animes()
        if pending:
            body += "\n\n<b>awaiting a bot:</b>\n" + "\n".join(
                f"{DIAMOND_HOLLOW} {title}  (<code>{doc}</code>)" for doc, title in pending[:15]
            )
        rows.append([("➜ add bot", cb("botmgr", "add"))])
        rows.append([("← back", cb("admin", "home"))])
        await q.message.edit_text(
            f"{bq('<b>▸ distribution bots</b>')}\n\n{bq(body)}",
            reply_markup=keyboard(*rows),
            parse_mode=ParseMode.HTML,
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
            bq("<b>bind title</b>\n\n"
               "send the anime reference (slug/id) to bind this bot to, "
               "or send <code>-</code> to unbind. a bound bot opens directly on that title."),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^botmgr\|add"))
    async def _add(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L("access_denied"), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_TOKEN)
        await q.answer()
        await q.message.edit_text(
            bq("<b>add distribution bot</b>\n\n"
               "1. create a bot with @botfather.\n"
               "2. paste its token here.\n\n"
               "the token is encrypted at rest and the bot goes live immediately."),
            parse_mode=ParseMode.HTML,
        )

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
                bq(f"{DIAMOND_FILLED} bot {'unbound' if anime_doc_id is None else f'bound to <code>{anime_doc_id}</code>'}"),
                parse_mode=ParseMode.HTML,
            )
            return

        token = message.text.strip()
        await fsm.clear(message.from_user.id)
        from nekofetch.services.bot_management_service import BotManagementService

        status = await message.reply(
            "<b>validating token!</b>", parse_mode=ParseMode.HTML
        )
        await loading_animation(status, "validating token")
        try:
            info = await BotManagementService(container).register(token)
        except NekoFetchError as exc:
            await status.edit_text(
                bq(f"{DIAMOND_HOLLOW} {exc.detail or 'registration failed.'}"),
                parse_mode=ParseMode.HTML,
            )
            return
        if info.username:
            detail = f"<b>name:</b> {info.name}\n<b>username:</b> @{info.username}"
        else:
            detail = f"<b>name:</b> {info.name}"
        await status.edit_text(
            f"{bq(f'{DIAMOND_FILLED} <b>bot registered & live</b>')}\n\n"
            f"{bq(detail)}",
            parse_mode=ParseMode.HTML,
        )
        try:
            await message.delete()
        except Exception:
            pass
