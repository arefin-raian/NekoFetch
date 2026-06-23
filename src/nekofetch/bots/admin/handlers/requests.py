from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.core.parsing import parse_episode_spec
from nekofetch.domain.enums import ContentKind, DownloadScope
from nekofetch.ui import progress
from nekofetch.ui.components import cb, keyboard, paginate, parse_cb
from nekofetch.ui.progress import loading_animation, staged_loading
from nekofetch.ui.typography import bq, bqx

STATE_NAME = "req:await_name"
STATE_EPISODES = "req:await_episodes"


def register(client: Client, container: Container) -> None:
    localizer = container.localizer
    fsm = FSM(container.redis, bot="admin")
    default_source = container.config.sources.default

    def L(key: str, lang: str = "en", **kw) -> str:
        return localizer.get(key, lang, **kw)

    @client.on_callback_query(filters.regex(r"^req\|new"))
    async def _new(_: Client, q: CallbackQuery) -> None:
        await fsm.set(q.from_user.id, STATE_NAME)
        await q.message.edit_text(bq(L("prompt_anime_name")), parse_mode=ParseMode.HTML)
        await q.answer()

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]))
    async def _text(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state == STATE_NAME:
            await _do_search(message, message.text.strip())
        elif state == STATE_EPISODES:
            await _submit_selected(message, data, message.text.strip())

    async def _do_search(message: Message, query: str) -> None:
        msg = await message.reply("<code>sᴇᴀʀᴄʜɪɴɢ!</code>", parse_mode=ParseMode.HTML)
        await staged_loading(msg, ["sᴇᴀʀᴄʜɪɴɢ", "ʀᴇᴛʀɪᴇᴠɪɴɢ ʀᴇsᴜʟᴛs"])
        try:
            source = container.sources.get(default_source)
            results = await source.search(query)
        except NekoFetchError as exc:
            await msg.edit_text(bq(L(exc.message_key)), parse_mode=ParseMode.HTML)
            return

        if not results:
            header = L("search_results_header")
            await msg.edit_text(
                f"{bq(f'<b>{header}</b>')}\n\n"
                f"{bq(f'ɴᴏ ᴍᴀᴛᴄʜᴇs ꜰᴏʀ <code>{query}</code>.')}",
                parse_mode=ParseMode.HTML,
            )
            await fsm.clear(message.from_user.id)
            return

        cache = [{"ref": r.source_ref, "title": r.title} for r in results[:50]]
        await fsm.set(message.from_user.id, "req:results", results=cache)
        await msg.edit_text(
            _results_text(results),
            reply_markup=_results_kb(cache, page=0),
            parse_mode=ParseMode.HTML,
        )

    def _results_text(results) -> str:
        lines = [f"<b>{i + 1}.</b> {r.title}" for i, r in enumerate(results[:8])]
        header = L("search_results_header")
        return (
            f"{bq(f'<b>{header}</b>')}\n\n"
            f"{bqx(chr(10).join(lines))}"
        )

    def _results_kb(cache: list[dict], page: int):
        items = [(f"{i + 1}. {r['title']}", cb("req", "pick", i)) for i, r in enumerate(cache)]
        return paginate(items, page=page, nav_action="req|spage", page_size=8)

    @client.on_callback_query(filters.regex(r"^req\|spage"))
    async def _spage(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        _, data = await fsm.get(q.from_user.id)
        cache = data.get("results", [])
        await q.message.edit_reply_markup(_results_kb(cache, page=int(args[1])))
        await q.answer()

    @client.on_callback_query(filters.regex(r"^req\|pick"))
    async def _pick(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        _, data = await fsm.get(q.from_user.id)
        cache = data.get("results", [])
        idx = int(args[1])
        if idx >= len(cache):
            await q.answer(L("error_generic"), show_alert=True)
            return
        chosen = cache[idx]
        await q.answer()

        msg = q.message
        await loading_animation(msg, "ʟᴏᴀᴅɪɴɢ ᴄᴏɴᴛᴇɴᴛ", steps=3, delay=0.3)

        source = container.sources.get(default_source)
        details = await source.get_details(chosen["ref"])
        await fsm.set(
            q.from_user.id, "req:content",
            ref=chosen["ref"], title=details.title,
            season_count=details.season_count or 1,
        )
        await msg.edit_text(
            _details_text(details), reply_markup=_content_kb(details.season_count or 1),
            parse_mode=ParseMode.HTML,
        )

    def _details_text(d) -> str:
        parts = [f"{bq(f'<b>{d.title}</b>')}"]
        if d.synopsis:
            parts.append(d.synopsis[:400])
        if d.genres:
            parts.append(f"<b>ɢᴇɴʀᴇs:</b> {', '.join(d.genres)}")
        cs = L("content_seasons")
        cm = L("content_movies")
        csp = L("content_specials")
        parts.append(
            f"<b>ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏɴᴛᴇɴᴛ</b>\n"
            f"{bq(f'◆ {cs}: {d.season_count or 1}')}\n"
            f"{bq(f'◆ {cm}')}\n"
            f"{bq(f'◆ {csp}')}"
        )
        return "\n\n".join(parts)

    def _content_kb(season_count: int):
        rows = []
        row = []
        for s in range(1, max(season_count, 1) + 1):
            row.append((f"Season {s}", cb("req", "season", s)))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([(L("content_movies"), cb("req", "kind", "movie")),
                     (L("content_specials"), cb("req", "kind", "special"))])
        return keyboard(*rows)

    @client.on_callback_query(filters.regex(r"^req\|season"))
    async def _season(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        await loading_animation(q.message, "ʀᴇᴛʀɪᴇᴠɪɴɢ sᴇᴀsᴏɴs")
        await fsm.update(q.from_user.id, season=int(args[1]), kind=ContentKind.SEASON.value)
        await q.answer()
        dsh = L("download_scope_header")
        await q.message.edit_text(
            f"{bq(f'<b>{dsh}</b>')}\n\n"
            f"{bq(f'sᴇᴀsᴏɴ {args[1]}')}",
            reply_markup=keyboard(
                [(L("btn_entire_series"), cb("req", "scope", "series"))],
                [(L("btn_selected_episodes"), cb("req", "scope", "eps"))],
            ),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^req\|kind"))
    async def _kind(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        await fsm.update(q.from_user.id, season=None, kind=args[1])
        await q.answer()
        dsh = L("download_scope_header")
        await q.message.edit_text(
            f"{bq(f'<b>{dsh}</b>')}",
            reply_markup=keyboard([(L("btn_entire_series"), cb("req", "scope", "series"))]),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^req\|scope"))
    async def _scope(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        if args[1] == "eps":
            await fsm.set(q.from_user.id, STATE_EPISODES, **(await fsm.get(q.from_user.id))[1])
            await q.message.edit_text(
                bq("ᴇɴᴛᴇʀ ᴇᴘɪsᴏᴅᴇs (ᴇ.ɢ. 1-12, 14, 20)."),
                parse_mode=ParseMode.HTML,
            )
            await q.answer()
            return
        _, data = await fsm.get(q.from_user.id)
        await _finalize(q.message, q.from_user.id, data, scope=DownloadScope.ENTIRE_SERIES)
        await q.answer()

    async def _submit_selected(message: Message, data: dict, spec: str) -> None:
        episodes = parse_episode_spec(spec)
        if not episodes:
            await message.reply(
                bq("ᴄᴏᴜʟᴅɴ'ᴛ ᴘᴀʀsᴇ ᴛʜᴀᴛ. ᴛʀʏ ᴇ.ɢ. 1-12, 14."),
                parse_mode=ParseMode.HTML,
            )
            return
        data = {**data, "episodes": episodes}
        msg = await message.reply("<code>sᴜʙᴍɪᴛᴛɪɴɢ ʀᴇǫᴜᴇsᴛ!</code>", parse_mode=ParseMode.HTML)
        await loading_animation(msg, "sᴜʙᴍɪᴛᴛɪɴɢ ʀᴇǫᴜᴇsᴛ")
        await _finalize(msg, message.from_user.id, data, scope=DownloadScope.SELECTED_EPISODES)

    async def _finalize(message, user_id: int, data: dict, *, scope: DownloadScope) -> None:
        from nekofetch.services.request_service import RequestService
        from nekofetch.services.queue_service import QueueService

        await asyncio.sleep(0)
        try:
            receipt = await RequestService(container).submit(
                telegram_id=user_id,
                source=default_source,
                source_ref=data["ref"],
                anime_title=data["title"],
                scope=scope,
                season=data.get("season"),
                episodes=data.get("episodes"),
            )
        except NekoFetchError as exc:
            await message.edit_text(bq(L(exc.message_key)), parse_mode=ParseMode.HTML)
            return
        await fsm.clear(user_id)

        is_admin = user_id in container.env.admin_ids
        if is_admin:
            try:
                await QueueService(container).enqueue(receipt.code)
            except NekoFetchError:
                pass

        ep = L("request_eta_pending")
        await message.edit_text(
            f"{bq('<b>✅ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛᴇᴅ</b>')}\n\n"
            f"{bqx(f'<b>ʀᴇǫᴜᴇsᴛ ɪᴅ:</b> <code>#{receipt.code}</code>\n'
                   f'<b>ᴘᴏsɪᴛɪᴏɴ:</b> <code>{receipt.position}</code>\n'
                   f'<b>ᴇᴛᴀ:</b> <code>{ep}</code>')}",
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^req\|mine"))
    async def _mine(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.request_service import RequestService

        await loading_animation(q.message, "ʟᴏᴀᴅɪɴɢ ʀᴇǫᴜᴇsᴛs")
        rows = await RequestService(container).list_for_user(q.from_user.id)
        await q.answer()
        if not rows:
            await q.message.edit_text(
                bq("ʏᴏᴜ ʜᴀᴠᴇ ɴᴏ ʀᴇǫᴜᴇsᴛs ʏᴇᴛ."),
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [
            f"<b>#{r.code}</b> ◆ {r.anime_title} — <code>{r.status}</code>" for r in rows[:10]
        ]
        bmr = L("btn_my_requests")
        await q.message.edit_text(
            f"{bq(f'<b>{bmr}</b>')}\n\n{bqx(chr(10).join(lines))}",
            parse_mode=ParseMode.HTML,
        )
