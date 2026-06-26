"""v2 user-facing screens — artwork + HTML caption + keyboard per surface.

Pure builders (no Telegram I/O), unit-testable, handlers stay declarative. Every
visible string comes from the centralized catalog (``localization.messages``) —
no raw text here. HTML parse mode, bold-first emphasis, colon-separated fields,
no code styling, a 16:9 artwork (no back-to-back repeats) on every major surface.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.localization.messages import PARSE_MODE, M, t
from nekofetch.ui.artwork import pick_artwork
from nekofetch.ui.components import cb

# ── status glyphs (lifecycle / lists) ──
DONE, CURRENT, PENDING = "●", "➤", "◌"

# Lifecycle order; labels resolve from the catalog at render time.
_LIFECYCLE_KEYS = [
    M.LC_REQUESTED, M.LC_PENDING, M.LC_SOURCE_ASSIGNED, M.LC_DOWNLOADING,
    M.LC_PROCESSING_META, M.LC_EXTRACTING_SUBS, M.LC_WATERMARK,
    M.LC_UPLOADING, M.LC_PUBLISHED, M.LC_COMPLETED,
]


@dataclass(slots=True)
class Screen:
    caption: str
    image: Path | None = None
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: str = PARSE_MODE


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
    kb = _kb([[(t(M.BTN_REQUEST_ANIME), cb("req_new")),
               (t(M.BTN_MY_REQUESTS), cb("my_reqs"))]])
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
    kb = _kb([[(t(M.BTN_REQUEST_ANIME), cb("req_new"))],
              [(t(M.BTN_BACK), cb("home"))]])
    return Screen(caption="\n".join(lines), image=pick_artwork(), keyboard=kb)


def ask_title() -> Screen:
    return Screen(caption=t(M.ASK_TITLE), image=pick_artwork(),
                  keyboard=_kb([[(t(M.BTN_BACK), cb("home"))]]))


def searching(query: str, frame: str = "⠹") -> Screen:
    return Screen(caption=t(M.SEARCHING, query=_esc(query), frame=frame), image=None)


def confirm_series(info: dict, image: Path | None = None) -> Screen:
    header = t(M.CONFIRM_HEADER, title=_esc(info["title"]))
    if info.get("year"):
        header += f"  <i>({_esc(str(info['year']))})</i>"
    rows = [header, ""]
    if info.get("media_type"):
        rows.append(_field(M.F_TYPE,
                    t(M.VALUE_TV) if info["media_type"] == "tv" else t(M.VALUE_MOVIE)))
    if info.get("seasons") or info.get("episodes"):
        bits = []
        if info.get("seasons"):
            bits.append(f"{info['seasons']} season{'s' if info['seasons'] != 1 else ''}")
        if info.get("episodes"):
            bits.append(f"{info['episodes']} episodes")
        rows.append(_field(M.F_CONTENT, t(M.SEP_DOT).join(bits)))
    if info.get("genres"):
        rows.append(_field(M.F_GENRES, t(M.SEP_DOT).join(info["genres"][:4])))
    if info.get("rating"):
        rows.append(_field(M.F_RATING, str(info["rating"])))
    if info.get("overview"):
        ov = _esc(info["overview"])
        ov = ov[:300].rsplit(" ", 1)[0] + "…" if len(ov) > 300 else ov
        rows += ["", f"<blockquote expandable>{ov}</blockquote>"]
    rows += ["", t(M.CONFIRM_QUESTION)]
    kb = _kb([[(t(M.BTN_SERIES_YES), cb("series_yes", info.get("id", ""))),
               (t(M.BTN_SERIES_NO), cb("series_no"))]])
    return Screen(caption="\n".join(rows), image=image or pick_artwork(), keyboard=kb)


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
                  keyboard=_kb([[(t(M.BTN_MY_REQUESTS), cb("my_reqs"))]]))


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
