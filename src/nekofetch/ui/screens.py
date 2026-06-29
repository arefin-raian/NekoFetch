"""v2 user-facing screens — artwork + HTML caption + keyboard per surface.

Pure builders (no Telegram I/O), unit-testable, handlers stay declarative. Every
visible string comes from the centralized catalog (``localization.messages``) —
no raw text here. HTML parse mode, bold-first emphasis, colon-separated fields,
no code styling, a 16:9 artwork (no back-to-back repeats) on every major surface.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from nekofetch.core.constants import BULLET, DOT_ACTIVE, DOT_DONE, DOT_PENDING
from nekofetch.localization.messages import PARSE_MODE, M, t
from nekofetch.ui.artwork import pick_artwork
from nekofetch.ui.components import cb

# ── status glyphs (lifecycle / lists) — shared design language ──
DONE, CURRENT, PENDING = DOT_DONE, DOT_ACTIVE, DOT_PENDING

# Lifecycle order; labels resolve from the catalog at render time.
_LIFECYCLE_KEYS = [
    M.LC_REQUESTED, M.LC_PENDING, M.LC_SOURCE_ASSIGNED, M.LC_DOWNLOADING,
    M.LC_PROCESSING_META, M.LC_EXTRACTING_SUBS, M.LC_WATERMARK,
    M.LC_UPLOADING, M.LC_PUBLISHED, M.LC_COMPLETED,
]


# Telegram hard limits. The photo-caption budget is kept a touch under 1024 so a
# trailing entity or stray character can never tip a send over the edge.
CAPTION_LIMIT = 1000
MESSAGE_LIMIT = 4096


@dataclass(slots=True)
class Screen:
    caption: str
    image: str | Path | None = None  # local path or HTTP(S) URL
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: ParseMode = PARSE_MODE


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def visible_len(html_text: str) -> int:
    """Approximate the length Telegram counts — tags become entities and don't
    count toward the caption/message limit, so measure the stripped text."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", html_text or "")))


def _truncate_html(html_text: str, limit: int) -> str:
    """Shorten ``html_text`` so its *visible* length fits ``limit``.

    Drops whole lines from the end (keeping HTML tags balanced, since each line is
    self-contained) until it fits, then appends an ellipsis. A blunt last-resort
    safeguard — callers should budget content first; this only guarantees we never
    exceed the hard limit.
    """
    if visible_len(html_text) <= limit:
        return html_text
    lines = html_text.split("\n")
    while lines and visible_len("\n".join(lines)) > limit - 1:
        lines.pop()
    out = "\n".join(lines).rstrip()
    return (out + " …") if out else html_text[:limit]


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(lbl, callback_data=data) for lbl, data in row]
         for row in rows]
    )


def _field(key: str, value: str) -> str:
    """Clean ``Label : value`` row — bold label (from catalog), plain value."""
    return f"<b>{t(key)}</b> : {_esc(value)}"


def lifecycle_labels() -> list[str]:
    return [t(k) for k in _LIFECYCLE_KEYS]


# ── User screens ───────────────────────────────────────────────────────────

def welcome(user_name: str, *, is_staff: bool = False, is_admin: bool = False) -> Screen:
    name = _esc(user_name) or "there"
    caption = "\n\n".join([
        t(M.WELCOME_TITLE, name=name),
        t(M.WELCOME_BODY),
        t(M.WELCOME_LIBRARY),
    ])
    rows = [[(t(M.BTN_REQUEST_ANIME), cb("req", "new")),
             (t(M.BTN_MY_REQUESTS), cb("req", "mine", 0))]]
    if is_staff or is_admin:
        rows.append([(t(M.BTN_REVIEW_REQUESTS), cb("staff", "requests", 0)),
                     (t(M.ADMIN_BTN_QUEUE), cb("queue", "view", 0))])
    if is_admin:
        rows.append([(t(M.ADMIN_BTN_PANEL), cb("admin", "home"))])
    return Screen(caption=caption, image=pick_artwork(), keyboard=_kb(rows))


