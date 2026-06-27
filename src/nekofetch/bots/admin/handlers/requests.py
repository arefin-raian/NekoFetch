"""Phase 1 request flow — AniList-first discovery, franchise confirmation.

Source plugins must never perform discovery searches. Searching occurs
exclusively through AniList, with TMDB as a fallback for backdrops.

Workflow:
  1. User submits an anime name.
  2. Query AniList first — get full metadata + relation graph.
  3. If multiple adaptations exist (Hellsing vs Ultimate), present version picker.
  4. Otherwise show a rich confirmation card with franchise breakdown.
  5. On confirm → register a franchise-level request, forward to admin/log.
  6. TMDB fallback: search TV entries only when AniList finds nothing.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import DownloadScope
from nekofetch.localization.messages import M, t
from nekofetch.ui.screens import (
    Screen,
    ask_title,
    choose_version,
    confirm_franchise,
    request_received,
    retry_title,
    send_screen,
)

STATE_NAME = "req:await_name"
STATE_FRANCHISE = "req:franchise"


def register(client: Client, container: Container) -> None:
    fsm = FSM(container.redis, bot="admin")

    @client.on_callback_query(filters.regex(r"^req\|new"))
    async def _new(_: Client, q: CallbackQuery) -> None:
        await fsm.set(q.from_user.id, STATE_NAME)
        screen = ask_title()
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
        await q.answer()

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]))
    async def _text(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, _data = await fsm.get(message.from_user.id)
        # In either state a typed message is a (new) title to look up — while a
        # confirmation card is shown, typing means "actually, search this instead".
        if state in (STATE_NAME, STATE_FRANCHISE):
            await _search_anilist(message, message.text.strip())

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 1 search — AniList only, no source plugin search
    # ──────────────────────────────────────────────────────────────────────────
    async def _search_anilist(message: Message, query: str) -> None:
        msg = await message.reply(t(M.CONFIRM_ANILIST_SEARCH), parse_mode=ParseMode.HTML)

        # --- 1. Query AniList ---
        media = await container.anilist.search(query)
        if media is None:
            # Fallback: try TMDB (TV preferred, then movie)
            await msg.edit_text(t(M.CONFIRM_TMDB_FALLBACK), parse_mode=ParseMode.HTML)
            tmdb_result = await container.tmdb.search(query)
            if tmdb_result is None:
                await msg.edit_text(t(M.SEARCH_ANILIST_NOT_FOUND), parse_mode=ParseMode.HTML)
                return

            # TMDB fallback: build a minimal franchise info
            franchise_data = {
                "title": tmdb_result.title,
                "year": tmdb_result.year,
                "format": tmdb_result.media_type.upper(),
                "status": None,
                "score": tmdb_result.rating,
                "studio": None,
                "genres": tmdb_result.genres,
                "synopsis": tmdb_result.overview,
                "franchise_episodes": tmdb_result.episodes,
                "franchise_seasons": tmdb_result.seasons or 1,
            "franchise_movies": 0,
            "franchise_ovas": 0,
            "franchise_onas": 0,
            "franchise_specials": 0,
            "relations": [],
            "anilist_id": str(tmdb_result.id),
                "anilist_url": None,
                "cover_url": tmdb_result.poster_url,
                "banner_url": tmdb_result.backdrop_url,
                "_source": "tmdb",
                "_query": query,
            }
            await fsm.set(
                message.from_user.id, STATE_FRANCHISE,
                franchise=franchise_data,
            )
            screen = confirm_franchise(franchise_data)
            msg = await send_screen(client, message.chat.id, screen, old_msg=msg)
            return

        # --- 2. Detect adaptations via SeriesResolver ---
        resolution = await container.series_resolver.resolve(query)
        franchise_data = _media_to_franchise_dict(media)

        if resolution.multiple:
            # Show version picker — use 'id' key for choose_version compat
            versions = [
                {
                    "title": e.title,
                    "id": str(e.anilist_id or media.id),
                    "anilist_id": str(e.anilist_id or media.id),
                    "format": e.format,
                    "year": None,
                    "episodes": None,
                    "aliases": e.aliases,
                }
                for e in resolution.entries
            ]
            await fsm.set(
                message.from_user.id, "req:versions",
                versions=versions, query=query, franchise=franchise_data,
            )
            screen = choose_version(query, versions)
            msg = await send_screen(client, message.chat.id, screen, old_msg=msg)
            return

        # --- 3. Single match — fetch TMDB for synopsis + backdrop ---
        # TMDB synopsis is preferred (better franchise-level overview) over AniList's.
        backdrop_path = None
        try:
            tmdb_match = await container.tmdb.search(media.titles[0] if media.titles else query)
            if tmdb_match:
                backdrop_path = tmdb_match.backdrop_url
                if tmdb_match.overview:
                    franchise_data["synopsis"] = tmdb_match.overview
        except Exception:
            pass

        franchise_data["_backdrop_url"] = backdrop_path

        await fsm.set(
            message.from_user.id, STATE_FRANCHISE,
            franchise=franchise_data, query=query,
        )
        screen = confirm_franchise(franchise_data, backdrop_path=backdrop_path)
        msg = await send_screen(client, message.chat.id, screen, old_msg=msg)

    # ──────────────────────────────────────────────────────────────────────────
    # Version picker callbacks
    # ──────────────────────────────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^ver_pick\|"))
    async def _ver_pick(_: Client, q: CallbackQuery) -> None:
        _, args = q.data.split("|", 1)
        picked_id = args
        _, data = await fsm.get(q.from_user.id)
        versions = data.get("versions", [])
        query = data.get("query", "Anime")

        # Find the picked version by id
        chosen = next(
            (v for v in versions if str(v.get("id")) == picked_id),
            versions[0],
        )
        chosen_anilist_id = chosen.get("anilist_id") or chosen.get("id")

        # Refetch full media data for the chosen version using _fetch_full
        try:
            refetched = await container.anilist._fetch_full(int(chosen_anilist_id))
        except (ValueError, TypeError):
            refetched = None

        if refetched:
            franchise_data = _media_to_franchise_dict(refetched)
        else:
            # Fallback: build minimal franchise data from what we have
            franchise_data = {
                "title": chosen.get("title", query),
                "year": None,
                "format": chosen.get("format"),
                "status": None,
                "score": None,
                "studio": None,
                "genres": [],
                "synopsis": None,
                "franchise_episodes": None,
                "franchise_seasons": 1,
                "franchise_movies": 0,
                "franchise_ovas": 0,
                "franchise_onas": 0,
                "franchise_specials": 0,
                "relations": [],
                "anilist_id": chosen_anilist_id,
                "anilist_url": None,
                "cover_url": None,
                "banner_url": None,
                "_source": "anilist",
            }

        franchise_data["title"] = chosen.get("title", franchise_data.get("title", query))

        await fsm.set(
            q.from_user.id, STATE_FRANCHISE,
            franchise=franchise_data, query=query,
        )
        screen = confirm_franchise(franchise_data)
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
        await q.answer()

    # ──────────────────────────────────────────────────────────────────────────
    # Confirmation / rejection
    # ──────────────────────────────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^series_yes\|"))
    async def _confirm(_: Client, q: CallbackQuery) -> None:
        _, data = await fsm.get(q.from_user.id)
        franchise_data = data.get("franchise", {})
        query = data.get("query", franchise_data.get("title", "Anime"))
        name = q.from_user.first_name if q.from_user else ""
        await q.answer()
        await _finalize(q.message, q.from_user.id, name, franchise_data, query=query)

    @client.on_callback_query(filters.regex(r"^series_no$"))
    async def _reject(_: Client, q: CallbackQuery) -> None:
        await fsm.set(q.from_user.id, STATE_NAME)
        screen = retry_title()
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
        await q.answer()

    # ──────────────────────────────────────────────────────────────────────────
    # Finalize — submit the franchise request
    # ──────────────────────────────────────────────────────────────────────────
    async def _finalize(
        card_msg: Message,
        user_id: int,
        user_name: str,
        franchise_data: dict,
        *,
        query: str,
    ) -> None:
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        title = franchise_data.get("title", query)
        anilist_id = franchise_data.get("anilist_id")
        source = franchise_data.get("_source", "anilist")

        # Build franchise_data JSON for the request record
        franchise_json = {
            "anilist_id": anilist_id,
            "source": source,
            "query": query,
            "title": title,
            "year": franchise_data.get("year"),
            "format": franchise_data.get("format"),
            "franchise_episodes": franchise_data.get("franchise_episodes"),
            "franchise_seasons": franchise_data.get("franchise_seasons"),
            "franchise_movies": franchise_data.get("franchise_movies"),
            "franchise_ovas": franchise_data.get("franchise_ovas"),
            "franchise_onas": franchise_data.get("franchise_onas"),
            "franchise_specials": franchise_data.get("franchise_specials"),
            "relations": franchise_data.get("relations", []),
            "genres": franchise_data.get("genres", []),
        }

        try:
            receipt = await RequestService(container).submit(
                telegram_id=user_id,
                source=source,
                source_ref=f"anilist:{anilist_id}" if anilist_id else query,
                anime_title=title,
                scope=DownloadScope.ENTIRE_SERIES,
                season=None,
                episodes=None,
                franchise_data=franchise_json,
            )
        except NekoFetchError as exc:
            # Submission failed (e.g. duplicate) — surface the error, reset to retry.
            await fsm.set(user_id, STATE_NAME)
            await send_screen(
                client, card_msg.chat.id,
                Screen(caption=t(exc.message_key)), old_msg=card_msg,
            )
            return
        await fsm.clear(user_id)

        # Admin users auto-queue; regular users wait for staff review
        is_admin = user_id in container.env.admin_ids
        if is_admin:
            try:
                await QueueService(container).enqueue(receipt.code)
            except NekoFetchError:
                pass

        screen = request_received(user_name, title, queue_pos=receipt.position)
        await send_screen(client, card_msg.chat.id, screen, old_msg=card_msg)

    # ──────────────────────────────────────────────────────────────────────────
    # My Requests
    # ──────────────────────────────────────────────────────────────────────────
    @client.on_callback_query(filters.regex(r"^req\|mine"))
    async def _mine(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.request_service import RequestService
        from nekofetch.ui.screens import my_requests as my_reqs_screen

        await q.answer()
        rows = await RequestService(container).list_for_user(q.from_user.id)
        name = q.from_user.first_name if q.from_user else ""
        if not rows:
            screen = my_reqs_screen(name, [])
            await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
            return
        req_list = [{"title": r.anime_title, "status": r.status} for r in rows[:10]]
        screen = my_reqs_screen(name, req_list)
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)

    # ── Home (back/welcome navigation) ──
    @client.on_callback_query(filters.regex(r"^(home)$"))
    async def _home(_: Client, q: CallbackQuery) -> None:
        from nekofetch.ui.screens import welcome as welcome_screen

        name = q.from_user.first_name or ""
        screen = welcome_screen(name)
        await send_screen(client, q.message.chat.id, screen, old_msg=q.message)
        await q.answer()

    # ── Helper ────────────────────────────────────────────────────────────────────

def _media_to_franchise_dict(media) -> dict:
    """Convert an AnilistMedia into the dict shape `confirm_franchise` expects."""
    return {
        "title": media.titles[0] if media.titles else "Unknown",
        "year": media.year,
        "format": media.format,
        "status": media.status,
        "score": media.score,
        "studio": media.studio,
        "genres": media.genres,
        "synopsis": media.synopsis,
        "franchise_episodes": media.franchise_episodes,
        "franchise_seasons": media.franchise_seasons,
        "franchise_movies": media.franchise_movies,
        "franchise_ovas": media.franchise_ovas,
        "franchise_onas": media.franchise_onas,
        "franchise_specials": media.franchise_specials,
        "relations": [
            {
                "relation": r.relation,
                "format": r.format,
                "episodes": r.episodes,
                "titles": r.titles,
                "anilist_id": r.anilist_id,
            }
            for r in media.relations
        ],
        "anilist_id": str(media.id),
        "anilist_url": media.anilist_url,
        "cover_url": media.cover_url,
        "banner_url": media.banner_url,
        "_source": "anilist",
    }
