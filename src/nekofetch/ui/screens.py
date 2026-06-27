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

from nekofetch.localization.messages import PARSE_MODE, M, t
from nekofetch.ui.artwork import pick_artwork
from nekofetch.ui.components import cb

# ── status glyphs (lifecycle / lists) ──
DONE, CURRENT, PENDING = "●", "➤", "◌"

# Relation kinds / formats worth showing in the confirmation card's related-entries
# block — keep it to real, watchable franchise content (no source manga, no joke
# character shorts, no OTHER noise).
_REL_SHOW = {"SEQUEL", "PREQUEL", "SIDE_STORY", "ALTERNATIVE", "SPIN_OFF",
             "PARENT", "SUMMARY"}
_REL_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}

# Lifecycle order; labels resolve from the catalog at render time.
_LIFECYCLE_KEYS = [
    M.LC_REQUESTED, M.LC_PENDING, M.LC_SOURCE_ASSIGNED, M.LC_DOWNLOADING,
    M.LC_PROCESSING_META, M.LC_EXTRACTING_SUBS, M.LC_WATERMARK,
    M.LC_UPLOADING, M.LC_PUBLISHED, M.LC_COMPLETED,
]


@dataclass(slots=True)
class Screen:
    caption: str
    image: str | Path | None = None  # local path or HTTP(S) URL
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: ParseMode = PARSE_MODE


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


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

def welcome(user_name: str) -> Screen:
    name = _esc(user_name) or "there"
    caption = "\n\n".join([
        t(M.WELCOME_TITLE, name=name),
        t(M.WELCOME_BODY),
        t(M.WELCOME_LIBRARY),
    ])
    kb = _kb([[(t(M.BTN_REQUEST_ANIME), cb("req", "new")),
               (t(M.BTN_MY_REQUESTS), cb("req", "mine", 0))]])
    return Screen(caption=caption, image=pick_artwork(), keyboard=kb)


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


