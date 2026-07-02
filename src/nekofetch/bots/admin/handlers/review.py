from __future__ import annotations

import asyncio
import html as _html

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import Permission
from nekofetch.localization.messages import M
from nekofetch.services.auth_service import AuthService
from nekofetch.ui.components import cb, keyboard, lock_buttons, paginate
from nekofetch.ui.screens import show

PAGE_SIZE = 8
STATE_MANUAL_COMP = "staff:manual:comp"
STATE_MANUAL_AUDIO = "staff:manual:audio"
STATE_MANUAL_RES = "staff:manual:res"
STATE_MANUAL_CUSTOM_RES = "staff:manual:custom_res"
STATE_MANUAL_CONFIRM = "staff:manual:confirm"
STATE_MANUAL_INTAKE = "staff:manual:intake"
STATE_MANUAL = STATE_MANUAL_COMP  # legacy alias for the entry-point transition
STATE_TORRENT = "staff:torrent_pick"
STATE_PROVIDE = "staff:await_provide"   # admin is sending a file for a stuck episode


def _comp_key(comp: dict) -> str:
    """Unique key for a component in the FSM data bag."""
    t = comp.get("type", "season")
    if t == "season":
        return f"season_{comp.get('number', 1)}"
    return f"{t}_{comp.get('title', '0')}"


def _comp_label(comp: dict) -> str:
    """Human-readable label for a component."""
    t = comp.get("type", "season")
    if t == "season":
        return f"Season {comp.get('number', 1)}"
    title = comp.get("title", "")
    return f"{t.title()}: {title}" if title else t.title()


def _esc(text: str) -> str:
    """HTML-escape user-facing text for safe rendering."""
    return _html.escape(text or "", quote=False)


def _extract_components(franchise: dict, anime_title: str) -> list[dict]:
    """Extract uploadable components from franchise_data.

    Returns a list of dicts with ``type`` and identifying fields (``number`` for
    seasons, ``title`` for others). If there are no non-season components and only
    1 season, returns a single-entry list."""
    components: list[dict] = []
    seasons = franchise.get("franchise_seasons", 1) or 1
    for n in range(1, seasons + 1):
        components.append({"type": "season", "number": n})
    # Non-season components from the relations list
    relations = franchise.get("relations", [])
    for rel in relations:
        fmt = (rel.get("format") or "").upper()
        title = rel.get("title") or rel.get("english") or ""
        if fmt == "OVA":
            components.append({"type": "ova", "title": title})
        elif fmt == "MOVIE":
            components.append({"type": "movie", "title": title})
        elif fmt == "ONA":
            components.append({"type": "ona", "title": title})
        elif fmt == "SPECIAL":
            components.append({"type": "special", "title": title})
    return components


