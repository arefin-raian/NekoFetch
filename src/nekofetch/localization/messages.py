"""Centralized message catalog — the single access point for every visible string.

ALL user-facing text (bot messages, prompts, status/progress, errors, success,
admin output, log-channel cards, notifications, human-readable debug) lives in
``resources/language/<code>.json`` and is reached through this module. Business
logic references a message **key** (a constant on :class:`M`) — never a raw
string — so editing a word, emoji, or bit of HTML in the JSON propagates
everywhere with no code change.

HTML is the default parse mode; every string in the catalog is authored as HTML.

Usage::

    from nekofetch.localization.messages import t, M
    caption = t(M.WELCOME_TITLE, name="Raiyan")
"""

from __future__ import annotations

from pathlib import Path

from pyrogram.enums import ParseMode

from nekofetch.localization.i18n import Localizer

# Default parse mode for everything rendered from the catalog.
PARSE_MODE = ParseMode.HTML

_LANG_DIR = Path(__file__).resolve().parents[3] / "resources" / "language"
_localizer = Localizer(_LANG_DIR, default="en")


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Resolve a catalog ``key`` to its HTML string, formatting ``{placeholders}``.

    Unknown keys fall back to the default language then to the key itself, so a
    gap is visible rather than crashing.
    """
    return _localizer.get(key, lang=lang, **kwargs)


def reload() -> None:
    """Re-read the JSON catalogs (e.g. after an admin edits a message)."""
    _localizer.reload()


def languages() -> list[str]:
    return _localizer.languages


class M:
    """Message keys. The string value IS the JSON key — reference these, never
    raw text. Grouped by surface for navigation."""

    # ── meta / common ──
    SEP_DOT = "sep_dot"

    # ── welcome ──
    WELCOME_TITLE = "welcome_title"
    WELCOME_BODY = "welcome_body"
    WELCOME_LIBRARY = "welcome_library"

    # ── buttons ──
    BTN_REQUEST_ANIME = "btn_request_anime"
    BTN_MY_REQUESTS = "btn_my_requests"
    BTN_BACK = "btn_back"
    BTN_CANCEL = "btn_cancel"
    BTN_SERIES_YES = "btn_series_yes"
    BTN_SERIES_NO = "btn_series_no"
    BTN_VERSION_NEITHER = "btn_version_neither"
    BTN_RETRY = "btn_retry"
    BTN_REASSIGN = "btn_reassign"
    BTN_DISMISS = "btn_dismiss"

    # ── my requests ──
    MYREQ_TITLE = "myreq_title"
    MYREQ_EMPTY = "myreq_empty"
    MYREQ_ROW = "myreq_row"
    MYREQ_SUMMARY = "myreq_summary"

    # ── search / confirm ──
    ASK_TITLE = "ask_title"
    SEARCHING = "searching"
    CONFIRM_HEADER = "confirm_header"
    CONFIRM_QUESTION = "confirm_question"
    VERSION_HEADER = "version_header"
    RETRY_TITLE = "retry_title"

    # ── fields (label : value) ──
    F_TYPE = "field_type"
    F_CONTENT = "field_content"
    F_GENRES = "field_genres"
    F_RATING = "field_rating"
    F_ANIME = "field_anime"
    F_STATUS = "field_status"
    F_QUEUE = "field_queue"
    F_REQUEST = "field_request"
    F_BY = "field_by"
    F_SOURCE = "field_source"
    F_NOW = "field_now"
    F_STUCK_AT = "field_stuck_at"
    F_REASON = "field_reason"
    F_SEASONS = "field_seasons"
    F_QUALITIES = "field_qualities"
    F_EPISODES = "field_episodes"
    F_TOOK = "field_took"

    VALUE_TV = "value_tv_series"
    VALUE_MOVIE = "value_movie"
    VALUE_QUEUED = "value_queued"

    # ── request received ──
    REQ_RECEIVED = "req_received"
    REQ_RECEIVED_BODY = "req_received_body"

    # ── lifecycle steps (log card) ──
    LC_REQUESTED = "lc_requested"
    LC_PENDING = "lc_pending"
    LC_SOURCE_ASSIGNED = "lc_source_assigned"
    LC_DOWNLOADING = "lc_downloading"
    LC_PROCESSING_META = "lc_processing_metadata"
    LC_EXTRACTING_SUBS = "lc_extracting_subtitles"
    LC_WATERMARK = "lc_applying_watermark"
    LC_UPLOADING = "lc_uploading"
    LC_PUBLISHED = "lc_published"
    LC_COMPLETED = "lc_completed"

    # ── log card headers ──
    LOG_PROGRESS_TITLE = "log_progress_title"
    LOG_COMPLETED_TITLE = "log_completed_title"
    LOG_BLOCKED_TITLE = "log_blocked_title"

    # ── admin ──
    ADMIN_NEW_REQUEST = "admin_new_request"
    ADMIN_ASSIGN_SOURCE = "admin_assign_source"
    ADMIN_BTN_TELEGRAM = "admin_btn_telegram"
    ADMIN_BTN_WEBSITE = "admin_btn_website"
    ADMIN_BTN_TORRENT = "admin_btn_torrent"
    ADMIN_BTN_REJECT = "admin_btn_reject"
    ADMIN_BTN_AUTOMATIC = "admin_btn_automatic"
    ADMIN_BTN_MANUAL = "admin_btn_manual"
    ADMIN_TG_CHOOSE = "admin_tg_choose"
    ADMIN_TG_MANUAL_PROMPT = "admin_tg_manual_prompt"

    # ── Phase 1: search / confirm ──
    CONFIRM_ANILIST_SEARCH = "confirm_anilist_search"
    CONFIRM_TMDB_FALLBACK = "confirm_tmdb_fallback"
    CONFIRM_ADAPTATION_CHOOSE = "confirm_adaptation_choose"
    BTN_CHOOSE = "btn_choose"
    BTN_READ_MORE = "btn_read_more"
    FRANCHISE_CONTENT = "franchise_content"
    RELATION_GRAPH = "relation_graph"
    UNIT_SEASONS = "unit_seasons"
    UNIT_MOVIES = "unit_movies"
    UNIT_OVAS = "unit_ovas"
    UNIT_ONAS = "unit_onas"
    UNIT_SPECIALS = "unit_specials"
    UNIT_EPS = "unit_eps"
    FIELD_STUDIO = "field_studio"
    FIELD_SCORE = "field_score"
    FIELD_FORMAT = "field_format"
    SEARCH_ANILIST_NOT_FOUND = "search_anilist_not_found"
    SEARCH_TMDB_NOT_FOUND = "search_tmdb_not_found"

    # ── website source admin ──
    SITE_PREFERENCE_TITLE = "site_preference_title"
    SITE_PREFERENCE_PROMPT = "site_preference_prompt"
    SITE_PROVIDER_ANIKOTO = "site_provider_anikoto"
    SITE_PROVIDER_KICKASS = "site_provider_kickass"
    BTN_CONFIRM_PRIORITY = "btn_confirm_priority"

    # ── log channel events ──
    LOG_REQUEST_SUBMITTED = "log_request_submitted"
    LOG_REQUEST_APPROVED = "log_request_approved"
    LOG_REQUEST_REJECTED = "log_request_rejected"
    LOG_SOURCE_ASSIGNED = "log_source_assigned"
    LOG_JOB_QUEUED = "log_job_queued"
    LOG_JOB_COMPLETED = "log_job_completed"
    LOG_JOB_FAILED = "log_job_failed"
    LOG_STAGE_COMPLETE = "log_stage_complete"
    LOG_PUBLISHED = "log_published"

    # ── errors / notices ──
    ERR_GENERIC = "error_generic"
    ERR_NOT_FOUND = "error_not_found"
    RATE_LIMITED = "rate_limited"
    ACCESS_DENIED = "access_denied"

    # ── notifications ──
    NOTIF_READY_TITLE = "notif_ready_title"
    NOTIF_READY_BODY = "notif_ready_body"
