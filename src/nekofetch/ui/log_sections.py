"""Pure render builders for the log-channel control center.

Every function takes already-fetched plain data and returns an HTML string — no
Telegram I/O, no DB access — so the whole control center is unit-testable. All
copy, emoji, and style tags come from the centralized catalog
(:mod:`nekofetch.localization.messages`) so a single en.json edit restyles
everything globally.
"""

from __future__ import annotations

import html

from nekofetch.core.constants import RULE_HEAVY
from nekofetch.localization.messages import M, t
from nekofetch.ui.progress import bar, human_bytes, human_eta, human_speed

# Stage label (first word, lowercased) → leading glyph. Anything unknown falls
# back to the generic gear so a new pipeline stage still renders cleanly.
_STAGE_ICON = {
    "downloading": "⬇️", "download": "⬇️", "fetching": "⬇️", "queued": "📋",
    "assembling": "🧬", "muxing": "🧬", "merging": "🧬",
    "compressing": "🗜️", "transcoding": "🗜️", "transcode": "🗜️", "encoding": "🗜️",
    "verifying": "🔍", "verify": "🔍", "probing": "🔍",
    "rename": "✏️", "renaming": "✏️", "metadata": "🏷️", "tagging": "🏷️",
    "branding": "🎨", "watermark": "💧", "watermarking": "💧",
    "thumbnail": "🖼️", "thumbnailing": "🖼️", "subtitle": "💬", "subtitles": "💬",
    "store": "💾", "storing": "💾", "uploading": "⬆️", "upload": "⬆️",
    "processing": "⚙️", "running": "⚙️", "pending": "⏳",
}

# Audio track → short, scannable badge for the active row (what's being fetched).
_AUDIO_LABEL = {
    "subbed": "SUB", "sub": "SUB",
    "dubbed": "DUB", "dub": "DUB",
    "dual_audio": "DUAL", "dual": "DUAL",
    # Short forms from the rename template {audio} variable:
    "Sub": "SUB", "Dub": "DUB", "Dual": "DUAL", "Multi": "MULTI",
}

# Human-friendly notice labels keyed by "category.action". Anything not listed
# falls back to a title-cased version of the action.
_NOTICE_LABEL = {
    "request.submitted": "log_label_request_submitted",
    "request.source_assigned": "log_label_request_source_assigned",
    "request.approved": "log_label_request_approved",
    "request.rejected": "log_label_request_rejected",
    "queue.enqueued": "log_label_queue_enqueued",
    "download.complete": "log_label_download_complete",
    "publish.approved": "log_label_publish_approved",
    "error.download_failed": "log_label_error_download_failed",
    "error.processing_failed": "log_label_error_processing_failed",
    "admin.setting_changed": "log_label_admin_setting_changed",
}

# Fields worth surfacing inline on a notice (in priority order). Everything else
# stays out of the one-line stream to keep it scannable.
_PRIMARY_FIELDS = ("anime", "title", "code", "source", "job", "error")


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


def _header(title_key: str, ts: str | None = None) -> str:
    """Section header: emoji + bold title, a short underline rule, then an
    optional muted timestamp. The rule is intentionally short so it never wraps.
    """
    head = f"{t(title_key)}\n<i>{RULE_HEAVY}</i>"
    if ts:
        head += f"\n{t(M.CC_UPDATED, ts=_esc(ts))}"
    return head


def dashboard_section(stats, top_requested: list[tuple[str, int]], ts: str) -> str:
    stat_rows = "\n".join([
        t(M.CC_STAT_ROW, label=t(M.CC_STAT_USERS), value=stats.total_users),
        t(M.CC_STAT_ROW, label=t(M.CC_STAT_DOWNLOADS), value=stats.total_downloads),
        t(M.CC_STAT_ROW, label=t(M.CC_STAT_QUEUE), value=stats.queue_size),
        t(M.CC_STAT_ROW, label=t(M.CC_STAT_FAILED), value=stats.failed_tasks),
        t(M.CC_STAT_ROW, label=t(M.CC_STAT_PUBLISHED), value=stats.published),
    ])
    if top_requested:
        top = "\n".join(
            t(M.CC_MOST_REQUESTED_ROW, rank=i + 1, title=_esc(title), count=count)
            for i, (title, count) in enumerate(top_requested)
        )
        top_block = f"\n\n{t(M.CC_MOST_REQUESTED)}\n{top}"
    else:
        top_block = ""
    return f"{_header(M.CC_DASHBOARD_TITLE, ts)}\n\n{stat_rows}{top_block}"


