"""v2 user-facing screens — artwork + HTML caption + keyboard per surface.

Pure builders (no Telegram I/O) so they're unit-testable and the handlers stay
declarative. Follows the approved redesign: HTML parse mode, bold-first emphasis,
colon-separated fields, no code styling for ordinary text, a 16:9 artwork on
every major surface (chosen with no back-to-back repeats), and inline buttons.

Each builder returns a ``Screen``; the caller sends/edits it as a photo message
(caption = ``Screen.caption``, parse_mode=HTML, photo=``Screen.image``).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.ui.artwork import pick_artwork
from nekofetch.ui.components import cb

# ── status glyphs (lifecycle / lists) ──
DONE, CURRENT, PENDING = "●", "➤", "◌"


@dataclass(slots=True)
class Screen:
    caption: str
    image: Path | None = None
    keyboard: InlineKeyboardMarkup | None = None
    parse_mode: str = "HTML"


def _esc(text: str) -> str:
    """Escape user/3rd-party text for HTML parse mode."""
    return html.escape(text or "", quote=False)


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(lbl, callback_data=data) for lbl, data in row]
         for row in rows]
    )


def _field(label: str, value: str) -> str:
    """Clean ``Label : value`` row — bold label, plain value, no boxes."""
    return f"<b>{_esc(label)}</b> : {_esc(value)}"


# ── User screens ───────────────────────────────────────────────────────────

def welcome(user_name: str) -> Screen:
    name = _esc(user_name) or "there"
    caption = (
        f"🐾  <b>Hi {name} — welcome to NekoFetch.</b>\n\n"
        "I fetch anime for you. Ask for any title and I'll source it, clean it "
        "up, brand it, and deliver it — <b>subs, dual audio, the works</b>.\n\n"
        "<i>Already in our library?</i> You get it instantly.\n"
        "<i>Not yet?</i> I'll go get it.\n\n"
        "What would you like to do?"
    )
    kb = _kb([[("🔎 Request Anime", cb("req_new")),
               ("📥 My Requests", cb("my_reqs"))]])
    return Screen(caption=caption, image=pick_artwork(), keyboard=kb)


def my_requests(user_name: str, requests: list[dict]) -> Screen:
    """`requests`: dicts with ``title`` and ``status`` (a short status label)."""
    name = _esc(user_name) or "you"
    lines = [f"📥  <b>{name} — your requests</b>", ""]
    if not requests:
        lines.append("<i>No requests yet. Tap “Request Anime” to start.</i>")
    else:
        width = min(28, max((len(r["title"]) for r in requests), default=0))
        for r in requests:
            title = _esc(r["title"])[:28]
            lines.append(f"{title.ljust(width)} :  {_esc(r['status'])}")
        ready = sum(1 for r in requests if "ready" in r["status"].lower())
        prog = sum(1 for r in requests if any(
            k in r["status"].lower() for k in ("process", "queue", "download", "upload")))
        wait = sum(1 for r in requests if "need" in r["status"].lower())
        lines += ["", f"<i>{len(requests)} total · {ready} ready · "
                      f"{prog} in progress · {wait} waiting on you</i>"]
    kb = _kb([[("🔎 Request Anime", cb("req_new"))], [("⬅ Back", cb("home"))]])
    return Screen(caption="\n".join(lines), image=pick_artwork(), keyboard=kb)


def ask_title() -> Screen:
    caption = (
        "🔎  <b>Which anime?</b>\n\n"
        "Send me a name — English, Japanese, or a short form.\n"
        "<i>Examples : Attack on Titan · Shingeki no Kyojin · AoT</i>"
    )
    return Screen(caption=caption, image=pick_artwork(),
                  keyboard=_kb([[("⬅ Back", cb("home"))]]))


def searching(query: str, frame: str = "⠹") -> Screen:
    """Transient animated state (caller cycles ``frame``)."""
    return Screen(caption=f"🔎  Looking up <b>{_esc(query)}</b> {frame}", image=None)


def confirm_series(info: dict, image: Path | None = None) -> Screen:
    """TMDB-backed single-series confirmation card. ``info`` = TmdbResult-like dict."""
    rows = [f"🎬  <b>{_esc(info['title'])}</b>"
            + (f"  <i>({_esc(str(info['year']))})</i>" if info.get("year") else ""), ""]
    if info.get("media_type"):
        rows.append(_field("Type", "TV Series" if info["media_type"] == "tv" else "Movie"))
    if info.get("seasons") or info.get("episodes"):
        seasons = info.get("seasons")
        episodes = info.get("episodes")
        bits = []
        if seasons:
            bits.append(f"{seasons} season{'s' if seasons != 1 else ''}")
        if episodes:
            bits.append(f"{episodes} episodes")
        rows.append(_field("Content", " · ".join(bits)))
    if info.get("genres"):
        rows.append(_field("Genres", " · ".join(info["genres"][:4])))
    if info.get("rating"):
        rows.append(_field("Rating", str(info["rating"])))
    if info.get("overview"):
        ov = _esc(info["overview"])
        ov = ov[:300].rsplit(" ", 1)[0] + "…" if len(ov) > 300 else ov
        rows += ["", f"<blockquote expandable>{ov}</blockquote>"]
    rows += ["", "<b>Is this the one?</b>"]
    kb = _kb([[("✅ Yes, that's it", cb("series_yes", info.get("id", ""))),
               ("❌ Not this", cb("series_no"))]])
    return Screen(caption="\n".join(rows), image=image or pick_artwork(), keyboard=kb)


def choose_version(query: str, versions: list[dict]) -> Screen:
    """Distinct-version chooser (Hellsing vs Ultimate, Naruto vs Shippuuden)."""
    rows = [f"🔎  <b>“{_esc(query)}” comes in distinct versions. Which one?</b>", ""]
    width = min(24, max((len(v["title"]) for v in versions), default=0))
    for v in versions:
        meta = " · ".join(str(x) for x in (v.get("format"), v.get("year"),
                          f"{v['episodes']} eps" if v.get("episodes") else None) if x)
        rows.append(f"{_esc(v['title'])[:24].ljust(width)} :  <i>{_esc(meta)}</i>")
    btns = [[(v["title"][:32], cb("ver_pick", v.get("id", i)))]
            for i, v in enumerate(versions)]
    btns.append([("❌ Neither", cb("series_no"))])
    return Screen(caption="\n".join(rows), image=pick_artwork(), keyboard=_kb(btns))


def retry_title() -> Screen:
    caption = (
        "🔎  <b>My bad — let's try again.</b>\n\n"
        "Give me the title a bit more precisely (add the year or the Japanese "
        "name if you can)."
    )
    return Screen(caption=caption, image=pick_artwork(),
                  keyboard=_kb([[("⬅ Back", cb("home"))]]))


def request_received(user_name: str, title: str, queue_pos: int | None = None) -> Screen:
    name = _esc(user_name) or "there"
    rows = [f"📥  <b>Got it, {name}.</b>", "",
            _field("Anime", title),
            _field("Status", "⏳ Queued for sourcing")]
    if queue_pos is not None:
        rows.append(_field("Queue", f"#{queue_pos}"))
    rows += ["", "<i>I'll fetch → process → brand → publish it, and ping you "
                 "here the moment it's ready.</i>"]
    return Screen(caption="\n".join(rows), image=pick_artwork(),
                  keyboard=_kb([[("📥 My Requests", cb("my_reqs"))]]))


# ── Log channel: one live card per request, edited as state advances ─────────

# Ordered lifecycle; the engine advances `current` through these.
LIFECYCLE = [
    "Requested", "Pending", "Source Assigned", "Downloading",
    "Processing Metadata", "Extracting Subtitles", "Applying Watermark",
    "Uploading", "Published", "Completed",
]


def log_card(req: dict) -> Screen:
    """Live log card. ``req`` keys: id, title, requester, source, state,
    optional substate (e.g. 'ep 3/25'), optional failed/reason for blocked."""
    title = _esc(req.get("title", "Unknown"))
    state = req.get("state", "Requested")

    if req.get("failed"):
        rows = [f"⚠️  <b>{title}</b>", "",
                _field("Stuck at", state),
                _field("Reason", req.get("reason", "unknown")),
                _field("Source", req.get("source", "—"))]
        if req.get("detail"):
            rows += ["", f"<blockquote expandable>{_esc(req['detail'])}</blockquote>"]
        kb = _kb([[("🔁 Retry", cb("log_retry", req.get("id", ""))),
                   ("🔀 Reassign", cb("log_reassign", req.get("id", ""))),
                   ("✖ Dismiss", cb("log_dismiss", req.get("id", "")))]])
        return Screen(caption="\n".join(rows), image=pick_artwork(), keyboard=kb)

    if state == "Completed":
        # Completed: no redundant status field — show what matters.
        rows = [f"✅  <b>{title}</b>", ""]
        for label in ("seasons", "qualities", "episodes", "source", "took"):
            if req.get(label):
                rows.append(_field(label.capitalize(), str(req[label])))
        return Screen(caption="\n".join(rows), image=pick_artwork())

    sub = f"  ·  {_esc(req['substate'])}" if req.get("substate") else ""
    rows = [f"🐾  <b>{title}</b>", "",
            _field("Request", f"#{req.get('id', '—')}"),
            _field("By", req.get("requester", "—")),
            _field("Source", req.get("source", "—")),
            _field("Now", f"{state}{sub}"), ""]
    # checklist with current step marked
    try:
        cur_idx = LIFECYCLE.index(state)
    except ValueError:
        cur_idx = 0
    for i, step in enumerate(LIFECYCLE):
        glyph = DONE if i < cur_idx else (CURRENT if i == cur_idx else PENDING)
        label = f"<b>{step}</b>" if i == cur_idx else step
        rows.append(f"{glyph}  {label}")
    return Screen(caption="\n".join(rows), image=pick_artwork())