def register(client: Client, container: Container) -> None:
    auth = AuthService(container)
    fsm = FSM(container.redis, bot="admin")
    L = container.localizer.get

    def _allowed(q: CallbackQuery, permission: Permission) -> bool:
        user = getattr(q, "nf_user", None)
        return bool(user and auth.has_permission(user, permission))

    def _scope_label(req) -> str:
        if req.episodes:
            return L(M.SCOPE_SEASON_EPS, n=req.season or 1,
                     eps=", ".join(map(str, req.episodes)))
        if req.season:
            return L(M.SCOPE_SEASON, n=req.season)
        return req.scope.replace("_", " ").title()

    async def _render_list(q: CallbackQuery, page: int) -> None:
        from nekofetch.services.request_service import RequestService

        pending = await RequestService(container).list_pending()
        back = [(L(M.BTN_BACK), cb("admin", "home"))]
        if not pending:
            caption = f"{L(M.REVIEW_TITLE)}\n\n{L(M.REVIEW_EMPTY)}"
            await show(client, q.message, caption, keyboard(back))
            return
        items = [
            (L(M.REVIEW_ROW, code=r.code, title=r.anime_title[:28]),
             cb("staff", "rdetail", r.code))
            for r in pending
        ]
        kb = paginate(items, page=page, nav_action="staff|rpage", page_size=PAGE_SIZE)
        kb.inline_keyboard.append(keyboard(back).inline_keyboard[0])
        caption = f"{L(M.REVIEW_TITLE)}\n\n{L(M.REVIEW_COUNT, n=len(pending))}"
        await show(client, q.message, caption, kb)

    @client.on_callback_query(filters.regex(r"^staff\|requests"))
    async def _requests(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        parts = q.data.split("|")
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _render_list(q, page)

    @client.on_callback_query(filters.regex(r"^staff\|rpage"))
    async def _rpage(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        await _render_list(q, int(q.data.split("|")[-1]))

    @client.on_callback_query(filters.regex(r"^staff\|rdetail"))
    async def _detail(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        try:
            req = await RequestService(container).get(code)
        except NekoFetchError:
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            await _render_list(q, 0)
            return
        await q.answer()
        caption = (
            f"{L(M.REVIEW_DETAIL_TITLE, code=req.code)}\n\n"
            + L(M.REVIEW_DETAIL_BODY, anime=req.anime_title, status=req.status,
                scope=_scope_label(req), source=req.source, by=req.user_id)
        )
        kb = keyboard(
            [(L(M.ADMIN_BTN_TELEGRAM), cb("staff", "rsource", code, "telegram")),
             (L(M.ADMIN_BTN_WEBSITE), cb("staff", "rsource", code, "website")),
             (L(M.ADMIN_BTN_TORRENT), cb("staff", "rsource", code, "torrent"))],
            [(L(M.ADMIN_BTN_REJECT), cb("staff", "rreject", code))],
            [(L(M.BTN_BACK), cb("staff", "requests", 0))],
        )
        await show(client, q.message, caption, kb)

    @client.on_callback_query(filters.regex(r"^staff\|rsource"))
    async def _source_select(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.log_channel_service import LogChannelService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, chosen_source = parts[2], parts[3]

        # This request is being assigned: lock the buttons against a double-tap and
        # mark it 'handling' so the persistent inbox advances to the next pending
        # request (or idle) within seconds instead of re-showing this one.
        await lock_buttons(q)
        await LogChannelService(container).mark_handling(code)

        if chosen_source == "telegram":
            await q.answer()
            kb = keyboard(
                [(L(M.ADMIN_BTN_AUTOMATIC), cb("staff", "rtgmode", code, "auto")),
                 (L(M.ADMIN_BTN_MANUAL), cb("staff", "rtgmode", code, "manual"))],
                [(L(M.BTN_BACK), cb("staff", "rdetail", code))],
            )
            await show(client, q.message, L(M.ADMIN_TG_CHOOSE), kb)
            return

        if chosen_source == "website":
            # Website sources always process the ENTIRE franchise. Before picking a
            # provider we analyse BOTH and present a report so the choice is informed.
            await q.answer()
            from nekofetch.services.website_report import build_website_report
            from nekofetch.ui.website_report import render_report

            try:
                req = await RequestService(container).get(code)
            except NekoFetchError:
                await q.answer(L(M.ERR_GENERIC), show_alert=True)
                return
            franchise = req.franchise_data or {}
            title = franchise.get("title") or req.anime_title
            back = keyboard([(L(M.BTN_BACK), cb("staff", "rdetail", code))])
            # 1) loading state, 2) build report, 3) report card with picker buttons.
            loading = await show(client, q.message, L(M.WEB_REPORT_LOADING, title=title), back)
            report = await build_website_report(container, title=title, franchise=franchise)
            kb = keyboard(
                [(L(M.SITE_BTN_ANIKOTO_PRIMARY),
                  cb("staff", "rsiteprio", code, "anikoto", "kickassanime")),
                 (L(M.SITE_BTN_KICKASS_PRIMARY),
                  cb("staff", "rsiteprio", code, "kickassanime", "anikoto"))],
                [(L(M.BTN_BACK), cb("staff", "rdetail", code))],
            )
            await show(client, loading, render_report(report), kb)
            return

        # Torrent: present a seeders-ranked, dual-audio-first picker (with auto-pick).
        await q.answer()
        try:
            req = await RequestService(container).get(code)
        except NekoFetchError:
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            return
        title = (req.franchise_data or {}).get("title") or req.anime_title
        back = keyboard([(L(M.BTN_BACK), cb("staff", "rdetail", code))])
        loading = await show(client, q.message, L(M.TORRENT_LOADING, title=title), back)
        try:
            stubs = (await container.sources.get("nyaa").search(title))[:24]
        except Exception:
            stubs = []
        if not stubs:
            await show(client, loading, L(M.TORRENT_EMPTY, title=title), back)
            return
        cands = [{"ref": s.source_ref, "label": s.title} for s in stubs]
        await fsm.set(q.from_user.id, STATE_TORRENT, code=code, title=title, cands=cands)
        await _render_torrent_page(loading, code, cands, 0, title)

    _TPAGE = 6

    async def _render_torrent_page(msg, code: str, cands: list[dict],
                                   page: int, title: str) -> None:
        start = page * _TPAGE
        page_items = cands[start:start + _TPAGE]
        rows = [[(L(M.TORRENT_BTN_AUTO), cb("staff", "rtauto", code))]]
        for i, c in enumerate(page_items, start=start):
            rows.append([(c["label"][:48], cb("staff", "rtpick", code, i))])
        nav = []
        if page > 0:
            nav.append((L(M.BTN_PREV), cb("staff", "rtpage", code, page - 1)))
        if start + _TPAGE < len(cands):
            nav.append((L(M.BTN_NEXT), cb("staff", "rtpage", code, page + 1)))
        if nav:
            rows.append(nav)
        rows.append([(L(M.BTN_BACK), cb("staff", "rdetail", code))])
        caption = f"{L(M.TORRENT_TITLE, title=title)}\n\n{L(M.TORRENT_INTRO, n=len(cands))}"
        await show(client, msg, caption, keyboard(*rows))

    async def _torrent_queue(q: CallbackQuery, idx: int) -> None:
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        _, data = await fsm.get(q.from_user.id)
        cands = data.get("cands", [])
        code = data.get("code")
        if not code or idx >= len(cands):
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            return
        chosen = cands[idx]
        try:
            await RequestService(container).update_source_ref(code, "nyaa", chosen["ref"])
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        await fsm.clear(q.from_user.id)
        await q.answer(L(M.TORRENT_QUEUED, title=f"job #{job_id}"), show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rtpage"))
    async def _torrent_page(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await q.answer()
        parts = q.data.split("|")
        code, page = parts[2], int(parts[3])
        _, data = await fsm.get(q.from_user.id)
        await _render_torrent_page(q.message, code, data.get("cands", []), page,
                                   data.get("title", ""))

    @client.on_callback_query(filters.regex(r"^staff\|rtpick"))
    async def _torrent_pick(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await _torrent_queue(q, int(q.data.split("|")[3]))

    @client.on_callback_query(filters.regex(r"^staff\|rtauto"))
    async def _torrent_auto(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        await _torrent_queue(q, 0)  # candidates are already ranked best-first

    @client.on_callback_query(filters.regex(r"^staff\|rsiteprio"))
    async def _site_priority(_: Client, q: CallbackQuery) -> None:
        """Confirm website provider priority list and queue the request."""
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 4)
        code, primary, fallback = parts[2], parts[3], parts[4]
        priority_str = f"{primary}>{fallback}"
        try:
            await RequestService(container).update_source(code, priority_str)
            job_id = await QueueService(container).enqueue(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_QUEUED, source=primary, job=job_id), show_alert=True)
        await _render_list(q, 0)

    @client.on_callback_query(filters.regex(r"^staff\|rtgmode"))
    async def _tg_mode(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService

        parts = q.data.split("|", 3)
        code, mode = parts[2], parts[3]

        if mode == "auto":
            try:
                await RequestService(container).update_source(code, "telegram")
                job_id = await QueueService(container).enqueue(code)
            except NekoFetchError as exc:
                await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
                return
            await q.answer(L(M.TOAST_QUEUED, source="telegram", job=job_id), show_alert=True)
            await _render_list(q, 0)
        elif mode == "manual":
            await q.answer()
            try:
                req = await RequestService(container).get(code)
            except NekoFetchError:
                await q.answer(L(M.ERR_GENERIC), show_alert=True)
                return
            fr = req.franchise_data or {}
            # Fetch TMDB backdrop so every wizard screen shows the series artwork.
            backdrop_url: str | None = None
            try:
                search_title = fr.get("english") or fr.get("title") or req.anime_title
                tmdb_result = await container.tmdb.search(search_title)
                if tmdb_result:
                    backdrop_url = tmdb_result.backdrop("w1280")
            except Exception:
                pass
            components = _extract_components(fr, req.anime_title)
            if len(components) == 1 and components[0]["type"] == "season":
                # Single season, no extras — skip component picker.
                await fsm.set(q.from_user.id, STATE_MANUAL_AUDIO, code=code,
                              anime_title=req.anime_title, components=components,
                              selected={}, audio={}, resolutions={},
                              current_index=0, backdrop_url=backdrop_url)
                await _render_audio_picker(q.message, q.from_user.id, components[0], 0)
            else:
                await fsm.set(q.from_user.id, STATE_MANUAL_COMP, code=code,
                              anime_title=req.anime_title, components=components,
                              selected={}, backdrop_url=backdrop_url)
                await _render_comp_picker(q.message, q.from_user.id)

    @client.on_callback_query(filters.regex(r"^staff\|jstop"))
    async def _job_stop(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        # Set the same Redis flag the download worker polls — it stops the CURRENT
        # episode, finishes the rest of the series, then retries this one at the end.
        try:
            job_id = int(q.data.split("|")[2])
        except (ValueError, IndexError):
            await q.answer()
            return
        if container.redis:
            await container.redis.set(f"nf:job:{job_id}:skip", "1", ex=300)
        await q.answer(L(M.TOAST_STOPPING), show_alert=True)

    @client.on_callback_query(filters.regex(r"^staff\|jcancel"))
    async def _job_cancel(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        try:
            job_id = int(q.data.split("|")[2])
        except (ValueError, IndexError):
            await q.answer()
            return
        # Terminate the whole job: marks it CANCELLED, signals a running worker to
        # abort, and clears live progress so it drops off ACTIVE TASKS.
        from nekofetch.services.queue_service import QueueService
        await QueueService(container).cancel(job_id)
        await q.answer(L(M.TOAST_CANCELLING), show_alert=True)

    # ── stuck-episode recovery: Retry / Switch source / Provide file ─────────────
    async def _load_stuck(code: str) -> dict | None:
        import json
        if not container.redis:
            return None
        raw = await container.redis.get(f"nf:stuck:{code}")
        return json.loads(raw) if raw else None

    async def _requeue(code: str, episodes: list, *, new_source: str | None = None) -> bool:
        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService
        try:
            await RequestService(container).retry_episodes(code, episodes, new_source=new_source)
            await QueueService(container).enqueue(code)
            return True
        except NekoFetchError:
            return False

    @client.on_callback_query(filters.regex(r"^staff\|aretry"))
    async def _attn_retry(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        code = q.data.split("|", 2)[2]
        await lock_buttons(q)
        stuck = await _load_stuck(code)
        if not stuck or not await _requeue(code, stuck["episodes"]):
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_RETRY_QUEUED))
        try:
            await q.message.edit_text(
                L(M.ATTN_RETRYING, eps=", ".join(map(str, stuck["episodes"]))),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    @client.on_callback_query(filters.regex(r"^staff\|aswitch\|"))
    async def _attn_switch(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        code = q.data.split("|", 2)[2]
        stuck = await _load_stuck(code)
        alt = (stuck or {}).get("alt_source")
        if not alt:
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer()
        try:
            await q.message.edit_text(L(M.ATTN_CHECKING_ALT, alt=alt.title()),
                                      parse_mode=ParseMode.HTML)
        except Exception:
            pass
        # Probe what the alternate source ACTUALLY offers so we can explicitly say
        # whether the needed audio (e.g. dub) exists there, not silently fail.
        explain = await _audio_compat(code, alt, stuck.get("audio_kinds", []))
        kb = keyboard(
            [(L(M.CC_BTN_SWITCH_CONFIRM, alt=alt.title()), cb("staff", "aswitchgo", code))],
            [(L(M.CC_BTN_PROVIDE), cb("staff", "aprovide", code))],
        )
        try:
            await q.message.edit_text(explain, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass

    async def _audio_compat(code: str, alt: str, needed: list) -> str:
        from nekofetch.services.request_service import RequestService
        try:
            req = await RequestService(container).get(code)
        except NekoFetchError:
            return L(M.ATTN_SWITCH_UNAVAILABLE, alt=alt.title())
        fr = req.franchise_data or {}
        titles = [x for x in (fr.get("english") or req.anime_title, fr.get("romaji")) if x]
        try:
            cov = await container.sources.get(alt).coverage(*titles)
        except Exception:
            cov = None
        if cov is None or not getattr(cov, "available", False):
            return L(M.ATTN_SWITCH_UNAVAILABLE, alt=alt.title())
        lines = [L(M.ATTN_SWITCH_HEADER, alt=alt.title())]
        need_dub = "dubbed" in needed or "dual_audio" in needed
        need_sub = "subbed" in needed or "dual_audio" in needed or not needed
        if need_sub:
            key = M.ATTN_SWITCH_HAS if cov.sub_episodes > 0 else M.ATTN_SWITCH_LACKS
            lines.append(L(key, alt=alt.title(), kind="sub"))
        if need_dub:
            key = M.ATTN_SWITCH_HAS if cov.dub_episodes > 0 else M.ATTN_SWITCH_LACKS
            lines.append(L(key, alt=alt.title(), kind="dub"))
        return "\n".join(lines)

    @client.on_callback_query(filters.regex(r"^staff\|aswitchgo"))
    async def _attn_switch_go(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        code = q.data.split("|", 2)[2]
        await lock_buttons(q)
        stuck = await _load_stuck(code)
        alt = (stuck or {}).get("alt_source")
        if not (stuck and alt and await _requeue(code, stuck["episodes"], new_source=alt)):
            await q.answer(L(M.ERR_GENERIC), show_alert=True)
            return
        await q.answer(L(M.TOAST_RETRY_QUEUED))
        try:
            await q.message.edit_text(
                L(M.ATTN_RETRYING, eps=", ".join(map(str, stuck["episodes"]))),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    @client.on_callback_query(filters.regex(r"^staff\|aprovide"))
    async def _attn_provide(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        code = q.data.split("|", 2)[2]
        stuck = await _load_stuck(code)
        eps = (stuck or {}).get("episodes", [])
        await fsm.set(q.from_user.id, STATE_PROVIDE, code=code, episodes=eps)
        await q.answer()
        try:
            await q.message.edit_text(
                L(M.ATTN_PROVIDE_PROMPT, eps=", ".join(map(str, eps)) or "—"),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    @client.on_message((filters.document | filters.video) & filters.private, group=5)
    async def _provide_ingest(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_PROVIDE:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.QUEUE_DOWNLOADS)):
            return
        from pathlib import Path

        from nekofetch.services.download_service import DownloadWorker

        code = data.get("code")
        eps = data.get("episodes") or []
        episode = int(eps[0]) if eps else 1
        media = message.document or message.video
        orig = getattr(media, "file_name", "") or "provided.mkv"
        ext = Path(orig).suffix or ".mkv"
        target = Path(container.env.storage_path) / "work" / "_provided" / f"{code}_E{episode}{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            path = await message.download(file_name=str(target))
            await DownloadWorker(container).ingest_provided_file(code, episode, path)
        except Exception as exc:  # noqa: BLE001
            await message.reply(L(M.ATTN_PROVIDE_FAILED, reason=str(exc)[:160]),
                                parse_mode=ParseMode.HTML)
            return
        remaining = eps[1:]
        if remaining:
            await fsm.set(message.from_user.id, STATE_PROVIDE, code=code, episodes=remaining)
        else:
            await fsm.clear(message.from_user.id)
        await message.reply(L(M.ATTN_PROVIDE_DONE, name=orig, ep=episode),
                            parse_mode=ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^staff\|rreject"))
    async def _reject(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.REVIEW_REQUESTS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        from nekofetch.services.log_channel_service import LogChannelService
        from nekofetch.services.request_service import RequestService

        code = q.data.split("|", 2)[2]
        await lock_buttons(q)
        try:
            await RequestService(container).reject(code)
        except NekoFetchError as exc:
            await q.answer(getattr(exc, "detail", None) or L(M.ERR_GENERIC), show_alert=True)
            return
        # Rejected → it leaves the pending queue; clear any handling flag so the
        # persistent inbox refreshes to the next request (or idle).
        await LogChannelService(container).clear_handling(code)
        await q.answer(L(M.TOAST_REJECTED))
        await _render_list(q, 0)

    # ════════════════════════════════════════════════════════════════════════
    # Manual Upload Wizard — FSM-driven multi-step flow
    # ════════════════════════════════════════════════════════════════════════

    # ── renderers ──

    async def _render_comp_picker(msg, user_id: int) -> None:
        _, data = await fsm.get(user_id)
        components = data.get("components", [])
        selected = data.get("selected", {})
        code = data.get("code", "")
        backdrop_url = data.get("backdrop_url")
        lines = [L(M.MANUAL_WIZ_COMP_TITLE), "", L(M.MANUAL_WIZ_COMP_PROMPT), ""]
        kb_rows: list[list[tuple[str, str]]] = []
        for comp in components:
            key = _comp_key(comp)
            label = _comp_label(comp)
            prefix = "✓" if selected.get(key) else "☐"
            lines.append(f"{prefix}  {_esc(label)}")
            kb_rows.append([(f"{prefix} {_esc(label)[:42]}",
                             cb("staff", "manual", "comp", "toggle", key))])
        kb_rows.append([(L(M.MANUAL_WIZ_COMP_ENTIRE),
                         cb("staff", "manual", "comp", "entire"))])
        kb_rows.append([(L(M.MANUAL_WIZ_COMP_DONE),
                         cb("staff", "manual", "comp", "done")),
                        (L(M.BTN_BACK), cb("staff", "rdetail", code))])
        await show(client, msg, "\n".join(lines), keyboard(*kb_rows),
                   image=backdrop_url)

    async def _render_audio_picker(msg, user_id: int, component: dict, index: int) -> None:
        _, data = await fsm.get(user_id)
        backdrop_url = data.get("backdrop_url")
        label = _comp_label(component)
        lines = [L(M.MANUAL_WIZ_AUDIO_TITLE, component=_esc(label)), ""]
        audio_types = [
            (M.MANUAL_WIZ_AUDIO_SUBBED, "subbed"),
            (M.MANUAL_WIZ_AUDIO_DUBBED, "dubbed"),
            (M.MANUAL_WIZ_AUDIO_DUAL, "dual_audio"),
            (M.MANUAL_WIZ_AUDIO_MULTI, "multi"),
        ]
        kb_rows: list[list[tuple[str, str]]] = []
        for msg_key, audio_val in audio_types:
            lines.append(f"•  {L(msg_key)}")
            kb_rows.append([(L(msg_key), cb("staff", "manual", "audio", audio_val))])
        await show(client, msg, "\n".join(lines), keyboard(*kb_rows),
                   image=backdrop_url)

    async def _render_res_picker(msg, user_id: int, component: dict, index: int) -> None:
        _, data = await fsm.get(user_id)
        label = _comp_label(component)
        comp_key = _comp_key(component)
        audio = data.get("audio", {}).get(comp_key, "subbed")
        resolutions = data.get("resolutions", {}).get(comp_key, [])
        backdrop_url = data.get("backdrop_url")
        lines = [L(M.MANUAL_WIZ_RES_TITLE, component=_esc(label), audio=audio), ""]
        res_options = ["360p", "480p", "540p", "720p", "1080p"]
        kb_rows: list[list[tuple[str, str]]] = []
        row: list[tuple[str, str]] = []
        for r in res_options:
            prefix = "☑" if r in resolutions else "☐"
            lines.append(f"{prefix}  {r}")
            row.append((f"{prefix} {r}", cb("staff", "manual", "res", "toggle", r)))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)
        kb_rows.append([(L(M.MANUAL_WIZ_RES_CUSTOM),
                         cb("staff", "manual", "res", "custom"))])
        kb_rows.append([(L(M.MANUAL_WIZ_RES_DONE),
                         cb("staff", "manual", "res", "done"))])
        await show(client, msg, "\n".join(lines), keyboard(*kb_rows),
                   image=backdrop_url)

    async def _render_confirm(msg, user_id: int) -> None:
        _, data = await fsm.get(user_id)
        code = data.get("code", "")
        audio = data.get("audio", {})
        resolutions = data.get("resolutions", {})
        selected_keys = list(data.get("selected", {}).keys())
        backdrop_url = data.get("backdrop_url")
        lines = [L(M.MANUAL_WIZ_CONFIRM_TITLE), ""]
        if not selected_keys:
            lines.append(L(M.MANUAL_WIZ_CONFIRM_EMPTY))
        else:
            for key in selected_keys:
                a = audio.get(key, "—")
                res_list = resolutions.get(key, [])
                res_str = ", ".join(res_list) if res_list else "—"
                lines.append(L(M.MANUAL_WIZ_CONFIRM_LINE, component=key.replace("_", " ").title(),
                               audio=a, resolutions=res_str))
        kb_rows: list[list[tuple[str, str]]] = [
            [(L(M.MANUAL_WIZ_CONFIRM_BTN), cb("staff", "manual", "confirm", "go"))],
            [(L(M.MANUAL_WIZ_CHANGE_BTN), cb("staff", "manual", "confirm", "back"))],
            [(L(M.BTN_BACK), cb("staff", "rdetail", code))],
        ]
        await show(client, msg, "\n".join(lines), keyboard(*kb_rows),
                   image=backdrop_url)

    # ── callback handlers for each wizard step ──

    @client.on_callback_query(filters.regex(r"^staff\|manual\|comp\|"))
    async def _manual_comp_cb(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        state, data = await fsm.get(q.from_user.id)
        if state not in (STATE_MANUAL_COMP, STATE_MANUAL_CONFIRM):
            await q.answer()
            return
        parts = q.data.split("|")
        action = parts[3]
        components = data.get("components", [])
        selected = data.get("selected", {})
        code = data.get("code", "")
        anime_title = data.get("anime_title", "")

        if action == "toggle":
            key = parts[4]
            if key in selected:
                del selected[key]
            else:
                selected[key] = True
            await fsm.update(q.from_user.id, selected=selected)
            await _render_comp_picker(q.message, q.from_user.id)
        elif action == "entire":
            selected = {_comp_key(c): True for c in components}
            await fsm.update(q.from_user.id, selected=selected)
            await _render_comp_picker(q.message, q.from_user.id)
        elif action == "done":
            if not selected:
                await q.answer(L(M.MANUAL_WIZ_CONFIRM_EMPTY), show_alert=True)
                return
            selected_components = [c for c in components if _comp_key(c) in selected]
            queue = [(c, "audio") for c in selected_components]
            await fsm.update(q.from_user.id, selected=selected, queue=queue,
                             current_index=0, audio={}, resolutions={})
            await _render_audio_picker(q.message, q.from_user.id,
                                       selected_components[0], 0)
            await fsm.set(q.from_user.id, STATE_MANUAL_AUDIO, code=code,
                          anime_title=anime_title, components=components,
                          selected=selected, queue=queue, current_index=0,
                          audio={}, resolutions={},
                          backdrop_url=data.get("backdrop_url"))
        await q.answer()

    @client.on_callback_query(filters.regex(r"^staff\|manual\|audio\|"))
    async def _manual_audio_cb(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        state, data = await fsm.get(q.from_user.id)
        if state != STATE_MANUAL_AUDIO:
            await q.answer()
            return
        audio_type = q.data.split("|")[3]
        comp_idx = data.get("current_index", 0)
        queue = data.get("queue", [])
        component = queue[comp_idx][0] if queue else {}
        comp_key = _comp_key(component)
        audio = data.get("audio", {})
        audio[comp_key] = audio_type
        await fsm.update(q.from_user.id, audio=audio)
        await fsm.set(q.from_user.id, STATE_MANUAL_RES,
                      code=data.get("code"), anime_title=data.get("anime_title"),
                      components=data.get("components"),
                      selected=data.get("selected"), queue=queue,
                      current_index=comp_idx, audio=audio,
                      resolutions=data.get("resolutions", {}),
                      backdrop_url=data.get("backdrop_url"))
        await _render_res_picker(q.message, q.from_user.id, component, comp_idx)
        await q.answer()

    @client.on_callback_query(filters.regex(r"^staff\|manual\|res\|"))
    async def _manual_res_cb(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        state, data = await fsm.get(q.from_user.id)
        if state != STATE_MANUAL_RES:
            await q.answer()
            return
        action = q.data.split("|")[3]
        comp_idx = data.get("current_index", 0)
        queue = data.get("queue", [])
        component = queue[comp_idx][0] if queue else {}
        comp_key = _comp_key(component)
        resolutions = data.get("resolutions", {})
        current = list(resolutions.get(comp_key, []))

        if action == "toggle":
            res = q.data.split("|")[4]
            if res in current:
                current.remove(res)
            else:
                current.append(res)
            resolutions[comp_key] = current
            await fsm.update(q.from_user.id, resolutions=resolutions)
            await _render_res_picker(q.message, q.from_user.id, component, comp_idx)
        elif action == "custom":
            await fsm.update(q.from_user.id, resolutions=resolutions)
            await fsm.set(q.from_user.id, STATE_MANUAL_CUSTOM_RES,
                          code=data.get("code"), anime_title=data.get("anime_title"),
                          components=data.get("components"),
                          selected=data.get("selected"), queue=queue,
                          current_index=comp_idx, audio=data.get("audio"),
                          resolutions=resolutions,
                          backdrop_url=data.get("backdrop_url"))
            kb = keyboard([(L(M.BTN_BACK), cb("staff", "manual", "res", "done"))])
            backdrop_url = data.get("backdrop_url")
            await show(client, q.message, L(M.MANUAL_WIZ_RES_CUSTOM_PROMPT), kb,
                       image=backdrop_url)
        elif action == "done":
            if not current:
                await q.answer(L(M.MANUAL_WIZ_CONFIRM_EMPTY), show_alert=True)
                return
            resolutions[comp_key] = current
            # Move to next component or confirm
            next_idx = comp_idx + 1
            if next_idx < len(queue):
                next_comp = queue[next_idx][0]
                await fsm.update(q.from_user.id, resolutions=resolutions)
                await fsm.set(q.from_user.id, STATE_MANUAL_AUDIO,
                              code=data.get("code"), anime_title=data.get("anime_title"),
                              components=data.get("components"),
                              selected=data.get("selected"), queue=queue,
                              current_index=next_idx, audio=data.get("audio"),
                              resolutions=resolutions,
                              backdrop_url=data.get("backdrop_url"))
                await _render_audio_picker(q.message, q.from_user.id, next_comp, next_idx)
            else:
                await fsm.update(q.from_user.id, resolutions=resolutions)
                await fsm.set(q.from_user.id, STATE_MANUAL_CONFIRM,
                              code=data.get("code"), anime_title=data.get("anime_title"),
                              components=data.get("components"),
                              selected=data.get("selected"), audio=data.get("audio"),
                              resolutions=resolutions,
                              backdrop_url=data.get("backdrop_url"))
                await _render_confirm(q.message, q.from_user.id)
        await q.answer()

    @client.on_callback_query(filters.regex(r"^staff\|manual\|confirm\|"))
    async def _manual_confirm_cb(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        state, data = await fsm.get(q.from_user.id)
        if state != STATE_MANUAL_CONFIRM:
            await q.answer()
            return
        action = q.data.split("|")[3]
        if action == "go":
            await _start_intake(q.message, q.from_user.id, data)
        elif action == "back":
            components = data.get("components", [])
            selected = data.get("selected", {})
            await fsm.set(q.from_user.id, STATE_MANUAL_COMP,
                          code=data.get("code"), anime_title=data.get("anime_title"),
                          components=components, selected=selected,
                          backdrop_url=data.get("backdrop_url"))
            await _render_comp_picker(q.message, q.from_user.id)
        await q.answer()

    @client.on_callback_query(filters.regex(r"^staff\|manual\|cancel"))
    async def _manual_cancel_cb(_: Client, q: CallbackQuery) -> None:
        if not _allowed(q, Permission.QUEUE_DOWNLOADS):
            await q.answer(L(M.ACCESS_DENIED), show_alert=True)
            return
        state, data = await fsm.get(q.from_user.id)
        if state is None:
            await q.answer()
            return
        code = data.get("code", "")
        backdrop_url = data.get("backdrop_url")
        await fsm.clear(q.from_user.id)
        await q.answer()
        await show(client, q.message, L(M.MANUAL_CANCELLED),
                   keyboard([(L(M.BTN_BACK), cb("staff", "rdetail", code))]),
                   image=backdrop_url)

    async def _start_intake(msg, user_id: int, data: dict) -> None:
        """Build the upload queue and enter the file-intake loop."""
        selected_keys = list(data.get("selected", {}).keys())
        components = data.get("components", [])
        audio = data.get("audio", {})
        resolutions = data.get("resolutions", {})
        comp_map = {_comp_key(c): c for c in components}
        build_order: list[tuple[str, str, str, str]] = []
        for key in selected_keys:
            comp = comp_map.get(key, {"type": "season", "number": key})
            comp_label = _comp_label(comp)
            aud = audio.get(key, "subbed")
            for res in resolutions.get(key, []):
                build_order.append((key, comp_label, aud, res))
        await fsm.set(user_id,
                      STATE_MANUAL_INTAKE,
                      code=data.get("code"), anime_title=data.get("anime_title"),
                      components=data.get("components"),
                      selected=data.get("selected"), audio=audio,
                      resolutions=resolutions, build_order=build_order,
                      current_batch=0, received={},
                      received_count=0,
                      backdrop_url=data.get("backdrop_url"))
        await _prompt_intake(msg, user_id, build_order[0], 0, 0)

    async def _prompt_intake(msg, user_id, batch, batch_idx: int, received: int) -> None:
        _, data = await fsm.get(user_id)
        backdrop_url = data.get("backdrop_url")
        comp_key, comp_label, audio_type, res = batch
        lines = [
            L(M.MANUAL_INTAKE_PROMPT, component=_esc(comp_label),
              audio=audio_type, res=res),
            "",
            L(M.MANUAL_INTAKE_INSTRUCTIONS),
        ]
        kb_rows: list[list[tuple[str, str]]] = [
            [(L(M.BTN_CANCEL), cb("staff", "manual", "cancel"))],
        ]
        await show(client, msg, "\n".join(lines), keyboard(*kb_rows),
                   image=backdrop_url)

    # ── intake message handlers ──

    @client.on_message((filters.document | filters.video) & filters.private, group=6)
    async def _manual_intake_files(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_MANUAL_INTAKE:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.QUEUE_DOWNLOADS)):
            return
        batch_idx = data.get("current_batch", 0)
        build_order = data.get("build_order", [])
        if batch_idx >= len(build_order):
            return
        media = message.document or message.video
        if not media:
            await message.reply(L(M.MANUAL_INVALID_FILE), parse_mode=ParseMode.HTML)
            return
        code = data.get("code", "")
        batch_key = f"{batch_idx}"
        received = data.get("received", {})
        paths = received.get(batch_key, [])
        # Save file to temp dir
        from pathlib import Path

        work_dir = Path(container.env.storage_path) / "work" / "_manual" / code / f"batch_{batch_idx}"
        work_dir.mkdir(parents=True, exist_ok=True)
        orig_name = getattr(media, "file_name", "") or f"file_{len(paths) + 1}.mkv"
        dest = work_dir / orig_name
        try:
            saved = await message.download(file_name=str(dest))
            paths.append(str(saved))
        except Exception as exc:
            await message.reply(
                L(M.MANUAL_INVALID_FILE),
                parse_mode=ParseMode.HTML,
            )
            return
        received[batch_key] = paths
        total = len(paths)
        await fsm.update(message.from_user.id, received=received,
                         received_count=data.get("received_count", 0) + 1)
        await message.reply(
            L(M.MANUAL_INTAKE_RECEIVED, filename=_esc(orig_name[:60]), n=total),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.sticker & filters.private, group=7)
    async def _manual_intake_sticker(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_MANUAL_INTAKE:
            return
        batch_idx = data.get("current_batch", 0)
        build_order = data.get("build_order", [])
        if batch_idx >= len(build_order):
            return
        batch_key = f"{batch_idx}"
        received = data.get("received", {})
        paths = received.get(batch_key, [])
        if not paths:
            await message.reply(L(M.MANUAL_NO_FILES), parse_mode=ParseMode.HTML)
            return
        batch = build_order[batch_idx]
        comp_key, comp_label, audio_type, res = batch
        await message.reply(
            L(M.MANUAL_INTAKE_BATCH_DONE, count=len(paths),
              component=_esc(comp_label), audio=audio_type, res=res),
            parse_mode=ParseMode.HTML,
        )
        next_idx = batch_idx + 1
        if next_idx < len(build_order):
            next_batch = build_order[next_idx]
            await fsm.update(message.from_user.id, current_batch=next_idx)
            await _prompt_intake(message, message.from_user.id,
                                 next_batch, next_idx, 0)
        else:
            # All batches done — process!
            await message.reply(
                L(M.MANUAL_INTAKE_ALL_DONE,
                  title=_esc(data.get("anime_title", ""))),
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(_process_manual_upload(
                message, message.from_user.id, data,
            ))

    # ── custom resolution text handler ──

    @client.on_message(filters.text & filters.private & ~filters.command(["start"]), group=4)
    async def _manual_custom_res_input(_: Client, message: Message) -> None:
        if not message.from_user:
            return
        state, data = await fsm.get(message.from_user.id)
        if state != STATE_MANUAL_CUSTOM_RES:
            return
        user = getattr(message, "nf_user", None)
        if not (user and auth.has_permission(user, Permission.QUEUE_DOWNLOADS)):
            return
        text = (message.text or "").strip()
        if not text:
            return
        comp_idx = data.get("current_index", 0)
        queue = data.get("queue", [])
        component = queue[comp_idx][0] if queue else {}
        comp_key = _comp_key(component)
        resolutions = data.get("resolutions", {})
        current = list(resolutions.get(comp_key, []))
        if text not in current:
            current.append(text)
        resolutions[comp_key] = current
        await fsm.set(message.from_user.id, STATE_MANUAL_RES,
                      code=data.get("code"), anime_title=data.get("anime_title"),
                      components=data.get("components"),
                      selected=data.get("selected"), queue=queue,
                      current_index=comp_idx, audio=data.get("audio"),
                      resolutions=resolutions,
                      backdrop_url=data.get("backdrop_url"))
        await _render_res_picker(message, message.from_user.id, component, comp_idx)

    async def _process_manual_upload(
        trigger_msg, user_id: int, data: dict,
    ) -> None:
        """After all files collected: sort, process, upload, enqueue."""
        from pathlib import Path

        from nekofetch.services.queue_service import QueueService
        from nekofetch.services.request_service import RequestService
        from nekofetch.sources.telegram.manual_pack import process_pack
        from nekofetch.sources._torrent import parse_release_meta

        code = data.get("code", "")
        title = data.get("anime_title", "")
        received = data.get("received", {})
        build_order = data.get("build_order", [])
        audio = data.get("audio", {})

        try:
            # 1. Update source to telegram_manual
            req_svc = RequestService(container)
            await req_svc.update_source(code, "telegram_manual")

            # 2. Process each batch: sort, normalize, store
            total_processed = 0
            work_base = Path(container.env.storage_path) / "work" / "_manual" / code
            out_base = Path(container.env.storage_path) / "work" / code
            out_base.mkdir(parents=True, exist_ok=True)

            for batch_idx, batch in enumerate(build_order):
                comp_key, comp_label, audio_type, res = batch
                paths = received.get(str(batch_idx), [])
                if not paths:
                    continue
                # Sort files by extracted episode number
                def _ep_sort(filepath: str) -> int:
                    name = Path(filepath).name
                    meta = parse_release_meta(name)
                    ep = meta.get("episode")
                    return ep if ep is not None else 9999
                paths.sort(key=_ep_sort)
                # Determine season number from component
                season = 1
                for comp in data.get("components", []):
                    if _comp_key(comp) == comp_key:
                        season = comp.get("number", 1)
                        break
                result = await process_pack(
                    anime=title,
                    quality=res,
                    ordered_files=paths,
                    out_dir=out_base,
                    season=season,
                    audio_config=audio_type,
                )
                total_processed += result.get("processed", 0)

            # 3. Enqueue for standard pipeline
            job_id = await QueueService(container).enqueue(code)
            await fsm.clear(user_id)
            await trigger_msg.reply(
                L(M.MANUAL_PROCESSING_DONE, count=total_processed),
                parse_mode=ParseMode.HTML,
            )
        except NekoFetchError as exc:
            await fsm.clear(user_id)
            await trigger_msg.reply(
                L(M.MANUAL_QUEUE_FAILED,
                  reason=getattr(exc, "detail", None) or L(M.ERR_GENERIC)),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            await fsm.clear(user_id)
            await trigger_msg.reply(
                L(M.MANUAL_QUEUE_FAILED, reason=str(exc)[:200]),
                parse_mode=ParseMode.HTML,
            )