def pending_section(reqs: list[dict], ts: str) -> str:
    if not reqs:
        body = t(M.CC_EMPTY_PENDING)
    else:
        body = "\n".join(
            t(M.CC_PENDING_ROW, code=_esc(r["code"]),
              title=_esc(r["title"]), by=_esc(r.get("by", "—")))
            for r in reqs
        )
    return f"{_header(M.CC_PENDING_TITLE, ts)}\n\n{body}"


def active_section(rows: list[dict], ts: str) -> str:
    body = "\n".join(active_row(r) for r in rows) if rows else t(M.CC_EMPTY_ACTIVE)
    return f"{_header(M.CC_ACTIVE_TITLE, ts)}\n\n{body}"


def _stage_glyph(stage: str) -> str:
    key = (stage or "").strip().lower().split()[0] if stage else ""
    return _STAGE_ICON.get(key, "⚙️")


def active_row(r: dict) -> str:
    """One richly-detailed active task: title + episode line, a stage line with a
    full-width bar and percent, and a stats line (speed · size · ETA). Every piece
    is shown only when its data is present, so a probe-only stage stays tidy while
    a live download shows the lot."""
    pct = int(r.get("progress", 0) or 0)
    stage = str(r.get("stage") or "").strip()

    # ── episode line ── "📺 S01E005 (5/220)"
    ep_block = ""
    episode = r.get("episode")
    if episode:
        season = int(r.get("season") or 1)
        of = ""
        idx, tot = r.get("ep_index"), r.get("ep_total")
        if idx and tot:
            of = t(M.CC_ACTIVE_EP_OF, index=idx, total=tot)
        ep_block = t(
            M.CC_ACTIVE_EP,
            season=f"{season:02d}",
            episode=f"{int(episode):03d}",
            of=of,
        )

    # ── version line ── exactly what's being fetched: quality + SUB/DUB/DUAL
    ver_bits = []
    if r.get("resolution"):
        ver_bits.append(str(r["resolution"]))
    aud = _AUDIO_LABEL.get(str(r.get("audio") or "").lower())
    if aud:
        ver_bits.append(aud)
    ver_block = t(M.CC_ACTIVE_VER, ver=_esc(" · ".join(ver_bits))) if ver_bits else ""

    # ── stage line ── glyph + stage label, falls back to a neutral marker
    stage_label = f"{_stage_glyph(stage)} {_esc(stage)}" if stage else "⚙️ <i>working</i>"

    # ── stats line ── only the parts we actually know
    parts: list[str] = []
    speed = float(r.get("speed_bps") or 0)
    if speed > 0:
        parts.append(t(M.CC_ACTIVE_STAT_SPEED, speed=_esc(human_speed(speed))))
    done, total = int(r.get("done") or 0), int(r.get("total") or 0)
    if total > 0:
        parts.append(t(M.CC_ACTIVE_STAT_SIZE,
                       done=_esc(human_bytes(done)), total=_esc(human_bytes(total))))
    elif done > 0:
        parts.append(t(M.CC_ACTIVE_STAT_SIZE_NOTOTAL, done=_esc(human_bytes(done))))
    eta = r.get("eta_seconds")
    if eta is not None:
        parts.append(t(M.CC_ACTIVE_STAT_ETA, eta=_esc(human_eta(eta))))
    stats = t(M.CC_ACTIVE_STAT_SEP).join(parts) if parts else "<i>starting…</i>"

    return t(
        M.CC_ACTIVE_ROW,
        title=_esc(r.get("title", "—")),
        ep=ep_block,
        ver=ver_block,
        stage=stage_label,
        bar=bar(pct, width=16).split(" ")[0],
        pct=pct,
        stats=stats,
    )


def completed_section(items: list[dict], ts: str) -> str:
    if not items:
        body = t(M.CC_EMPTY_COMPLETED)
    else:
        body = "\n".join(
            t(M.CC_COMPLETED_ROW, title=_esc(it["title"]), seasons=_esc(it.get("seasons", "")))
            for it in items
        )
    return f"{_header(M.CC_COMPLETED_TITLE, ts)}\n\n{body}"


def notices_section(lines: list[str], ts: str) -> str:
    # The rolling event log lives inside one expandable blockquote — the only
    # place blockquotes are used in the control center.
    if lines:
        body = f"<blockquote expandable>{chr(10).join(lines)}</blockquote>"
    else:
        body = t(M.CC_EMPTY_NOTICES)
    return f"{_header(M.CC_NOTICES_TITLE, ts)}\n\n{body}"