def searching(query: str, frame: str = "⠹") -> Screen:
    return Screen(caption=t(M.SEARCHING, query=_esc(query), frame=frame), image=None)


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
    title = _esc(media_data.get("title", "Unknown"))
    year = media_data.get("year")
    header = f"🎬  <b>{title}</b>"
    if year:
        header += f"  <i>({_esc(str(year))})</i>"
    rows = [header, ""]

    # ── metadata fields ──
    if media_data.get("format"):
        rows.append(_field(M.F_TYPE, media_data["format"]))
    if media_data.get("status"):
        rows.append(_field(M.F_STATUS, media_data["status"]))
    if media_data.get("score"):
        rows.append(_field(M.F_RATING, f"{media_data['score']}/10"))
    if media_data.get("studio"):
        rows.append(_field(M.FIELD_STUDIO, media_data["studio"]))
    if media_data.get("genres"):
        rows.append(_field(M.F_GENRES, t(M.SEP_DOT).join(media_data["genres"][:5])))

    # ── synopsis (cleanly truncated, with a Read More link to AniList) ──
    synopsis = (media_data.get("synopsis") or "").strip()
    # AniList descriptions may carry inline <br>/<i> markup — strip tags for a
    # clean, predictable caption.
    synopsis = html.unescape(re.sub(r"<[^>]+>", "", synopsis)).strip()
    anilist_url = media_data.get("anilist_url")
    if synopsis:
        if len(synopsis) > 300:
            clipped = _esc(synopsis[:300].rsplit(" ", 1)[0]) + "…"
            if anilist_url:
                clipped += f" <a href=\"{_esc(anilist_url)}\">{t(M.BTN_READ_MORE)}</a>"
            rows += ["", clipped]
        else:
            rows += ["", _esc(synopsis)]

    # ── franchise breakdown ──
    ep_total = media_data.get("franchise_episodes")
    units = (
        (media_data.get("franchise_seasons", 0), M.UNIT_SEASONS),
        (media_data.get("franchise_movies", 0), M.UNIT_MOVIES),
        (media_data.get("franchise_ovas", 0), M.UNIT_OVAS),
        (media_data.get("franchise_onas", 0), M.UNIT_ONAS),
        (media_data.get("franchise_specials", 0), M.UNIT_SPECIALS),
    )
    breakdown_bits = []
    for n, key in units:
        if n and n > 0:
            word = t(key)
            if n == 1 and word.endswith("s"):   # 1 season, 1 OVA, 1 movie
                word = word[:-1]
            bit = f"<b>{n}</b> {word}"
            if key == M.UNIT_SEASONS and ep_total:
                bit += f" ({ep_total} {t(M.UNIT_EPS)})"
            breakdown_bits.append(bit)
    if breakdown_bits:
        rows += ["", t(M.FRANCHISE_CONTENT) + "  " + "  ✦  ".join(breakdown_bits)]

    # ── related entries (filtered, newline-separated, expandable) ──
    relations = [
        r for r in media_data.get("relations", [])
        if r.get("relation") in _REL_SHOW and r.get("format") in _REL_FORMATS
    ]
    if relations:
        rel_lines = []
        for r in relations[:15]:  # cap to avoid runaway captions
            rtype = _esc((r.get("relation") or "").replace("_", " ").title())
            titles = r.get("titles") or ["?"]
            rtitle = _esc(titles[0])
            rfmt = _esc(r.get("format") or "")
            reps = r.get("episodes")
            rep_str = f" · {reps} {t(M.UNIT_EPS)}" if reps and reps > 1 else ""
            rel_lines.append(f"• <b>{rtitle}</b> · {rtype} · {rfmt}{rep_str}")
        graph = "\n".join(rel_lines)
        rows += ["", f"<blockquote expandable><b>{t(M.RELATION_GRAPH)}</b>\n{graph}</blockquote>"]

    rows += ["", t(M.CONFIRM_QUESTION)]
    kb = _kb([[(t(M.BTN_SERIES_YES), cb("series_yes", str(media_data.get("anilist_id", "")))),
               (t(M.BTN_SERIES_NO), cb("series_no"))]])

    # Image priority: TMDB backdrop → AniList banner → cover → random local art.
    image: str | Path | None = None
    if backdrop_path:
        image = backdrop_path  # URL string, sent directly to send_photo
    elif media_data.get("banner_url"):
        image = media_data["banner_url"]
    elif media_data.get("cover_url"):
        image = media_data["cover_url"]
    return Screen(caption="\n".join(rows), image=image or pick_artwork(), keyboard=kb)


# ── backward-compat alias with adapted signature ──
def confirm_series(info: dict, image: Path | None = None) -> Screen:
    """Wrap old ``confirm_series(info, image)`` calls into the new ``confirm_franchise``."""
    target = confirm_franchise
    mapped = {
        "title": info.get("title", ""),
        "year": info.get("year"),
        "format": info.get("media_type", "").upper(),
        "status": None,
        "score": info.get("rating"),
        "studio": None,
        "genres": info.get("genres", []),
        "synopsis": info.get("overview", ""),
        "franchise_episodes": info.get("episodes"),
        "franchise_seasons": info.get("seasons") or 1,
        "franchise_movies": 0,
        "franchise_ovas": 0,
        "franchise_specials": 0,
        "relations": [],
        "anilist_id": str(info.get("id", "")),
        "anilist_url": None,
        "cover_url": None,
        "banner_url": None,
        "_source": "tmdb",
    }
    return target(mapped)


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
    btns.append([(t(M.BTN_VERSION_NEITHER), cb("series_no"))])
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

    photo = screen.image
    if photo:
        return await client.send_photo(
            chat_id,
            photo=str(photo) if isinstance(photo, Path) else photo,
            caption=screen.caption,
            parse_mode=screen.parse_mode,
            reply_markup=screen.keyboard,
        )
    return await client.send_message(
        chat_id,
        screen.caption,
        parse_mode=screen.parse_mode,
        reply_markup=screen.keyboard,
    )
