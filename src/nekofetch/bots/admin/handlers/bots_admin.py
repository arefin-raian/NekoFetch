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
STATE_CREATE_ANIME = "bot:await_anime_ref"


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
                rrow = [(L(M.BOTS_BTN_BIND, name=b.name[:18]), cb("botmgr", "bind", b.id))]
                # Add recreate button for each bot.
                rrow.append((L(M.BOTS_BTN_RECREATE, name=b.name[:14]), cb("botmgr", "recreate", b.id)))
                rows.append(rrow)
            body = "\n".join(lines)
        else:
            body = L(M.BOTS_EMPTY)
        pending = await svc.pending_bot_animes()
        if pending:
            body += "\n\n" + L(M.BOTS_PENDING_HEADER) + "\n" + "\n".join(
                L(M.BOTS_PENDING_ROW, title=title, doc=doc) for doc, title in pending[:15]
            )
        rows.append([(L(M.BOTS_BTN_CREATE), cb("botmgr", "create"))])
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

    @client.on_callback_query(filters.regex(r"^botmgr\|recreate"))
    async def _recreate(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        bot_id = int(q.data.split("|", 2)[2])
        await q.answer()
        # Look up the anime_doc_id for this bot.
        from nekofetch.infrastructure.database.postgres.models import DistributionBot
        from nekofetch.infrastructure.database.postgres.session import session_scope
        from sqlalchemy import select
        async with session_scope(container.pg_sessionmaker) as session:
            bot = await session.get(DistributionBot, bot_id)
        if bot is None or not bot.anime_doc_id:
            await q.message.reply("⚠️ Bot not found or has no bound title.")
            return
        status = await q.message.reply("♻️ <b>Recreating bot…</b>", parse_mode=ParseMode.HTML)
        from nekofetch.services.bot_orchestrator import BotOrchestratorService
        try:
            info = await BotOrchestratorService(container).recreate_bot(bot.anime_doc_id)
            if info:
                await status.edit_text(
                    f"✅ <b>Bot recreated</b>\n\n"
                    f"<b>Name:</b> {info.name}\n"
                    f"<b>Username:</b> @{info.username}",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await status.edit_text("⚠️ Bot recreation failed — check the logs.")
        except NekoFetchError as exc:
            await status.edit_text(
                f"⚠️ {exc.detail or 'Failed to recreate bot'}",
                parse_mode=ParseMode.HTML,
            )

    @client.on_callback_query(filters.regex(r"^botmgr\|create"))
    async def _create(_: Client, q: CallbackQuery) -> None:
        """Manual bot creation — ask for an anime_ref."""
        if not _allowed(q):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await fsm.set(q.from_user.id, STATE_CREATE_ANIME)
        await q.answer()
        kb = keyboard([(L(M.BTN_BACK), cb("admin", "bots"))])
        prompt = "➕ <b>Create Bot For Anime</b>\n\nSend the anime_doc_id or slug to create a bot for."
        await show(client, q.message, prompt, kb)

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
        if state not in (STATE_TOKEN, STATE_BIND, STATE_CREATE_ANIME):
            return
        if not (user and auth.is_owner(user)
                and auth.has_permission(user, Permission.GENERATE_BOTS)):
            return

        if state == STATE_CREATE_ANIME:
            await fsm.clear(message.from_user.id)
            anime_ref = message.text.strip()
            status = await message.reply(
                "🔄 <b>Creating bot for {anime}…</b>".replace("{anime}", anime_ref[:40]),
                parse_mode=ParseMode.HTML,
            )
            from nekofetch.services.bot_orchestrator import BotOrchestratorService
            try:
                info = await BotOrchestratorService(container).ensure_bot_for_anime(anime_ref)
                if info:
                    await status.edit_text(
                        f"✅ <b>Bot created</b>\n\n"
                        f"<b>Name:</b> {info.name}\n"
                        f"<b>Username:</b> @{info.username}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await status.edit_text(
                        "⚠️ Bot creation failed — distribution_bots may be disabled.",
                    )
            except NekoFetchError as exc:
                await status.edit_text(
                    f"⚠️ {exc.detail or 'Failed to create bot'}",
                    parse_mode=ParseMode.HTML,
                )
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