def notice_line(category: str, action: str, ts: str, fields: dict | None = None) -> str:
    """One activity-stream line: emoji + human label + the single most relevant
    field, with a muted timestamp. Reads like English, not a log dump.

    Pipeline stages (``processing`` / ``download`` actions) get a per-STAGE glyph so
    Verify/Metadata/Branding/Thumbnail/Store/Upload/Complete are visually distinct,
    instead of every step sharing one gear."""
    fields = fields or {}
    # A distinct glyph per pipeline stage where one applies; otherwise the category
    # emoji. Only processing.complete (download + processing + DB upload all done) is
    # the true end-of-everything marker → ✅.
    if category == "processing" and action == "complete":
        emoji = "✅"
    elif category in ("processing", "download"):
        glyph = _stage_glyph(action)
        emoji = glyph if glyph != "⚙️" else t(M.LOG_EMOJI.get(category, "log_emoji_system"))
    else:
        emoji = t(M.LOG_EMOJI.get(category, "log_emoji_system"))
    label_key = _NOTICE_LABEL.get(f"{category}.{action}")
    label = t(label_key) if label_key else action.replace("_", " ").title()
    primary = ""
    for key in _PRIMARY_FIELDS:
        if fields.get(key) not in (None, ""):
            primary = f"  ·  {_esc(fields[key])}"
            break
    return t(M.CC_NOTICE_ROW, glyph=emoji, label=label, primary=primary, ts=_esc(ts))


def catalog_section(items: list[tuple[str, str]], ts: str) -> str:
    if not items:
        body = t(M.CC_EMPTY_CATALOG)
    else:
        body = "\n".join(
            t(M.CC_COMPLETED_ROW, title=_esc(title), seasons=_esc(seasons))
            for title, seasons in items
        )
    return f"{_header(M.CC_CATALOG_TITLE, ts)}\n\n{body}"


# Descriptive, bold reserved-slot placeholders, rotated by index.
_RESERVED_KEYS = (M.CC_RESERVED_1, M.CC_RESERVED_2, M.CC_RESERVED_3)


def reserved_placeholder(index: int = 0) -> str:
    return t(_RESERVED_KEYS[index % len(_RESERVED_KEYS)])


def inbox_idle() -> str:
    """The persistent request-inbox in its idle state — a single, stable status
    line shown when no request is awaiting source assignment."""
    return t(M.CC_INBOX_IDLE)


def request_card(code: str, title: str, by: str, scope: str) -> str:
    return (
        t(M.CC_REQUEST_CARD_TITLE, code=_esc(code)) + "\n\n"
        + t(M.CC_REQUEST_CARD_BODY, title=_esc(title), by=_esc(by), scope=_esc(scope))
        + f"\n\n{t(M.CC_REQUEST_CHOOSE_SOURCE)}"
    )


def ambiguity_card(code: str, title: str, question: str) -> str:
    return (
        t(M.CC_AMBIGUITY_TITLE, code=_esc(code)) + "\n\n"
        + t(M.CC_AMBIGUITY_BODY, title=_esc(title), question=_esc(question))
    )


def conversation_line(name: str, text: str) -> str:
    """One human chat line in the conversation section: ``[<b>Name</b>]: text``.
    Both fields are HTML-escaped — the poster's text is shown literally, never as
    markup."""
    return t(M.CC_CONVO_LINE, name=_esc(name), text=_esc(text))


def failure_card(code: str, title: str, stage: str, error: str) -> str:
    """A prominent standalone failure card for a failed download/processing job."""
    return (
        t(M.CC_FAILURE_TITLE, code=_esc(code)) + "\n\n"
        + t(M.CC_FAILURE_BODY, title=_esc(title), stage=_esc(stage), error=_esc(error))
    )


def attention_card(code: str, title: str, failures: list) -> str:
    """Card for episodes that couldn't be downloaded — the rest of the series
    already shipped; these need a Retry / Switch-source / Provide-file decision.

    ``failures`` is ``[{"ep": n, "audio": "subbed"|"dubbed"|...}]`` so each line
    states WHICH version failed (e.g. "Ep 2 · SUB"), not just an episode number."""
    parts = []
    for f in failures:
        badge = _AUDIO_LABEL.get(str(f.get("audio") or "").lower())
        parts.append(f"Ep {f['ep']}" + (f" · {badge}" if badge else ""))
    body = "  /  ".join(parts) or "—"
    return (
        t(M.CC_ATTENTION_TITLE, code=_esc(code)) + "\n\n"
        + t(M.CC_ATTENTION_BODY, title=_esc(title), episodes=_esc(body))
    )