def my_requests(user_name: str, requests: list[dict]) -> Screen:
    name = _esc(user_name) or "you"
    lines = [t(M.MYREQ_TITLE, name=name), ""]
    if not requests:
        lines.append(t(M.MYREQ_EMPTY))
    else:
        width = min(28, max((len(r["title"]) for r in requests), default=0))
        for r in requests:
            lines.append(t(M.MYREQ_ROW, title=_esc(r["title"])[:28].ljust(width),
                           status=_esc(r["status"])))
        ready = sum(1 for r in requests if "ready" in r["status"].lower())
        prog = sum(1 for r in requests if any(
            k in r["status"].lower() for k in ("process", "queue", "download", "upload")))
        wait = sum(1 for r in requests if "need" in r["status"].lower())
        lines += ["", t(M.MYREQ_SUMMARY, total=len(requests), ready=ready,
                        progress=prog, waiting=wait)]
    kb = _kb([[(t(M.BTN_REQUEST_ANIME), cb("req", "new"))],
              [(t(M.BTN_BACK), cb("home"))]])
    return Screen(caption="\n".join(lines), image=pick_artwork(), keyboard=kb)


def ask_title() -> Screen:
    return Screen(caption=t(M.ASK_TITLE), image=pick_artwork(),
                  keyboard=_kb([[(t(M.BTN_BACK), cb("home"))]]))


def confirm_franchise(
    media_data: dict,
    backdrop_path: str | None = None,
) -> Screen:
    """Rich franchise confirmation card — the centerpiece of Phase 1.

    ``media_data`` is a dict shaped like the expanded AnilistMedia fields:
    title, year, format, status, score, studio, genres, synopsis,
    franchise_episodes, franchise_seasons, franchise_movies, franchise_ovas,
    franchise_specials, relations (list of dicts each with relation, format,
    episodes, titles), anilist_url, cover_url, banner_url
    """
    english = _esc(media_data.get("english") or media_data.get("title", "Unknown"))
    romaji = media_data.get("romaji")
    year = media_data.get("year")

    # ── header (inside a blockquote): 🎬 Title (year) ❘ romaji ──
    head_inner = f"🎬 <b>{english}"
    if year:
        head_inner += f" ({_esc(str(year))})"
    if romaji and romaji.casefold() != (media_data.get("english") or "").casefold():
        head_inner += f" ❘</b> <i>{_esc(romaji)}</i>"
    else:
        head_inner += "</b>"
    rows = [f"<blockquote>{head_inner}</blockquote>", ""]

    # ── metadata fields: "<b>Label :</b> value" ──
    def kv(label_key: str, value: str) -> str:
        return f"<b>{t(label_key)} :</b> {_esc(value)}"

    if media_data.get("format"):
        rows.append(kv(M.F_TYPE, media_data["format"]))
    if media_data.get("status"):
        rows.append(kv(M.F_STATUS, media_data["status"]))
    if media_data.get("score"):
        rows.append(f"<b>{t(M.F_RATING)} :</b> {media_data['score']}/10")
    if media_data.get("studio"):
        rows.append(kv(M.FIELD_STUDIO, media_data["studio"]))
    if media_data.get("genres"):
        rows.append(kv(M.F_GENRES, t(M.SEP_DOT).join(media_data["genres"][:5])))

    # ── synopsis inside an expandable blockquote (Read More button if clipped) ──
    synopsis = (media_data.get("synopsis") or "").strip()
    synopsis = html.unescape(re.sub(r"<[^>]+>", "", synopsis)).strip()
    read_more_url: str | None = None
    if synopsis:
        if len(synopsis) > 600:
            synopsis = _esc(synopsis[:600].rsplit(" ", 1)[0]) + "…"
            read_more_url = media_data.get("synopsis_url") or media_data.get("anilist_url")
        else:
            synopsis = _esc(synopsis)
        syn_label = t(M.FIELD_SYNOPSIS)
        rows += ["", f"<blockquote expandable><b>{syn_label} :</b> {synopsis}</blockquote>"]

    # ── franchise content (computed from the full relation graph) ──
    ep_total = media_data.get("franchise_episodes")
    units = (
        (media_data.get("franchise_seasons", 0), M.UNIT_SEASONS),
        (media_data.get("franchise_movies", 0), M.UNIT_MOVIES),
        (media_data.get("franchise_ovas", 0), M.UNIT_OVAS),
        (media_data.get("franchise_onas", 0), M.UNIT_ONAS),
        (media_data.get("franchise_specials", 0), M.UNIT_SPECIALS),
        (media_data.get("franchise_spinoffs", 0), M.UNIT_SPINOFFS),
    )
    breakdown_bits = []
    for n, key in units:
        if n and n > 0:
            word = t(key)
            if n == 1 and word.endswith("s"):   # 1 season, 1 OVA, 1 movie
                word = word[:-1]
            bit = f"{n} {word}"
            if key == M.UNIT_SEASONS and ep_total:
                bit += f" ({ep_total} {t(M.UNIT_EPS)})"
            breakdown_bits.append(bit)
    if breakdown_bits:
        rows += ["", t(M.FRANCHISE_CONTENT) + " " + f" {BULLET} ".join(breakdown_bits)]

    rows += ["", t(M.CONFIRM_QUESTION)]
    caption = _truncate_html("\n".join(rows), CAPTION_LIMIT)

    kb_rows: list[list[InlineKeyboardButton]] = []
    if read_more_url:
        kb_rows.append([InlineKeyboardButton(t(M.BTN_READ_MORE), url=read_more_url)])
    kb_rows.append([
        InlineKeyboardButton(t(M.BTN_SERIES_YES),
                             callback_data=cb("series_yes", str(media_data.get("anilist_id", "")))),
        InlineKeyboardButton(t(M.BTN_SERIES_NO), callback_data=cb("series_no")),
    ])
    kb = InlineKeyboardMarkup(kb_rows)

    # Image priority: TMDB backdrop → AniList banner → cover → random local art.
    image: str | Path | None = None
    if backdrop_path:
        image = backdrop_path  # URL string, sent directly to send_photo
    elif media_data.get("banner_url"):
        image = media_data["banner_url"]
    elif media_data.get("cover_url"):
        image = media_data["cover_url"]
    return Screen(caption=caption, image=image or pick_artwork(), keyboard=kb)


