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
from nekofetch.ui.progress import bar, human_eta

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


def active_row(r: dict) -> str:
    pct = int(r.get("progress", 0) or 0)
    return t(
        M.CC_ACTIVE_ROW,
        title=_esc(r.get("title", "—")),
        stage=_esc(r.get("stage", "")),
        bar=bar(pct, width=12).split(" ")[0],
        pct=pct,
        eta=_esc(human_eta(r.get("eta_seconds"))),
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
    field, with a muted timestamp. Reads like English, not a log dump."""
    fields = fields or {}
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
