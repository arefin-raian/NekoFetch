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
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.progress import loading_animation
from nekofetch.ui.screens import show

STATE_TOKEN = "bot:await_token"
STATE_BIND = "bot:await_bind"


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(q: CallbackQuery) -> bool:
        # Distribution bot tokens are sensitive — owner-only.
        user = getattr(q, "nf_user", None)
        return bool(user and auth.is_owner(user)
                    and auth.has_permission(user, Permission.GENERATE_BOTS))

    @client.on_callback_query(filters.regex(r"^admin\|bots"))
    async def _list(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.bot_management_service import BotManagementService

        await q.answer()
        svc = BotManagementService(container)
        bots = await svc.list_bots()
        rows = []
        if bots:
            lines = []
            for b in bots:
                handle = f" (@{b.username})" if b.username else ""
                dot = L(M.BOTS_DOT_ACTIVE) if b.enabled else L(M.BOTS_DOT_DISABLED)
                lines.append(L(M.BOTS_ROW, dot=dot, name=b.name, handle=handle))
                rows.append([(L(M.BOTS_BTN_BIND, name=b.name[:18]), cb("botmgr", "bind", b.id))])
            body = "\n".join(lines)
        else:
            body = L(M.BOTS_EMPTY)
        pending = await svc.pending_bot_animes()
        if pending:
            body += "\n\n" + L(M.BOTS_PENDING_HEADER) + "\n" + "\n".join(
                L(M.BOTS_PENDING_ROW, title=title, doc=doc) for doc, title in pending[:15]
            )
        rows.append([(L(M.BOTS_BTN_ADD), cb("botmgr", "add"))])
        rows.append([(L(M.BTN_BACK), cb("admin", "home"))])
        await show(client, q.message, f"{L(M.BOTS_TITLE)}\n\n{body}", keyboard(*rows))

    @client.on_callback_query(filters.regex(r"^botmgr\|bind"))
    async def _bind(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        bot_id = int(q.data.split("|", 2)[2])
        await fsm.set(q.from_user.id, STATE_BIND, bot_id=bot_id)
        await q.answer()
        kb = keyboard([(L(M.BTN_BACK), cb("admin", "bots"))])
        await show(client, q.message, L(M.BOTS_BIND_PROMPT), kb)

    @client.on_callback_query(filters.regex(r"^botmgr\|add"))
    async def _add(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_TOKEN)
        await q.answer()
        kb = keyboard([(L(M.BTN_BACK), cb("admin", "bots"))])
        await show(client, q.message, L(M.BOTS_ADD_PROMPT), kb)

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=1)
    async def _token(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        user = getattr(message, "nf_user", None)
        if state not in (STATE_TOKEN, STATE_BIND):
            return
        if not (user and auth.is_owner(user)
                and auth.has_permission(user, Permission.GENERATE_BOTS)):
            return

        if state == STATE_BIND:
            await fsm.clear(message.from_user.id)
            from nekofetch.services.bot_management_service import BotManagementService

            ref = message.text.strip()
            anime_doc_id = None if ref == "-" else ref
            await BotManagementService(container).bind_title(int(data["bot_id"]), anime_doc_id)
            msg = L(M.BOTS_UNBOUND) if anime_doc_id is None else L(M.BOTS_BOUND, ref=anime_doc_id)
            await message.reply(msg, parse_mode=ParseMode.HTML)
            return

        token = message.text.strip()
        await fsm.clear(message.from_user.id)
        from nekofetch.services.bot_management_service import BotManagementService

        status = await message.reply(L(M.BOTS_VALIDATING), parse_mode=ParseMode.HTML)
        await loading_animation(status, L(M.BOTS_VALIDATING))
        try:
            info = await BotManagementService(container).register(token)
        except NekoFetchError as exc:
            await status.edit_text(
                L(M.BOTS_REGISTER_FAILED, reason=exc.detail or L(M.ERR_GENERIC)),
                parse_mode=ParseMode.HTML,
            )
            return
        if info.username:
            detail = L(M.BOTS_DETAIL_NAMED, name=info.name, username=info.username)
        else:
            detail = L(M.BOTS_DETAIL_NAME, name=info.name)
        await status.edit_text(L(M.BOTS_REGISTERED, detail=detail), parse_mode=ParseMode.HTML)
        try:
            await message.delete()
        except Exception:
            pass