def choose_version(query: str, versions: list[dict]) -> Screen:
    rows = [t(M.VERSION_HEADER, query=_esc(query)), ""]
    width = min(24, max((len(v["title"]) for v in versions), default=0))
    for v in versions:
        meta = t(M.SEP_DOT).join(str(x) for x in (
            v.get("format"), v.get("year"),
            f"{v['episodes']} eps" if v.get("episodes") else None) if x)
        rows.append(f"{_esc(v['title'])[:24].ljust(width)} :  <i>{_esc(meta)}</i>")
    btns = [[(v["title"][:32], cb("ver_pick", v.get("id", i)))]
            for i, v in enumerate(versions)]
    # 'Both' folds every adaptation into one combined request; 'Neither' restarts.
    btns.append([(t(M.BTN_VERSION_BOTH), cb("ver_pick_both")),
                 (t(M.BTN_VERSION_NEITHER), cb("series_no"))])
    return Screen(caption="\n".join(rows), image=pick_artwork(), keyboard=_kb(btns))


def retry_title() -> Screen:
    return Screen(caption=t(M.RETRY_TITLE), image=pick_artwork(),
                  keyboard=_kb([[(t(M.BTN_BACK), cb("home"))]]))


def request_received(user_name: str, title: str, queue_pos: int | None = None) -> Screen:
    rows = [t(M.REQ_RECEIVED, name=_esc(user_name) or "there"), "",
            _field(M.F_ANIME, title),
            _field(M.F_STATUS, t(M.VALUE_QUEUED))]
    if queue_pos is not None:
        rows.append(_field(M.F_QUEUE, f"#{queue_pos}"))
    rows += ["", t(M.REQ_RECEIVED_BODY)]
    return Screen(caption="\n".join(rows), image=pick_artwork(),
                  keyboard=_kb([[(t(M.BTN_MY_REQUESTS), cb("req", "mine", 0))]]))


# ── Log channel: one live card per request, edited as state advances ─────────

