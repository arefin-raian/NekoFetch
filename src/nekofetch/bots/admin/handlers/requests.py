"""Anime request flow (public users).

    Request Anime -> "Enter anime name." -> results -> content -> season -> scope -> submit

State is kept in the Redis FSM so the flow survives restarts. Search results are cached
in the FSM data bag and referenced by index to keep callback data within Telegram's
64-byte limit.
"""

from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.core.parsing import parse_episode_spec
from nekofetch.domain.enums import ContentKind, DownloadScope
from nekofetch.ui import progress
from nekofetch.ui.components import cb, keyboard, paginate, parse_cb, section

STATE_NAME = "req:await_name"
STATE_EPISODES = "req:await_episodes"


def register(client: Client, container: Container) -> None:
    localizer = container.localizer
    fsm = FSM(container.redis, bot="admin")
    default_source = container.config.sources.default

    def L(key: str, lang: str = "en", **kw) -> str:
        return localizer.get(key, lang, **kw)

    # ── entry: "Request Anime" ──
    @client.on_callback_query(filters.regex(r"^req\|new"))
    async def _new(_: Client, q: CallbackQuery) -> None:
        await fsm.set(q.from_user.id, STATE_NAME)
        await q.message.edit_text(L("prompt_anime_name"))
        await q.answer()

    # ── text router for FSM states (non-command text) ──
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
        msg = await message.reply(progress.labeled(L("status_searching"), 20))
        try:
            source = container.sources.get(default_source)
            await msg.edit_text(progress.labeled(L("status_searching_db"), 60))
            results = await source.search(query)
        except NekoFetchError as exc:
            await msg.edit_text(L(exc.message_key))
            return

        if not results:
            await msg.edit_text(f"{L('search_results_header')}\n\nNo matches for “{query}”.")
            await fsm.clear(message.from_user.id)
            return

        cache = [{"ref": r.source_ref, "title": r.title} for r in results[:50]]
        await fsm.set(message.from_user.id, "req:results", results=cache)
        await msg.edit_text(
            _results_text(results),
            reply_markup=_results_kb(cache, page=0),
        )

    def _results_text(results) -> str:
        lines = [f"{i + 1}. {r.title}" for i, r in enumerate(results[:8])]
        return f"**{L('search_results_header')}**\n\n" + "\n".join(lines)

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

    # ── pick a title -> show available content ──
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

        source = container.sources.get(default_source)
        details = await source.get_details(chosen["ref"])
        await fsm.set(
            q.from_user.id, "req:content",
            ref=chosen["ref"], title=details.title,
            season_count=details.season_count or 1,
        )
        await q.message.edit_text(
            _details_text(details), reply_markup=_content_kb(details.season_count or 1)
        )

    def _details_text(d) -> str:
        parts = [f"**{d.title}**"]
        if d.synopsis:
            parts.append(d.synopsis[:400])
        if d.genres:
            parts.append(f"{section('Genres')}  " + ", ".join(d.genres))
        parts.append(
            f"{section('Available Content')}\n"
            f"{DIAMOND_FILLED} {L('content_seasons')}: {d.season_count or 1}\n"
            f"{DIAMOND_FILLED} {L('content_movies')}\n"
            f"{DIAMOND_FILLED} {L('content_specials')}"
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

    # ── choose a season -> download scope ──
    @client.on_callback_query(filters.regex(r"^req\|season"))
    async def _season(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        await fsm.update(q.from_user.id, season=int(args[1]), kind=ContentKind.SEASON.value)
        await q.answer()
        await q.message.edit_text(
            f"**{L('download_scope_header')}**\n\nSeason {args[1]}",
            reply_markup=keyboard(
                [(L("btn_entire_series"), cb("req", "scope", "series"))],
                [(L("btn_selected_episodes"), cb("req", "scope", "eps"))],
            ),
        )

    @client.on_callback_query(filters.regex(r"^req\|kind"))
    async def _kind(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        await fsm.update(q.from_user.id, season=None, kind=args[1])
        await q.answer()
        await q.message.edit_text(
            f"**{L('download_scope_header')}**",
            reply_markup=keyboard([(L("btn_entire_series"), cb("req", "scope", "series"))]),
        )

    # ── scope -> submit ──
    @client.on_callback_query(filters.regex(r"^req\|scope"))
    async def _scope(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        if args[1] == "eps":
            await fsm.set(q.from_user.id, STATE_EPISODES, **(await fsm.get(q.from_user.id))[1])
            await q.message.edit_text("Enter episodes (e.g. 1-12, 14, 20).")
            await q.answer()
            return
        _, data = await fsm.get(q.from_user.id)
        await _finalize(q.message, q.from_user.id, data, scope=DownloadScope.ENTIRE_SERIES)
        await q.answer()

    async def _submit_selected(message: Message, data: dict, spec: str) -> None:
        episodes = parse_episode_spec(spec)
        if not episodes:
            await message.reply("Couldn't parse that. Try e.g. 1-12, 14.")
            return
        data = {**data, "episodes": episodes}
        await _finalize(message, message.from_user.id, data, scope=DownloadScope.SELECTED_EPISODES)

    async def _finalize(message, user_id: int, data: dict, *, scope: DownloadScope) -> None:
        from nekofetch.services.request_service import RequestService
        from nekofetch.services.queue_service import QueueService

        await asyncio.sleep(0)  # yield
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
            await message.reply(L(exc.message_key))
            return
        await fsm.clear(user_id)

        # Admins bypass the review step — enqueue immediately.
        is_admin = user_id in container.env.admin_ids
        if is_admin:
            try:
                await QueueService(container).enqueue(receipt.code)
            except NekoFetchError:
                pass

        await message.reply(
            f"**{L('request_accepted_title')}**\n\n"
            f"{L('request_id_label')}:\n#{receipt.code}\n\n"
            f"{L('request_position_label')}:\n{receipt.position}\n\n"
            f"{L('request_eta_label')}:\n{L('request_eta_pending')}"
        )

    # ── My Requests ──
    @client.on_callback_query(filters.regex(r"^req\|mine"))
    async def _mine(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.request_service import RequestService

        rows = await RequestService(container).list_for_user(q.from_user.id)
        await q.answer()
        if not rows:
            await q.message.edit_text("You have no requests yet.")
            return
        lines = [
            f"#{r.code} {DIAMOND_FILLED} {r.anime_title} — {r.status}" for r in rows[:10]
        ]
        await q.message.edit_text("**" + L("btn_my_requests") + "**\n\n" + "\n".join(lines))