def log_card(req: dict) -> Screen:
    """``req`` keys: id, title, requester, source, state, optional substate,
    optional failed/reason/detail, and completed-summary fields."""
    title = _esc(req.get("title", "Unknown"))
    state = req.get("state", t(M.LC_REQUESTED))
    labels = lifecycle_labels()

    if req.get("failed"):
        rows = [t(M.LOG_BLOCKED_TITLE, title=title), "",
                _field(M.F_STUCK_AT, state),
                _field(M.F_REASON, req.get("reason", "unknown")),
                _field(M.F_SOURCE, req.get("source", "—"))]
        if req.get("detail"):
            rows += ["", f"<blockquote expandable>{_esc(req['detail'])}</blockquote>"]
        kb = _kb([[(t(M.BTN_RETRY), cb("log_retry", req.get("id", ""))),
                   (t(M.BTN_REASSIGN), cb("log_reassign", req.get("id", ""))),
                   (t(M.BTN_DISMISS), cb("log_dismiss", req.get("id", "")))]])
        return Screen(caption="\n".join(rows), image=pick_artwork(), keyboard=kb)

    if state == t(M.LC_COMPLETED):
        rows = [t(M.LOG_COMPLETED_TITLE, title=title), ""]
        for key, field_key in ((("seasons"), M.F_SEASONS), ("qualities", M.F_QUALITIES),
                                ("episodes", M.F_EPISODES), ("source", M.F_SOURCE),
                                ("took", M.F_TOOK)):
            if req.get(key):
                rows.append(_field(field_key, str(req[key])))
        return Screen(caption="\n".join(rows), image=pick_artwork())

    sub = f"  {t(M.SEP_DOT)}  {_esc(req['substate'])}" if req.get("substate") else ""
    rows = [t(M.LOG_PROGRESS_TITLE, title=title), "",
            _field(M.F_REQUEST, f"#{req.get('id', '—')}"),
            _field(M.F_BY, req.get("requester", "—")),
            _field(M.F_SOURCE, req.get("source", "—")),
            _field(M.F_NOW, f"{state}{sub}"), ""]
    cur_idx = labels.index(state) if state in labels else 0
    for i, step in enumerate(labels):
        glyph = DONE if i < cur_idx else (CURRENT if i == cur_idx else PENDING)
        rows.append(f"{glyph}  {'<b>' + step + '</b>' if i == cur_idx else step}")
    return Screen(caption="\n".join(rows), image=pick_artwork())


async def show(
    client: Client,
    src_msg: Message,
    caption: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    image: str | Path | None = None,
) -> Message:
    """Render an admin screen in place of ``src_msg`` with rotating artwork.

    Works whether ``src_msg`` is a text or a photo message — it deletes the old
    one and sends a fresh photo, sidestepping Telegram's "can't edit a media
    message's text" limitation that plagues callback-driven panels.
    """
    screen = Screen(caption=caption, image=image or pick_artwork(), keyboard=keyboard)
    return await send_screen(client, src_msg.chat.id, screen, old_msg=src_msg)


async def send_screen(
    client: Client,
    chat_id: int,
    screen: Screen,
    old_msg: Message | None = None,
) -> Message:
    """Send a Screen as a photo message, optionally replacing an old message.

    ``screen.image`` can be a local ``Path`` or an HTTP(S) URL (both work with
    Pyrogram's ``send_photo``). When no image is available, falls back to plain text.

    If ``old_msg`` is provided, it is deleted before the new message is sent.
    """
    if old_msg is not None:
        try:
            await old_msg.delete()
        except Exception:
            pass

    caption = screen.caption or ""
    photo = screen.image

    if photo:
        photo_arg = str(photo) if isinstance(photo, Path) else photo
        # Caption fits the photo budget → single photo message (the common path).
        if visible_len(caption) <= CAPTION_LIMIT:
            return await client.send_photo(
                chat_id, photo=photo_arg, caption=caption,
                parse_mode=screen.parse_mode, reply_markup=screen.keyboard,
            )
        # Overflow: send the image alone, then the full body (and the keyboard) as
        # a follow-up text message. Telegram never sees an over-budget caption, so
        # MEDIA_CAPTION_TOO_LONG can't happen — and no HTML is broken.
        try:
            await client.send_photo(chat_id, photo=photo_arg)
        except Exception:
            pass
        return await client.send_message(
            chat_id, _truncate_html(caption, MESSAGE_LIMIT),
            parse_mode=screen.parse_mode, reply_markup=screen.keyboard,
        )

    return await client.send_message(
        chat_id, _truncate_html(caption, MESSAGE_LIMIT),
        parse_mode=screen.parse_mode, reply_markup=screen.keyboard,
    )
